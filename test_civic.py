
from civic_api import search_civic
import json

result = search_civic("BRAF V600E")

print("\n========== CIViC API RESPONSE ==========")
print(json.dumps(result, indent=4))
print("========================================")
