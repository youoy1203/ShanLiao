import json
import os
import re
import shutil

data_dir = "data"
summary_path = os.path.join(data_dir, "news_with_summary.jsonl")
temp_path = os.path.join(data_dir, "news_with_summary_cleaned.jsonl")
backup_path = os.path.join(data_dir, "news_with_summary.jsonl.bak")
transformed_path = os.path.join(data_dir, "transformed_news.jsonl")

if not os.path.exists(summary_path):
    print("找不到 news_with_summary.jsonl，無法清理！")
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
        r'^新聞摘要\s*[（(]\s*約?\d+字\s*[）)][:：\s]*',
        r'^新聞摘要[:：\s]*',
        r'^摘要如下[:：\s]*',
        r'^摘要[:：\s]*',
        r'^核心事件[:：\s]*',
        r'^內容摘要[:：\s]*',
        r'^本文摘要[:：\s]*',
        r'^[（(]\s*約?\d+字\s*[）)][:：\s]*',  # 匹配開頭的 (150字) 或 （150字）
    ]
    
    for prefix in prefixes:
        cleaned = re.sub(prefix, '', cleaned, flags=re.IGNORECASE).strip()
        
    # 3. 移除結尾的 (150字) 或是 （199字） 等字數統計
    cleaned = re.sub(r'[（(]\s*約?\d+字\s*[）)]\s*$', '', cleaned).strip()
    
    # 4. 合併換行符與多餘空白，讓摘要維持在單一行
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # 5. 去除可能殘留在開頭的標點符號 (如冒號、頓號、逗號、空格)
    cleaned = re.sub(r'^[：:，,、。；;\s]+', '', cleaned).strip()
    
    return cleaned

print("開始進行摘要清理工作...")

total_lines = 0
cleaned_count = 0

with open(summary_path, "r", encoding="utf-8") as f_in, \
     open(temp_path, "w", encoding="utf-8") as f_out:
         
    for line in f_in:
        if not line.strip():
            continue
        total_lines += 1
        try:
            data = json.loads(line)
            orig_summary = data.get("summary", "")
            cleaned = clean_summary(orig_summary)
            
            if orig_summary != cleaned:
                cleaned_count += 1
                
            data["summary"] = cleaned
            f_out.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"解析/清理行時出錯: {e}")

print(f"清理完成！")
print(f" - 總處理筆數: {total_lines}")
print(f" - 有修改之筆數: {cleaned_count}")

# 備份原檔案
print(f"正在備份原檔案至 {backup_path}...")
shutil.copyfile(summary_path, backup_path)

# 用新檔案覆寫原檔案
print(f"正在將清理後的檔案覆寫回 {summary_path}...")
if os.path.exists(summary_path):
    os.remove(summary_path)
os.rename(temp_path, summary_path)

# 清理或刪除 transformed_news.jsonl
if os.path.exists(transformed_path):
    print(f"發現舊的風格轉換標題檔案 {transformed_path}。正在將其刪除，以便後續全部重新執行...")
    os.remove(transformed_path)
    print("舊風格轉換標題已刪除。")
else:
    print("沒有發現舊的風格轉換標題檔案。")

print("所有清理工作大功告成！")
