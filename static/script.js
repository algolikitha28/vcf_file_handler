
// =====================================================
// 1. DOM ELEMENTS AND CONFIGURATION
// =====================================================

const fileInput = document.getElementById("vcfFile");
const uploadBtn = document.getElementById("uploadBtn");
const fileInfo = document.getElementById("fileInfo");
const message = document.getElementById("message");
const dropArea = document.getElementById("dropArea");

const MAX_FILE_SIZE = 100 * 1024 * 1024;

// Read CSRF token from index.html
const csrfMeta = document.querySelector(
    'meta[name="csrf-token"]'
);

const csrfToken = csrfMeta ? csrfMeta.content : null;

if (!csrfToken) {
    console.error("CSRF token not found. Check index.html.");
}

// Chart instances
let qualityChart = null;
let geneChart = null;

// Store server-generated filename after upload
let uploadedFilename = null;


// =====================================================
// 2. DISPLAY SELECTED FILE
// =====================================================

fileInput.addEventListener("change", () => {

    const file = fileInput.files[0];

    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".vcf")) {

        showMessage("Only VCF files are allowed.", "error");

        fileInput.value = "";
        fileInfo.textContent = "";

        return;
    }

    if (file.size === 0) {

        showMessage("The selected file is empty.", "error");

        fileInput.value = "";
        fileInfo.textContent = "";

        return;
    }

    if (file.size > MAX_FILE_SIZE) {

        showMessage(
            "File size must not exceed 100 MB.",
            "error"
        );

        fileInput.value = "";
        fileInfo.textContent = "";

        return;
    }

    // New file must be uploaded before CIViC lookup
    uploadedFilename = null;

    fileInfo.textContent =
        `Selected: ${file.name} (${(file.size / 1024 / 1024).toFixed(3)} MB)`;

    showMessage("", "");

});


// =====================================================
// 3. DRAG AND DROP SUPPORT
// =====================================================

dropArea.addEventListener("dragover", (event) => {

    event.preventDefault();

    dropArea.classList.add("dragging");

});

dropArea.addEventListener("dragleave", () => {

    dropArea.classList.remove("dragging");

});

dropArea.addEventListener("drop", (event) => {

    event.preventDefault();

    dropArea.classList.remove("dragging");

    const file = event.dataTransfer.files[0];

    if (!file) return;

    const transfer = new DataTransfer();

    transfer.items.add(file);

    fileInput.files = transfer.files;

    fileInput.dispatchEvent(new Event("change"));

});


// =====================================================
// 4. UPLOAD VCF FILE
// =====================================================

uploadBtn.addEventListener("click", async () => {

    const file = fileInput.files[0];

    if (!file) {

        showMessage("Please select a VCF file.", "error");

        return;
    }

    if (!file.name.toLowerCase().endsWith(".vcf") ||
        file.size === 0 ||
        file.size > MAX_FILE_SIZE) {

        showMessage(
            "Please select a valid VCF file up to 100 MB.",
            "error"
        );

        return;
    }

    if (!csrfToken) {

        showMessage(
            "Security token is missing. Please refresh the page.",
            "error"
        );

        return;
    }

    uploadBtn.disabled = true;
    uploadBtn.textContent = "Uploading and analyzing...";

    // Do not use an older upload if this upload fails
    uploadedFilename = null;

    showMessage("Uploading VCF file...", "success");

    try {

        const formData = new FormData();

        formData.append("file", file);


        // ----------------------------------
        // Upload API request
        // ----------------------------------

        const uploadResponse = await fetch("/upload-vcf", {

            method: "POST",

            headers: {
                "X-CSRFToken": csrfToken
            },

            body: formData

        });

        const uploadData = await uploadResponse.json();

        if (!uploadResponse.ok) {

            throw new Error(
                uploadData.message || "VCF upload failed."
            );

        }

        const filename =
            uploadData.filename ||
            uploadData.saved_filename ||
            uploadData.stored_filename;

        if (!filename) {

            throw new Error(
                "Upload succeeded, but the API did not return the saved filename."
            );

        }

        // Store server-generated filename
        uploadedFilename = filename;

        showMessage(
            "Upload successful! Performing VCF analysis...",
            "success"
        );


        // ----------------------------------
        // Analyze uploaded VCF
        // ----------------------------------

        const analysisResponse = await fetch("/analyze-vcf", {

            method: "POST",

            headers: {

                "Content-Type": "application/json",

                "X-CSRFToken": csrfToken

            },

            body: JSON.stringify({

                filename: filename

            })

        });

        const analysisData = await analysisResponse.json();

        if (!analysisResponse.ok) {

            throw new Error(
                analysisData.message || "VCF analysis failed."
            );

        }

        // Display analysis results
        displayResults(analysisData);


        // ----------------------------------
        // Clear old CIViC results
        // ----------------------------------

        const civicResultsElement =
            document.getElementById("civicResults");

        const civicMessageElement =
            document.getElementById("civicMessage");

        const civicContainer =
            document.getElementById("civicEvidenceContainer");

        if (civicResultsElement) {

            civicResultsElement.classList.add("hidden");

        }

        if (civicMessageElement) {

            civicMessageElement.textContent = "";

        }

        if (civicContainer) {

            civicContainer.replaceChildren();

        }

        showMessage(
            "VCF uploaded and analyzed successfully!",
            "success"
        );

    }

    catch (error) {

        uploadedFilename = null;

        showMessage(error.message, "error");

    }

    finally {

        uploadBtn.disabled = false;

        uploadBtn.textContent = "Upload and Analyze";

    }

});


// =====================================================
// 5. DISPLAY VCF ANALYSIS RESULTS
// =====================================================

function displayResults(response) {

    const data = response.analysis;

    if (!data) {

        throw new Error("Analysis response is missing.");

    }

    const qc = data.quality_assessment;
    const genes = data.gene_analysis;

    document.getElementById("results").classList.remove("hidden");

    document.getElementById("uploadedFilename").textContent =
        "File: " + response.filename;


    // ----------------------------------
    // Summary cards
    // ----------------------------------

    document.getElementById("totalVariants").textContent =
        data.total_variants;

    document.getElementById("uniqueGenes").textContent =
        genes.unique_genes;

    document.getElementById("passCount").textContent =
        qc.PASS;

    document.getElementById("passPercentage").textContent =
        qc.PASS_percentage + "%";


    // ----------------------------------
    // Quality assessment
    // ----------------------------------

    document.getElementById("passValue").textContent =
        qc.PASS;

    document.getElementById("filteredValue").textContent =
        qc.FILTERED;

    document.getElementById("unfilteredValue").textContent =
        qc.UNFILTERED;


    // ----------------------------------
    // QUAL statistics
    // ----------------------------------

    document.getElementById("meanQual").textContent =
        qc.QUAL_statistics.mean_qual ?? "N/A";

    document.getElementById("minQual").textContent =
        qc.QUAL_statistics.minimum_qual ?? "N/A";

    document.getElementById("maxQual").textContent =
        qc.QUAL_statistics.maximum_qual ?? "N/A";

    document.getElementById("availableQual").textContent =
        "Available QUAL scores: " +
        qc.QUAL_statistics.available_quality_scores;


    // ----------------------------------
    // Gene table
    // ----------------------------------

    const geneTable = document.getElementById("geneTable");

    geneTable.replaceChildren();

    const geneNames = Object.keys(genes.gene_distribution);

    geneNames.forEach(gene => {

        const row = document.createElement("tr");

        const geneCell = document.createElement("td");

        geneCell.textContent = gene;

        const countCell = document.createElement("td");

        countCell.textContent = genes.gene_distribution[gene];

        row.appendChild(geneCell);

        row.appendChild(countCell);

        geneTable.appendChild(row);

    });


    // ----------------------------------
    // Draw charts
    // ----------------------------------

    createQualityChart(qc);

    createGeneChart(genes.gene_distribution);

    document.getElementById("results").scrollIntoView({

        behavior: "smooth"

    });

}


// =====================================================
// 6. QUALITY CHART
// =====================================================

function createQualityChart(qc) {

    if (qualityChart) {

        qualityChart.destroy();

    }

    const ctx = document.getElementById("qualityChart");

    qualityChart = new Chart(ctx, {

        type: "doughnut",

        data: {

            labels: [
                "PASS",
                "FILTERED",
                "UNFILTERED"
            ],

            datasets: [{

                data: [
                    qc.PASS,
                    qc.FILTERED,
                    qc.UNFILTERED
                ],

                backgroundColor: [
                    "#16a34a",
                    "#f59e0b",
                    "#94a3b8"
                ],

                borderWidth: 1

            }]

        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            plugins: {

                legend: {

                    position: "bottom"

                }

            }

        }

    });

}


// =====================================================
// 7. GENE DISTRIBUTION CHART
// =====================================================

function createGeneChart(distribution) {

    if (geneChart) {

        geneChart.destroy();

    }

    const genes = Object.keys(distribution);

    const counts = Object.values(distribution);

    geneChart = new Chart(

        document.getElementById("geneChart"),

        {

            type: "bar",

            data: {

                labels: genes,

                datasets: [{

                    label: "Number of variants",

                    data: counts,

                    backgroundColor: "#2563eb",

                    borderRadius: 5

                }]

            },

            options: {

                responsive: true,

                maintainAspectRatio: false,

                scales: {

                    y: {

                        beginAtZero: true,

                        ticks: {

                            precision: 0

                        }

                    }

                }

            }

        }

    );

}


// =====================================================
// 8. CIViC BUTTON FUNCTIONALITY
// =====================================================

const civicBtn = document.getElementById("civicBtn");

const civicMessage = document.getElementById("civicMessage");

const civicResults = document.getElementById("civicResults");

const civicSummary = document.getElementById("civicSummary");

const civicEvidenceContainer =
    document.getElementById("civicEvidenceContainer");


if (civicBtn) {

    civicBtn.addEventListener("click", async () => {

        if (!uploadedFilename) {

            civicMessage.textContent =
                "Please upload and analyze a VCF file first.";

            civicMessage.className = "message error";

            return;

        }

        if (!csrfToken) {

            civicMessage.textContent =
                "Security token is missing. Please refresh the page.";

            civicMessage.className = "message error";

            return;

        }

        civicBtn.disabled = true;

        civicBtn.textContent = "Searching CIViC...";

        civicMessage.textContent =
            "Searching CIViC for annotated variants...";

        civicMessage.className = "message success";

        civicResults.classList.add("hidden");

        civicEvidenceContainer.replaceChildren();


        try {

            // ----------------------------------
            // CIViC API request
            // ----------------------------------

            const response = await fetch("/civic-lookup", {

                method: "POST",

                headers: {

                    "Content-Type": "application/json",

                    "X-CSRFToken": csrfToken

                },

                body: JSON.stringify({

                    filename: uploadedFilename

                })

            });

            const data = await response.json();

            if (!response.ok || data.status !== "success") {

                throw new Error(
                    data.message || "CIViC lookup failed."
                );

            }

            // Display CIViC results
            displayCivicResults(data);

            civicMessage.textContent =
                "CIViC lookup completed successfully.";

            civicMessage.className = "message success";

        }

        catch (error) {

            civicMessage.textContent = error.message;

            civicMessage.className = "message error";

        }

        finally {

            civicBtn.disabled = false;

            civicBtn.textContent = "Search CIViC Evidence";

        }

    });

}


// =====================================================
// 9. DISPLAY CIViC RESULTS
// =====================================================

function displayCivicResults(data) {

    civicEvidenceContainer.replaceChildren();

    civicResults.classList.remove("hidden");

    const results = data.results || [];

    civicSummary.textContent =
        `${data.total_parsed_variants || 0} parsed variants | ` +
        `${data.variants_with_protein_change || 0} unique protein-change searches`;


    if (results.length === 0) {

        const emptyMessage = document.createElement("p");

        emptyMessage.textContent =
            data.message || "No annotated variants were available.";

        civicEvidenceContainer.appendChild(emptyMessage);

        return;

    }

    let evidenceCount = 0;

    let profileCount = 0;


    results.forEach(item => {

        const variant = item.input_variant || {};

        const lookup = item.civic_lookup || {};

        const variantCard = document.createElement("div");

        variantCard.className = "civic-variant-card";


        // ----------------------------------
        // Input variant heading
        // ----------------------------------

        const variantHeading = document.createElement("h4");

        variantHeading.textContent =
            `Input variant: ${variant.gene || "Unknown gene"} ` +
            `${variant.protein_change || ""}`;

        variantCard.appendChild(variantHeading);


        // ----------------------------------
        // Handle lookup errors
        // ----------------------------------

        if (lookup.status !== "success") {

            const errorText = document.createElement("p");

            errorText.textContent =
                lookup.message || "CIViC lookup failed for this variant.";

            variantCard.appendChild(errorText);

            civicEvidenceContainer.appendChild(variantCard);

            return;

        }


        const profiles = lookup.results || [];


        // ----------------------------------
        // No candidate profiles
        // ----------------------------------

        if (profiles.length === 0) {

            const noMatch = document.createElement("p");

            noMatch.textContent =
                "No candidate CIViC molecular profiles were found.";

            variantCard.appendChild(noMatch);

            civicEvidenceContainer.appendChild(variantCard);

            return;

        }


        // ----------------------------------
        // Display molecular profiles
        // ----------------------------------

        profiles.forEach(profile => {

            profileCount++;

            const profileCard = document.createElement("div");

            profileCard.className = "civic-profile-card";

            const profileHeading = document.createElement("h5");

            profileHeading.textContent =
                profile.name || "Unnamed molecular profile";

            profileCard.appendChild(profileHeading);


            // ----------------------------------
            // CIViC profile link
            // ----------------------------------

            if (profile.link) {

                try {

                    const profileURL = new URL(
                        profile.link,
                        "https://civicdb.org"
                    );

                    if (profileURL.origin === "https://civicdb.org") {

                        const link = document.createElement("a");

                        link.href = profileURL.href;

                        link.textContent =
                            "View molecular profile on CIViC";

                        link.target = "_blank";

                        link.rel = "noopener noreferrer";

                        profileCard.appendChild(link);

                    }

                }

                catch (error) {

                    console.warn("Invalid CIViC profile link.");

                }

            }


            // ----------------------------------
            // Evidence items
            // ----------------------------------

            const evidenceItems =
                profile.evidenceItems?.nodes || [];


            if (evidenceItems.length === 0) {

                const noEvidence = document.createElement("p");

                noEvidence.textContent =
                    "No accepted evidence items are available for this profile.";

                profileCard.appendChild(noEvidence);

            }


            evidenceItems.forEach(evidence => {

                evidenceCount++;

                const evidenceCard =
                    document.createElement("div");

                evidenceCard.className = "civic-evidence-item";


                // Evidence heading
                const evidenceHeading =
                    document.createElement("h6");

                evidenceHeading.textContent =
                    `${evidence.evidenceType || "Evidence"} | ` +
                    `Level: ${evidence.evidenceLevel || "N/A"}`;

                evidenceCard.appendChild(evidenceHeading);


                // Evidence details
                const details = [

                    ["Status", evidence.status],

                    ["Evidence rating", evidence.evidenceRating],

                    ["Direction", evidence.evidenceDirection],

                    [
                        "Disease",
                        evidence.disease?.displayName ||
                        evidence.disease?.name
                    ]

                ];


                details.forEach(([label, value]) => {

                    if (!value) return;

                    const paragraph = document.createElement("p");

                    paragraph.textContent = `${label}: ${value}`;

                    evidenceCard.appendChild(paragraph);

                });


                // ----------------------------------
                // Therapies
                // ----------------------------------

                const therapies = evidence.therapies || [];

                const therapyParagraph =
                    document.createElement("p");

                therapyParagraph.textContent =
                    "Therapies: " +

                    (

                        therapies.length

                            ? therapies.map(t => t.name)
                                .filter(Boolean)
                                .join(", ")

                            : "Not specified"

                    );

                evidenceCard.appendChild(therapyParagraph);


                // ----------------------------------
                // Evidence description
                // ----------------------------------

                const description = document.createElement("p");

                description.textContent =
                    "Description: " +
                    (
                        evidence.description ||
                        "No description available."
                    );

                evidenceCard.appendChild(description);

                profileCard.appendChild(evidenceCard);

            });

            variantCard.appendChild(profileCard);

        });

        civicEvidenceContainer.appendChild(variantCard);

    });


    // =================================================
    // SCIENTIFIC INTERPRETATION DISCLAIMER
    // =================================================

    const disclaimer = document.createElement("p");

    disclaimer.className = "civic-disclaimer";

    disclaimer.textContent =
        "Important: These are candidate molecular-profile matches " +
        "returned by a name search. Check the exact molecular alteration, " +
        "cancer type, evidence direction and evidence level before " +
        "interpreting a result. CIViC evidence is research information, " +
        "not an individual treatment recommendation.";

    civicEvidenceContainer.appendChild(disclaimer);


    // Update summary
    civicSummary.textContent +=
        ` | ${profileCount} candidate profiles | ${evidenceCount} evidence items`;

}


// =====================================================
// 10. DISPLAY MESSAGES
// =====================================================

function showMessage(text, type) {

    message.textContent = text;

    message.className = "message " + type;

}
