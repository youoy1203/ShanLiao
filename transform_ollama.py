import os
import json
import time
import requests

PROJECT_DIR = "c:\\MCAS\\ShanLiao"
DATA_DIR = os.path.join(PROJECT_DIR, "data")
SUMMARY_NEWS_PATH = os.path.join(DATA_DIR, "news_with_summary.jsonl")
TRANSFORMED_NEWS_PATH = os.path.join(DATA_DIR, "transformed_news.jsonl")
RULEBOOK_PATH = os.path.join(PROJECT_DIR, "style_rulebook.md")

OLLAMA_URL = "http://localhost:11434/api/chat"

# 我們優先使用 qwen3.5:9b (如果本地有)，否則用 qwen3:1.7b
MODEL_NAME = "qwen3.5:9b"  # 使用者有的模型之一

def check_ollama_model():
    """檢查 Ollama 是否可用，以及模型是否存在"""
    try:
        res = requests.get("http://localhost:11434/api/tags", timeout=5)
        if res.status_code == 200:
            models = [m["name"] for m in res.json().get("models", [])]
            print(f"本地 Ollama 已載入之模型: {models}")
            if MODEL_NAME in models:
                return MODEL_NAME
            elif "qwen3:1.7b" in models:
                print(f"找不到 {MODEL_NAME}，將使用備用模型 qwen3:1.7b")
                return "qwen3:1.7b"
            elif models:
                print(f"找不到指定模型，將使用第一個可用模型: {models[0]}")
                return models[0].split(":")[0]
    except Exception as e:
        print(f"無法連線至本地 Ollama 服務: {e}。請確保 Ollama 已啟動。")
    return None

def read_rulebook():
    """讀取規則書"""
    if not os.path.exists(RULEBOOK_PATH):
        print("警告: 找不到 style_rulebook.md，將使用簡化規則。")
        return "請將新聞摘要轉換為療癒系短標題，字數 25-40 字，不要出現具體人名、地名、數字。"
    with open(RULEBOOK_PATH, "r", encoding="utf-8") as f:
        return f.read()

def transform_article(model, rulebook, headline, summary):
    """利用本地 Ollama 模型進行風格標題轉換"""
    system_prompt = (
        "你是一位深諳黃山料風格的文青作家。請閱讀以下的黃山料風格新聞標題轉換規則書。\n\n"
        f"【規則書】\n{rulebook}\n\n"
        "你的任務是根據輸入的【原始新聞標題】和【新聞摘要】，輸出符合規則書的【黃山料風格標題】。\n"
        "請只輸出轉換後的那一句標題，不要有引號，不要有任何多餘的解釋或說明。"
    )
    
    user_content = (
        f"【原始新聞標題】\n{headline}\n\n"
        f"【新聞摘要】\n{summary}\n\n"
        "請直接給出轉換後的山料風格標題（25~40字）："
    )
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "options": {
            "temperature": 0.3
        },
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=60)
        if response.status_code == 200:
            res_json = response.json()
            title = res_json["message"]["content"].strip()
            # 移除可能存在的首尾引號
            title = title.strip('"').strip("'").strip("「").strip("」")
            return title
        else:
            print(f"Ollama 回傳錯誤狀態碼: {response.status_code}")
    except Exception as e:
        print(f"Ollama 請求異常: {e}")
    return None

def load_processed_ids():
    """載入已完成轉換的文章 ID"""
    if not os.path.exists(TRANSFORMED_NEWS_PATH):
        return set()
    processed = set()
    try:
        with open(TRANSFORMED_NEWS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "id" in data:
                            processed.add(int(data["id"]))
                    except:
                        pass
    except Exception as e:
        print(f"讀取已轉換資料時出錯: {e}")
    return processed

def main():
    model = check_ollama_model()
    if not model:
        print("錯誤: 本地 Ollama 服務未啟動，無法進行本地轉換。")
        return
        
    if not os.path.exists(SUMMARY_NEWS_PATH):
        print(f"錯誤: 找不到已生成摘要的檔案 {SUMMARY_NEWS_PATH}。請先運行 summarizer.py")
        return
        
    rulebook = read_rulebook()
    processed_ids = load_processed_ids()
    print(f"已完成轉換之新聞筆數: {len(processed_ids)}")
    
    # 讀取摘要資料
    news_list = []
    with open(SUMMARY_NEWS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    news_list.append(data)
                except:
                    pass
                    
    to_process = [news for news in news_list if int(news["id"]) not in processed_ids]
    print(f"待處理新聞筆數: {len(to_process)} 筆")
    
    if not to_process:
        print("所有新聞皆已完成標題轉換。")
        return
        
    print(f"開始使用本地 Ollama 模型 ({model}) 進行標題轉換...")
    t0 = time.time()
    
    with open(TRANSFORMED_NEWS_PATH, "a", encoding="utf-8") as out_file:
        for i, news in enumerate(to_process):
            article_id = news["id"]
            headline = news["headline"]
            summary = news["summary"]
            
            print(f"[{i+1}/{len(to_process)}] 正在處理文章 ID {article_id}...")
            
            try:
                transformed_title = transform_article(model, rulebook, headline, summary)
                if transformed_title:
                    output_data = dict(news)
                    output_data["shanliao_title"] = transformed_title
                    
                    out_file.write(json.dumps(output_data, ensure_ascii=False) + "\n")
                    out_file.flush()
                    print(f"-> 成功轉換為: {transformed_title}")
                else:
                    print("-> 轉換失敗。跳過此文章...")
            except KeyboardInterrupt:
                print("\n中斷處理，已安全儲存進度...")
                break
            except Exception as e:
                print(f"-> 處理 ID {article_id} 時出錯: {e}")
                
            # 本地模型不需要長休眠，適當間隔以防卡死
            time.sleep(0.1)
            
    t1 = time.time()
    print(f"轉換結束！總耗時: {t1 - t0:.1f} 秒。")

if __name__ == "__main__":
    main()
