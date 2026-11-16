
import os
import re
import uuid
import time
from pathlib import Path
from collections import Counter
from urllib.parse import urlparse

from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    url_for,
    flash
)

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user
)

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, CSRFError

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

from sqlalchemy import func

from config import Config

from variant_parser import parse_annotated_vcf
from civic_api import search_civic


# =====================================================
# 1. FLASK APPLICATION CONFIGURATION
# =====================================================

app = Flask(__name__)

app.config.from_object(Config)

# Require a secret key for secure session signing.
if not app.config.get("SECRET_KEY"):
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing. "
        "Add it to your .env file before starting the application."
    )

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_FOLDER = Path(app.config["UPLOAD_FOLDER"]).resolve()
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {".vcf"}

MAX_FILE_SIZE = 100 * 1024 * 1024

# Allow extra space for multipart form-data overhead.
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE + (1024 * 1024)

MAX_CIVIC_LOOKUPS = 100
MAX_ANNOTATION_ROWS = 500


# =====================================================
# 2. DATABASE AND AUTHENTICATION INITIALIZATION
# =====================================================

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)

login_manager.login_view = "login"
login_manager.login_message = "Please log in to access VCF Analyzer."
login_manager.login_message_category = "warning"

# CSRF protection for HTML forms and API requests.
csrf = CSRFProtect(app)


# =====================================================
# 3. DATABASE MODELS
# =====================================================

class User(UserMixin, db.Model):

    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(80),
        nullable=False
    )

    # Used for case-insensitive unique name checking.
    name_key = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        nullable=False
    )

    uploaded_files = db.relationship(
        "UploadedFile",
        backref="owner",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        """Store a secure password hash."""

        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a password against its stored hash."""

        return check_password_hash(
            self.password_hash,
            password
        )


class UploadedFile(db.Model):

    __tablename__ = "uploaded_files"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    filename = db.Column(
        db.String(255),
        unique=True,
        nullable=False
    )

    original_filename = db.Column(
        db.String(255),
        nullable=False
    )

    uploaded_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        nullable=False
    )


@login_manager.user_loader
def load_user(user_id):
    """Load the logged-in user from the database."""

    try:
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        return None


# Make CSRF token available to every template.
@app.context_processor
def inject_csrf_token():
    from flask_wtf.csrf import generate_csrf

    return {
        "csrf_token": generate_csrf
    }


# Create database tables if they do not exist.
with app.app_context():
    db.create_all()


# =====================================================
# 4. AUTHENTICATION HELPERS
# =====================================================

def is_safe_redirect_url(target):
    """Prevent redirects to external websites after login."""

    if not target:
        return False

    host_url = urlparse(request.host_url)
    redirect_url = urlparse(
        request.host_url + target.lstrip("/")
        if target.startswith("/")
        else target
    )

    return (
        redirect_url.scheme in ("http", "https")
        and redirect_url.netloc == host_url.netloc
    )


@login_manager.unauthorized_handler
def unauthorized():

    # Return JSON for API requests instead of login-page HTML.
    if request.path in (
        "/upload-vcf",
        "/analyze-vcf",
        "/civic-lookup"
    ):
        return jsonify({
            "status": "error",
            "message": "Authentication required. Please log in."
        }), 401

    return redirect(url_for("login"))


@app.errorhandler(CSRFError)
def handle_csrf_error(error):

    if request.path in (
        "/upload-vcf",
        "/analyze-vcf",
        "/civic-lookup"
    ):
        return jsonify({
            "status": "error",
            "message": "Invalid or missing CSRF token. Refresh the page and try again."
        }), 400

    flash(
        "Your form session expired. Please try again.",
        "error"
    )

    return redirect(url_for("login"))


# =====================================================
# 5. REGISTRATION
# =====================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        # Validate name.
        if len(name) < 3 or len(name) > 80:

            flash(
                "Name must contain between 3 and 80 characters.",
                "error"
            )

            return render_template("register.html"), 400

        if not name.isprintable():

            flash(
                "Please enter a valid name.",
                "error"
            )

            return render_template("register.html"), 400

        # Validate password.
        if len(password) < 8 or len(password) > 128:

            flash(
                "Password must contain between 8 and 128 characters.",
                "error"
            )

            return render_template("register.html"), 400

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return render_template("register.html"), 400

        name_key = name.casefold()

        # Check for an existing account.
        existing_user = User.query.filter_by(
            name_key=name_key
        ).first()

        if existing_user:

            flash(
                "An account with this name already exists.",
                "error"
            )

            return render_template("register.html"), 409

        try:

            new_user = User(
                name=name,
                name_key=name_key
            )

            new_user.set_password(password)

            db.session.add(new_user)
            db.session.commit()

            flash(
                "Account created successfully. Please log in.",
                "success"
            )

            return redirect(url_for("login"))

        except Exception:

            db.session.rollback()

            app.logger.exception("User registration failed")

            flash(
                "Unable to create your account. Please try again.",
                "error"
            )

            return render_template("register.html"), 500

    return render_template("register.html")


# =====================================================
# 6. LOGIN
# =====================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")

        if not name or not password:

            flash(
                "Please enter your name and password.",
                "error"
            )

            return render_template("login.html"), 400

        user = User.query.filter_by(
            name_key=name.casefold()
        ).first()

        if user and user.check_password(password):

            login_user(
                user,
                remember=False,
                fresh=True
            )

            next_page = request.args.get("next")

            if next_page and is_safe_redirect_url(next_page):
                return redirect(next_page)

            return redirect(url_for("home"))

        flash(
            "Invalid name or password.",
            "error"
        )

        return render_template("login.html"), 401

    return render_template("login.html")


# =====================================================
# 7. LOGOUT
# =====================================================

@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():

    if request.method == "POST":
        logout_user()

        flash(
            "You have been logged out successfully.",
            "success"
        )

        return redirect(url_for("login"))

    # Retain compatibility with the existing logout link.
    # A POST form with CSRF protection is recommended.
    return render_template("login.html")


# =====================================================
# 8. FILE VALIDATION FUNCTIONS
# =====================================================

def allowed_file(filename):
    """Check whether the uploaded file has a VCF extension."""

    if not filename:
        return False

    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def validate_vcf(file_path):
    """Check whether the file begins with a VCFv4 header."""

    try:

        with open(file_path, "rb") as file:

            first_line = file.readline().strip()

            return bool(
                re.fullmatch(
                    rb"##fileformat=VCFv4\.\d+",
                    first_line
                )
            )

    except OSError:
        return False


def get_uploaded_vcf(filename):
    """
    Validate the filename and verify that the logged-in user owns it.

    Returns:
        (file_path, None) on success
        (None, error_response) on failure
    """

    if not isinstance(filename, str) or not filename:

        return None, (
            jsonify({
                "status": "error",
                "message": "Please provide the uploaded VCF filename."
            }),
            400
        )

    safe_filename = secure_filename(filename)

    if (
        safe_filename != filename
        or not allowed_file(safe_filename)
    ):

        return None, (
            jsonify({
                "status": "error",
                "message": "Invalid VCF filename."
            }),
            400
        )

    # Verify file ownership using the database.
    uploaded_record = UploadedFile.query.filter_by(
        filename=safe_filename,
        user_id=current_user.id
    ).first()

    if not uploaded_record:

        return None, (
            jsonify({
                "status": "error",
                "message": (
                    "File not found or you do not have permission "
                    "to access this file."
                )
            }),
            404
        )

    file_path = (
        UPLOAD_FOLDER / safe_filename
    ).resolve()

    if file_path.parent != UPLOAD_FOLDER:

        return None, (
            jsonify({
                "status": "error",
                "message": "Invalid file path."
            }),
            400
        )

    if not file_path.is_file():

        return None, (
            jsonify({
                "status": "error",
                "message": "Uploaded VCF file not found."
            }),
            404
        )

    if file_path.stat().st_size > MAX_FILE_SIZE:

        return None, (
            jsonify({
                "status": "error",
                "message": "VCF file exceeds the 100 MB limit."
            }),
            413
        )

    if not validate_vcf(file_path):

        return None, (
            jsonify({
                "status": "error",
                "message": "Invalid VCF file format."
            }),
            400
        )

    return file_path, None


# =====================================================
# 9. VCF UPLOAD API
# =====================================================

@app.route("/upload-vcf", methods=["POST"])
@login_required
def upload_vcf():

    temp_path = None
    final_path = None

    try:

        if "file" not in request.files:

            return jsonify({
                "status": "error",
                "message": "No file provided. Please upload a VCF file."
            }), 400

        file = request.files["file"]

        if not file.filename:

            return jsonify({
                "status": "error",
                "message": "No file selected."
            }), 400

        if not allowed_file(file.filename):

            return jsonify({
                "status": "error",
                "message": "Only .vcf files are allowed."
            }), 400

        original_filename = secure_filename(file.filename)

        if not original_filename:

            return jsonify({
                "status": "error",
                "message": "Invalid filename."
            }), 400

        unique_filename = (
            f"{uuid.uuid4().hex}_{original_filename}"
        )

        temp_path = UPLOAD_FOLDER / f"{unique_filename}.part"
        final_path = UPLOAD_FOLDER / unique_filename

        file_size = 0

        with open(temp_path, "wb") as output:

            while True:

                chunk = file.stream.read(1024 * 1024)

                if not chunk:
                    break

                file_size += len(chunk)

                if file_size > MAX_FILE_SIZE:
                    raise RequestEntityTooLarge()

                output.write(chunk)

        if file_size == 0:

            return jsonify({
                "status": "error",
                "message": "Uploaded file is empty."
            }), 400

        if not validate_vcf(temp_path):

            return jsonify({
                "status": "error",
                "message": (
                    "Invalid VCF content. "
                    "A valid VCFv4 file format header is required."
                )
            }), 400

        # Move temporary file to its final location.
        os.replace(temp_path, final_path)
        temp_path = None

        # Record file ownership in the database.
        uploaded_record = UploadedFile(
            user_id=current_user.id,
            filename=unique_filename,
            original_filename=original_filename
        )

        db.session.add(uploaded_record)
        db.session.commit()

        return jsonify({

            "status": "success",
            "message": "VCF file uploaded successfully.",
            "filename": unique_filename,
            "original_filename": original_filename,
            "file_size_bytes": file_size,
            "file_size_MB": round(
                file_size / (1024 * 1024),
                2
            )

        }), 200

    except RequestEntityTooLarge:

        return jsonify({
            "status": "error",
            "message": "File size exceeds the maximum allowed limit of 100 MB."
        }), 413

    except OSError:

        db.session.rollback()

        if final_path and final_path.exists():
            final_path.unlink(missing_ok=True)

        app.logger.exception("File storage error")

        return jsonify({
            "status": "error",
            "message": "Unable to save the uploaded file."
        }), 500

    except Exception:

        db.session.rollback()

        if final_path and final_path.exists():
            final_path.unlink(missing_ok=True)

        app.logger.exception("Unexpected upload error")

        return jsonify({
            "status": "error",
            "message": "An unexpected error occurred during upload."
        }), 500

    finally:

        if temp_path is not None and temp_path.exists():

            try:
                temp_path.unlink()
            except OSError:
                app.logger.exception(
                    "Unable to remove temporary upload file"
                )


# =====================================================
# 10. HANDLE LARGE REQUEST ERRORS
# =====================================================

@app.errorhandler(413)
def handle_large_file(error):

    return jsonify({
        "status": "error",
        "message": "Request too large. Maximum file size is 100 MB."
    }), 413


# =====================================================
# 11. HOME PAGE
# =====================================================

@app.route("/", methods=["GET"])
@login_required
def home():

    return render_template("index.html")


# =====================================================
# 12. EXTRACT GENE ANNOTATIONS
# =====================================================

def extract_genes(info, annotation_fields):

    genes = set()

    if "GENE" in info:

        for gene in info["GENE"].split(","):

            gene = gene.strip()

            if gene and gene != ".":
                genes.add(gene)

    for annotation_type in ["CSQ", "ANN"]:

        if annotation_type not in info:
            continue

        annotations = info[annotation_type].split(",")

        fields = annotation_fields.get(
            annotation_type,
            []
        )

        if not fields:
            continue

        possible_names = [
            "SYMBOL",
            "Gene_Name",
            "GENE",
            "Gene",
            "Gene_ID"
        ]

        gene_index = None

        for name in possible_names:

            if name in fields:
                gene_index = fields.index(name)
                break

        if gene_index is None:
            continue

        for annotation in annotations:

            values = annotation.split("|")

            if gene_index < len(values):

                gene = values[gene_index].strip()

                if gene and gene != ".":
                    genes.add(gene)

    return genes


# =====================================================
# 13. ANALYZE VCF FILE
# =====================================================

def analyze_vcf(file_path):

    total_variants = 0

    pass_count = 0
    filtered_count = 0
    unfiltered_count = 0

    filter_reasons = Counter()
    gene_distribution = Counter()
    quality_values = []

    annotation_fields = {}

    with open(
        file_path,
        "r",
        encoding="utf-8",
        errors="replace"
    ) as vcf:

        for line in vcf:

            line = line.strip()

            if not line:
                continue

            # Read INFO annotation definitions.
            if line.startswith("##INFO="):

                annotation_type = None

                if "ID=CSQ," in line:
                    annotation_type = "CSQ"

                elif "ID=ANN," in line:
                    annotation_type = "ANN"

                if annotation_type:

                    if annotation_type == "CSQ":

                        match = re.search(
                            r"Format:\s*['\"]?(.+?)(?:['\"]?>?$)",
                            line
                        )

                    else:

                        match = re.search(
                            r"Functional annotations:\s*'([^']+)'",
                            line
                        )

                    if match:

                        annotation_fields[annotation_type] = [
                            field.strip()
                            for field in match.group(1).split("|")
                        ]

                continue

            if line.startswith("#"):
                continue

            columns = line.split("\t")

            if len(columns) < 8:
                continue

            total_variants += 1

            qual = columns[5]
            filter_value = columns[6]
            info_string = columns[7]

            # Quality assessment.
            if filter_value == "PASS":

                pass_count += 1

            elif filter_value == ".":

                unfiltered_count += 1

            else:

                filtered_count += 1

                for reason in filter_value.split(";"):
                    filter_reasons[reason] += 1

            # QUAL statistics.
            if qual != ".":

                try:

                    quality_score = float(qual)

                    if (
                        quality_score != float("inf")
                        and quality_score != float("-inf")
                    ):
                        quality_values.append(quality_score)

                except ValueError:
                    pass

            # Parse INFO column.
            info = {}

            for item in info_string.split(";"):

                if "=" in item:

                    key, value = item.split("=", 1)
                    info[key] = value

            # Gene distribution.
            genes = extract_genes(
                info,
                annotation_fields
            )

            for gene in genes:
                gene_distribution[gene] += 1

    pass_percentage = (
        round((pass_count / total_variants) * 100, 2)
        if total_variants > 0
        else 0
    )

    quality_summary = {

        "available_quality_scores": len(quality_values),

        "mean_qual": (
            round(
                sum(quality_values) / len(quality_values),
                2
            )
            if quality_values
            else None
        ),

        "minimum_qual": (
            min(quality_values)
            if quality_values
            else None
        ),

        "maximum_qual": (
            max(quality_values)
            if quality_values
            else None
        )
    }

    return {

        "total_variants": total_variants,

        "quality_assessment": {

            "PASS": pass_count,
            "FILTERED": filtered_count,
            "UNFILTERED": unfiltered_count,
            "PASS_percentage": pass_percentage,
            "filter_reasons": dict(filter_reasons),
            "QUAL_statistics": quality_summary
        },

        "gene_analysis": {

            "unique_genes": len(gene_distribution),

            "gene_distribution": dict(
                gene_distribution.most_common()
            )
        },

        "annotation_sources_detected": list(
            annotation_fields.keys()
        )
    }


# =====================================================
# 14. VCF ANALYSIS API ENDPOINT
# =====================================================

@app.route("/analyze-vcf", methods=["POST"])
@login_required
def analyze_vcf_api():

    try:

        data = request.get_json(silent=True) or {}

        file_path, error_response = get_uploaded_vcf(
            data.get("filename")
        )

        if error_response:
            return error_response

        # A. Existing VCF analysis.
        results = analyze_vcf(file_path)

        # B. Annotation extraction.
        annotation_data = {

            "status": "unavailable",

            "message": (
                "No usable VEP (CSQ) or SnpEff (ANN) "
                "annotations were detected."
            ),

            "annotation_source": None,
            "total_annotations": 0,
            "variants_with_protein_change": 0,
            "displayed_annotations": 0,
            "truncated": False,
            "variants": []

        }

        try:

            annotated_variants = parse_annotated_vcf(
                file_path
            )

            if annotated_variants:

                protein_variants = [
                    variant
                    for variant in annotated_variants
                    if variant.get("protein_change")
                ]

                annotation_source = next(
                    (
                        variant.get("annotation_source")
                        for variant in annotated_variants
                        if variant.get("annotation_source")
                    ),
                    None
                )

                displayed_variants = annotated_variants[
                    :MAX_ANNOTATION_ROWS
                ]

                annotation_data = {

                    "status": "available",

                    "message": (
                        "Variant annotations extracted successfully."
                    ),

                    "annotation_source": annotation_source,

                    "total_annotations": len(
                        annotated_variants
                    ),

                    "variants_with_protein_change": len(
                        protein_variants
                    ),

                    "displayed_annotations": len(
                        displayed_variants
                    ),

                    "truncated": (
                        len(annotated_variants)
                        > MAX_ANNOTATION_ROWS
                    ),

                    "variants": displayed_variants

                }

            else:

                annotation_data["message"] = (
                    "No usable annotated variants were found."
                )

        except ValueError as error:

            annotation_data["message"] = str(error)

        return jsonify({

            "status": "success",
            "message": "VCF analysis completed successfully.",
            "filename": file_path.name,
            "analysis": results,
            "annotation_analysis": annotation_data

        }), 200

    except OSError:

        app.logger.exception(
            "Unable to read VCF file"
        )

        return jsonify({
            "status": "error",
            "message": "Unable to read the VCF file."
        }), 500

    except Exception:

        app.logger.exception(
            "VCF analysis failed"
        )

        return jsonify({
            "status": "error",
            "message": "An error occurred during VCF analysis."
        }), 500


# =====================================================
# 15. CIViC CLINICAL EVIDENCE LOOKUP
# =====================================================

@app.route("/civic-lookup", methods=["POST"])
@login_required
def civic_lookup():

    try:

        data = request.get_json(silent=True) or {}

        file_path, error_response = get_uploaded_vcf(
            data.get("filename")
        )

        if error_response:
            return error_response

        # Parse annotated variants.
        variants = parse_annotated_vcf(file_path)

        if not variants:

            return jsonify({

                "status": "success",

                "message": (
                    "No usable annotated variants were found."
                ),

                "filename": file_path.name,
                "total_parsed_variants": 0,
                "variants_with_protein_change": 0,
                "results": []

            }), 200

        # Group variants by gene and protein change.
        search_names = {}

        for variant in variants:

            gene = variant.get("gene")
            protein = variant.get("protein_change")

            if not gene or not protein:
                continue

            profile_name = f"{gene} {protein}"

            search_names.setdefault(
                profile_name,
                []
            ).append(variant)

        if not search_names:

            return jsonify({

                "status": "success",

                "message": (
                    "Annotated variants were found, but none had "
                    "both a gene and protein change."
                ),

                "filename": file_path.name,
                "total_parsed_variants": len(variants),
                "variants_with_protein_change": 0,
                "results": []

            }), 200

        if len(search_names) > MAX_CIVIC_LOOKUPS:

            return jsonify({

                "status": "error",

                "message": (
                    f"This VCF contains {len(search_names)} unique "
                    f"protein changes. The current limit is "
                    f"{MAX_CIVIC_LOOKUPS} CIViC searches per request."
                )

            }), 413

        civic_results = []

        for profile_name, matching_variants in search_names.items():

            try:

                result = search_civic(profile_name)

                if not isinstance(result, dict):

                    result = {

                        "status": "error",
                        "query": profile_name,

                        "message": (
                            "Unexpected response from CIViC API."
                        ),

                        "results": []

                    }

            except Exception:

                app.logger.exception(
                    "CIViC query failed for %s",
                    profile_name
                )

                result = {

                    "status": "error",
                    "query": profile_name,

                    "message": (
                        "Unable to retrieve CIViC results "
                        "for this variant."
                    ),

                    "results": []

                }

            for variant in matching_variants:

                civic_results.append({

                    "input_variant": variant,
                    "civic_lookup": result

                })

            time.sleep(0.4)

        annotation_source = variants[0].get(
            "annotation_source",
            "Unknown"
        )

        return jsonify({

            "status": "success",
            "message": "CIViC lookup completed.",
            "filename": file_path.name,
            "annotation_source": annotation_source,
            "total_parsed_variants": len(variants),
            "variants_with_protein_change": len(search_names),
            "results": civic_results

        }), 200

    except ValueError as error:

        return jsonify({

            "status": "error",
            "message": str(error)

        }), 400

    except OSError:

        app.logger.exception(
            "Unable to read VCF during CIViC lookup"
        )

        return jsonify({

            "status": "error",
            "message": "Unable to read the uploaded VCF file."

        }), 500

    except Exception:

        app.logger.exception(
            "CIViC lookup failed"
        )

        return jsonify({

            "status": "error",
            "message": "An unexpected error occurred during CIViC lookup."

        }), 500


# =====================================================
# 16. RUN APPLICATION
# =====================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
