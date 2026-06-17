import json
import os
import re

path = "data/news_with_summary.jsonl"
out_path = "scratch/test_clean_output.txt"
if not os.path.exists(path):
    print("File not found")
    exit()

def clean_summary(text):
    if not text:
        return ""
    
    # 1. 移除 Markdown 粗體標記 **
    cleaned = text.replace("**", "")
    
    # 2. 移除各種常見的 AI 前綴與標題 (不分大小寫與中英文標點)
    prefixes = [
        r'^【新聞摘要】[:：\s]*',
        r'^【摘要】[:：\s]*',
        r'^\[新聞摘要\][:：\s]*',
        r'^\[摘要\][:：\s]*',
        r'^新聞摘要（\d+字）[:：\s]*',
        r'^新聞摘要\(\d+字\)[:：\s]*',
        r'^新聞摘要\s*\(約\d+字\)[:：\s]*',
        r'^新聞摘要[:：\s]*',
        r'^摘要如下[:：\s]*',
        r'^摘要[:：\s]*',
        r'^核心事件[:：\s]*',
        r'^內容摘要[:：\s]*',
        r'^本文摘要[:：\s]*',
    ]
    
    for prefix in prefixes:
        cleaned = re.sub(prefix, '', cleaned, flags=re.IGNORECASE).strip()
        
    # 3. 合併換行符與多餘空白，讓摘要維持在單一行
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # 4. 去除可能包在最外層的引號
    cleaned = re.sub(r'^["\'「『「]|["\'」』」]$', '', cleaned).strip()
    
    # 5. 去除可能殘留在開頭的標點符號 (如冒號、頓號、逗號)
    cleaned = re.sub(r'^[：:，,、。；;\s]+', '', cleaned).strip()
    
    return cleaned

with open(out_path, "w", encoding="utf-8") as out_f:
    out_f.write("--- 清理測試前 30 筆對比 ---\n\n")
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                orig = data.get("summary", "")
                cleaned = clean_summary(orig)
                
                out_f.write(f"ID {data.get('id')}:\n")
                out_f.write(f"  [ORIG] : {orig}\n")
                out_f.write(f"  [CLEAN]: {cleaned}\n")
                out_f.write("-" * 40 + "\n")
                
                count += 1
                if count >= 30:
                    break
            except Exception as e:
                out_f.write(f"Error parsing line: {e}\n")

print(f"測試對比已寫入至 {out_path}")
