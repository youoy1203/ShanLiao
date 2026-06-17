import os
import json
import random

PROJECT_DIR = "c:\\MCAS\\ShanLiao"
DATA_DIR = os.path.join(PROJECT_DIR, "data")
TRANSFORMED_NEWS_PATH = os.path.join(DATA_DIR, "transformed_news.jsonl")
TRAIN_DATA_PATH = os.path.join(DATA_DIR, "train.json")
EVAL_DATA_PATH = os.path.join(DATA_DIR, "eval.json")

def load_transformed_news():
    """載入並過濾已轉換的新聞資料"""
    if not os.path.exists(TRANSFORMED_NEWS_PATH):
        print(f"錯誤: 找不到已轉換新聞資料檔案 {TRANSFORMED_NEWS_PATH}")
        return []
        
    valid_data = []
    with open(TRANSFORMED_NEWS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    # 確保必要欄位存在
                    if "summary" in data and "shanliao_title" in data:
                        summary = data["summary"].strip()
                        title = data["shanliao_title"].strip()
                        
                        # 進行基礎品質過濾
                        if len(summary) > 20 and len(title) >= 10:
                            valid_data.append({
                                "summary": summary,
                                "shanliao_title": title
                            })
                except Exception as e:
                    print(f"解析 JSON 失敗: {e}")
    return valid_data

def convert_to_sharegpt(summary, title):
    """將單筆資料轉換為 ShareGPT 格式"""
    return {
        "conversations": [
            {
                "role": "system",
                "content": "你是一位擅長將新聞摘要轉化為療癒系短標題的文青作家。"
            },
            {
                "role": "user",
                "content": f"請將以下新聞摘要轉化為一句25字以內的山料風格標題：\n\n{summary}"
            },
            {
                "role": "assistant",
                "content": title
            }
        ]
    }

def main():
    raw_data = load_transformed_news()
    total_count = len(raw_data)
    print(f"共載入 {total_count} 筆有效轉換資料。")
    
    if total_count == 0:
        print("沒有有效資料可供打包。")
        return
        
    # 打包為 ShareGPT 格式
    sharegpt_dataset = []
    for item in raw_data:
        sharegpt_item = convert_to_sharegpt(item["summary"], item["shanliao_title"])
        sharegpt_dataset.append(sharegpt_item)
        
    # 隨機打亂資料
    random.seed(42)
    random.shuffle(sharegpt_dataset)
    
    # 分割資料集 (90% train, 10% eval)
    split_index = int(total_count * 0.9)
    train_set = sharegpt_dataset[:split_index]
    eval_set = sharegpt_dataset[split_index:]
    
    print(f"資料集分割完成：")
    print(f"- 訓練集 (train.json): {len(train_set)} 筆")
    print(f"- 驗證集 (eval.json): {len(eval_set)} 筆")
    
    # 寫入檔案
    with open(TRAIN_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(train_set, f, ensure_ascii=False, indent=2)
        
    with open(EVAL_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(eval_set, f, ensure_ascii=False, indent=2)
        
    print(f"成功儲存資料集至 {DATA_DIR} 目錄！")

if __name__ == "__main__":
    main()
