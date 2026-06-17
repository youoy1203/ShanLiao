import json
import os

path = "data/news_with_summary.jsonl"
if not os.path.exists(path):
    print("File not found")
    exit()

with open(path, "rb") as f:
    raw_bytes = f.readline()
    print("Raw Bytes of first line:")
    print(raw_bytes[:200])
    
    # 嘗試用 utf-8 解碼並印出
    try:
        decoded_utf8 = raw_bytes.decode("utf-8")
        print("\nDecoded with UTF-8:")
        # 為了避免 console 亂碼影響，我們寫到一個 temp text 檔案中，或者印出每個字元的 unicode code point
        print(decoded_utf8[:150])
    except Exception as e:
        print("UTF-8 decode failed:", e)

    # 嘗試用 cp950 (Big5) 解碼
    try:
        decoded_cp950 = raw_bytes.decode("cp950")
        print("\nDecoded with CP950:")
        print(decoded_cp950[:150])
    except Exception as e:
        print("CP950 decode failed:", e)
