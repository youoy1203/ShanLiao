import os
import re
import time
import requests
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

MISTRAL_API_KEY = os.getenv("Mistral")
MISTRAL_MODEL = "mistral-large-2512"

def generate_summary(title, content):
    """
    透過 Mistral API (使用 mistral-large-2512 模型) 讀取新聞內文與標題生成摘要
    內置 429 Too Many Requests 自動重試機制
    """
    if not MISTRAL_API_KEY:
        print("[AI Summarizer] 錯誤: 找不到 Mistral API key，請檢查 .env 檔案。")
        return "（無法生成 AI 摘要，請點擊連結閱讀全文）"
        
    url = "https://api.mistral.ai/v1/chat/completions"
    
    # 限制內文長度，以防超出模型的 context window
    max_content_len = 3000
    cleaned_content = content.strip() if content else ""
    if len(cleaned_content) > max_content_len:
        cleaned_content = cleaned_content[:max_content_len] + "\n(由於內容過長已截斷)"
        
    prompt = f"""請以繁體中文為以下新聞生成一段約 100 字的簡短摘要，直接輸出摘要內容，不需要 any 前言：

新聞標題：{title.strip()}

新聞內文：
{cleaned_content}
"""

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }
    
    max_retries = 5
    base_delay = 16  # 基礎 Rate Limit 延遲 16 秒，確保大於 14.3 秒以符合 0.07 req/sec
    
    for attempt in range(max_retries):
        try:
            # 每次發送前進行基礎延遲
            print(f"[AI Summarizer] 遵守 Rate Limit 限制，等待 {base_delay} 秒再呼叫 Mistral...")
            time.sleep(base_delay)
            
            print(f"[AI Summarizer] 正在為新聞《{title}》發送請求至 Mistral ({MISTRAL_MODEL}) (嘗試 {attempt + 1}/{max_retries})...")
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            
            # 若遇到 429，則進行重試
            if response.status_code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"[AI Summarizer] 警告: 觸發 Mistral 限速 429。將等待 {wait_time} 秒後重試...")
                time.sleep(wait_time)
                continue
                
            response.raise_for_status()
            
            result = response.json()
            summary = result["choices"][0]["message"]["content"].strip()
            
            # 移除 AI 可能會生成的常見前綴
            unwanted_prefixes = [
                "這是一篇關於", "以下是為您生成的摘要", "新聞摘要如下", "這篇新聞主要在說明", "摘要：", "摘要如下"
            ]
            for prefix in unwanted_prefixes:
                if summary.startswith(prefix):
                    summary = re.sub(rf"^{prefix}[:：\s]*", "", summary)
                    
            return summary if summary else "（無法生成 AI 摘要，請點擊連結閱讀全文）"
            
        except requests.exceptions.HTTPError as he:
            # 雙重防護捕獲 HTTPError 中的 429
            if he.response is not None and he.response.status_code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"[AI Summarizer] 警告: 捕獲 HTTP 429 限速錯誤。將等待 {wait_time} 秒後重試...")
                time.sleep(wait_time)
                continue
            else:
                print(f"[AI Summarizer] 呼叫 Mistral 失敗 (HTTP 錯誤): {he}")
                break
        except Exception as e:
            print(f"[AI Summarizer] 呼叫 Mistral 發生異常 (嘗試 {attempt + 1}/{max_retries}): {e}")
            time.sleep(5)
            
    return "（無法生成 AI 摘要，請點擊連結閱讀全文）"

if __name__ == "__main__":
    test_title = "公視新聞 Mistral 重試機制測試"
    test_content = "公視新聞網（PNN）今天測試了自動摘要與 Rate Limit 重試功能。在多次快速調用下，系統可以自動捕獲並應對 Mistral API 的 429 Too Many Requests 錯誤，並進行指數型退讓重試，以確保長時間大批量的任務執行不會因此中斷。"
    
    summary = generate_summary(test_title, test_content)
    print("\n--- 生成結果 ---")
    print(summary)
