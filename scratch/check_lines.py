import json
import os

data_dir = "data"
for name in ["raw_news.jsonl", "news_with_summary.jsonl", "transformed_news.jsonl"]:
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        print(f"{name} does not exist")
        continue
    
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        
    ids = []
    errors = 0
    missing_id = 0
    for i, l in enumerate(lines):
        try:
            d = json.loads(l)
            if "id" in d:
                ids.append(d["id"])
            else:
                missing_id += 1
        except Exception as e:
            errors += 1
            
    print(f"{name}:")
    print(f"  Total lines: {len(lines)}")
    print(f"  Successfully parsed JSON: {len(lines) - errors}")
    print(f"  Missing 'id' key: {missing_id}")
    print(f"  Unique IDs: {len(set(ids))}")
    print(f"  ID range: {min(ids) if ids else 'N/A'} to {max(ids) if ids else 'N/A'}")
    if len(ids) != len(set(ids)):
        print(f"  WARNING: Contains duplicates! Duplicated count: {len(ids) - len(set(ids))}")
