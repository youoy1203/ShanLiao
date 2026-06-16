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
        
    prompt = f"""請以繁體中文為以下新聞生成一段約 100 字的簡短摘要，直接輸出摘要內容，不需要任何前言：

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
    
    try:
        # 配合 mistral-large-2512 的 0.07 Requests per Second 限制 (約每 14.3 秒 1 次)，每次發送前強制延遲 15 秒
        print(f"[AI Summarizer] 遵守 Rate Limit 限制，等待 15 秒再呼叫 Mistral...")
        time.sleep(15)
        
        print(f"[AI Summarizer] 正在為新聞《{title}》發送請求至 Mistral ({MISTRAL_MODEL})...")
        response = requests.post(url, json=payload, headers=headers, timeout=60)
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
    except Exception as e:
        print(f"[AI Summarizer] 呼叫 Mistral 失敗: {e}")
        return "（無法生成 AI 摘要，請點擊連結閱讀全文）"

if __name__ == "__main__":
    test_title = "公視新聞 Mistral Large 測試"
    test_content = "公視新聞網（PNN）今天測試了 Mistral Large AI 摘要功能。這項技術使用了 Mistral 的 mistral-large-2512 模型，並順利在 WSL2 環境下透過 HTTPS 外部連線與 Mistral 官方伺服器進行通訊。開發人員表示，此自動化流程將有助於大幅減少新聞摘要發布的人力成本，且能快速將內容透過 Discord Bot 發送到目標頻道。目前測試非常順利，未來可能推廣到其他平台。"
    
    summary = generate_summary(test_title, test_content)
    print("\n--- 生成結果 ---")
    print(summary)
