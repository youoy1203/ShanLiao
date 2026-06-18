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
                    # 確保必要欄位存在，包含原始標題 (headline)、摘要 (summary) 和風格標題 (shanliao_title)
                    if "headline" in data and "summary" in data and "shanliao_title" in data:
                        headline = data["headline"].strip()
                        summary = data["summary"].strip()
                        title = data["shanliao_title"].strip()
                        
                        # 進行基礎品質過濾
                        if len(summary) > 20 and len(title) >= 10:
                            valid_data.append({
                                "headline": headline,
                                "summary": summary,
                                "shanliao_title": title
                            })
                except Exception as e:
                    print(f"解析 JSON 失敗: {e}")
    return valid_data

def convert_to_sharegpt(headline, summary, title):
    """將單筆資料轉換為 ShareGPT 格式 (將指令放在 system，數據放在 user)"""
    return {
        "conversations": [
            {
                "role": "system",
                "content": "你是一位擅長寫療癒系散文的作家（筆名黃山料）。請閱讀使用者提供的原始標題與新聞摘要，將其轉化為一句 25 ~ 40 字、去實體化且符合情感投射的黃山料風格標題。"
            },
            {
                "role": "user",
                "content": f"【原始標題】：{headline}\n【新聞摘要】：{summary}"
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
        sharegpt_item = convert_to_sharegpt(item["headline"], item["summary"], item["shanliao_title"])
        sharegpt_dataset.append(sharegpt_item)
        
    # 隨機打亂資料
    random.seed(42)
    random.shuffle(sharegpt_dataset)
    
    # 100% 資料全部作為訓練集
    train_set = sharegpt_dataset
    
    print(f"資料打包完成：")
    print(f"- 訓練集 (train.json): {len(train_set)} 筆")
    
    # 寫入檔案
    with open(TRAIN_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(train_set, f, ensure_ascii=False, indent=2)
        
    print(f"成功儲存訓練集至 {DATA_DIR} 目錄！")

if __name__ == "__main__":
    main()
