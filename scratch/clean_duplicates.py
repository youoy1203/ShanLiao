import json
import os

def clean_file(file_path):
    if not os.path.exists(file_path):
        print(f"檔案不存在: {file_path}")
        return
        
    seen = set()
    unique_lines = []
    duplicate_count = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    # 確保 ID 是 int 形式
                    article_id = int(data.get("id"))
                    if article_id not in seen:
                        seen.add(article_id)
                        unique_lines.append(line)
                    else:
                        duplicate_count += 1
                except Exception as e:
                    # 沒 ID 的行直接跳過
                    pass
                    
    # 寫回原檔案
    with open(file_path, "w", encoding="utf-8") as f:
        for line in unique_lines:
            f.write(line + "\n" if not line.endswith("\n") else line)
            
    print(f"清洗檔案: {file_path}")
    print(f" - 原始行數: {len(unique_lines) + duplicate_count}")
    print(f" - 清洗後行數 (Unique): {len(unique_lines)}")
    print(f" - 剔除重複數: {duplicate_count}")

def main():
    data_dir = "c:/MCAS/ShanLiao/data"
    clean_file(os.path.join(data_dir, "raw_news.jsonl"))
    clean_file(os.path.join(data_dir, "news_with_summary.jsonl"))
    clean_file(os.path.join(data_dir, "transformed_news.jsonl"))

if __name__ == "__main__":
    main()
