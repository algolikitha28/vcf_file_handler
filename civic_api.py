
import requests

# CIViC GraphQL API endpoint
CIVIC_API_URL = "https://civicdb.org/api/graphql"

HEADERS = {
    "Content-Type": "application/json"
}

# GraphQL query to search molecular profiles and their evidence
CIVIC_QUERY = """
query SearchMolecularProfiles($name: String!) {
    molecularProfiles(name: $name, first: 10) {
        nodes {
            id
            name
            link
            evidenceItems(first: 50) {
                nodes {
                    id
                    status
                    evidenceType
                    evidenceLevel
                    evidenceRating
                    evidenceDirection
                    description
                    disease {
                        id
                        name
                        displayName
                    }
                    therapies {
                        id
                        name
                    }
                }
            }
        }
    }
}
"""


def search_civic(molecular_profile_name):

    # Prepare GraphQL request
    payload = {
        "query": CIVIC_QUERY,
        "variables": {
            "name": molecular_profile_name
        }
    }

    try:
        # Send request to CIViC API
        response = requests.post(
            CIVIC_API_URL,
            headers=HEADERS,
            json=payload,
            timeout=30
        )

        # Raise error for HTTP failures
        response.raise_for_status()

        # Convert response into JSON
        result = response.json()

        # Handle GraphQL errors
        if "errors" in result:
            return {
                "status": "error",
                "message": "CIViC GraphQL query returned errors.",
                "errors": result["errors"]
            }

        # Extract molecular profiles
        profiles = (
            result.get("data", {})
            .get("molecularProfiles", {})
            .get("nodes", [])
        )

        # Keep only ACCEPTED evidence records
        for profile in profiles:

            evidence_nodes = (
                profile.get("evidenceItems", {})
                .get("nodes", [])
            )

            profile["evidenceItems"]["nodes"] = [
                item for item in evidence_nodes
                if item.get("status") == "ACCEPTED"
            ]

        # Return filtered results
        return {
            "status": "success",
            "query": molecular_profile_name,
            "total_profiles": len(profiles),
            "results": profiles
        }

    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": "CIViC API request timed out."
        }

    except requests.exceptions.RequestException as error:
        return {
            "status": "error",
            "message": str(error)
        }

    except ValueError:
        return {
            "status": "error",
            "message": "Invalid JSON response from CIViC."
        }
