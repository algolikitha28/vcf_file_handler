
import re


AA_THREE_TO_ONE = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D",
    "Cys": "C", "Gln": "Q", "Glu": "E", "Gly": "G",
    "His": "H", "Ile": "I", "Leu": "L", "Lys": "K",
    "Met": "M", "Phe": "F", "Pro": "P", "Ser": "S",
    "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
    "Ter": "*"
}


def protein_to_short(protein):
    """Convert p.Val600Glu or ENSP:p.Val600Glu to V600E."""

    if not protein:
        return None

    protein = protein.strip()

    if ":p." in protein:
        protein = "p." + protein.rsplit(":p.", 1)[1]

    protein = protein.removeprefix("p.")

    pattern = r"^([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})$"
    match = re.match(pattern, protein)

    if match:
        ref, position, alt = match.groups()

        ref_one = AA_THREE_TO_ONE.get(ref)
        alt_one = AA_THREE_TO_ONE.get(alt)

        if ref_one and alt_one:
            return f"{ref_one}{position}{alt_one}"

    return protein


def get_annotation_format(vcf_path):
    """Detect VEP CSQ or SnpEff ANN."""

    with open(vcf_path, "r", encoding="utf-8", errors="replace") as file:
        for line in file:

            if line.startswith("##INFO=<ID=CSQ"):
                return "VEP"

            if line.startswith("##INFO=<ID=ANN"):
                return "SNPEFF"

            if line.startswith("#CHROM"):
                break

    return None


def get_annotation_fields(vcf_path, annotation_type):
    """Extract annotation field order from the VCF header."""

    annotation_id = (
        "##INFO=<ID=CSQ"
        if annotation_type == "VEP"
        else "##INFO=<ID=ANN"
    )

    with open(vcf_path, "r", encoding="utf-8", errors="replace") as file:

        for line in file:

            if line.startswith(annotation_id):

                match = re.search(r"Format:\s*(.*?)\"", line)

                if not match:
                    raise ValueError(
                        "Could not find annotation Format in VCF header."
                    )

                return match.group(1).strip().split("|")

            if line.startswith("#CHROM"):
                break

    raise ValueError("Annotation field definition not found.")


def parse_annotated_vcf(vcf_path):
    """
    Extract variant annotations from VEP CSQ or SnpEff ANN.

    Returns a list of dictionaries.
    """

    annotation_type = get_annotation_format(vcf_path)

    if annotation_type is None:
        raise ValueError(
            "No VEP CSQ or SnpEff ANN annotation was found."
        )

    fields = get_annotation_fields(vcf_path, annotation_type)

    variants = []

    annotation_key = (
        "CSQ" if annotation_type == "VEP" else "ANN"
    )

    with open(vcf_path, "r", encoding="utf-8", errors="replace") as file:

        for line in file:

            if line.startswith("#") or not line.strip():
                continue

            columns = line.rstrip("\r\n").split("\t")

            if len(columns) < 8:
                continue

            chrom, pos, variant_id, ref, alt = columns[:5]
            info = columns[7]

            info_values = {}

            for item in info.split(";"):

                if "=" in item:
                    key, value = item.split("=", 1)
                    info_values[key] = value

            annotation_data = info_values.get(annotation_key)

            if not annotation_data:
                continue

            for annotation in annotation_data.split(","):

                values = annotation.split("|")
                record = dict(zip(fields, values))

                if annotation_type == "VEP":

                    gene = record.get("SYMBOL")
                    consequence = record.get("Consequence")
                    protein = record.get("HGVSp")
                    transcript = record.get("Feature")

                else:

                    gene = record.get("Gene_Name")
                    consequence = record.get("Annotation")
                    protein = record.get("HGVS.p")
                    transcript = record.get("Feature_ID")

                variants.append({

                    "chromosome": chrom,
                    "position": pos,
                    "vcf_id": variant_id,
                    "ref": ref,
                    "alt": alt,
                    "gene": gene or None,
                    "consequence": consequence or None,
                    "protein_change": protein_to_short(protein),
                    "transcript": transcript or None,
                    "annotation_source": annotation_type

                })

    return variants
