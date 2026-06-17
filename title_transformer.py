import os
import re
import subprocess
import requests

def get_ollama_base_url():
    """
    動態探測 Ollama 服務的 Base URL
    """
    env_url = os.environ.get("OLLAMA_BASE_URL")
    if env_url:
        return env_url

    # 嘗試本地 localhost
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=0.3)
        if response.status_code == 200:
            return "http://localhost:11434"
    except Exception:
        pass

    # 解析 WSL2 閘道 (Gateway IP)
    gateway_ip = None
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0 and result.stdout:
            match = re.search(r"via\s+([0-9\.]+)", result.stdout)
            if match:
                gateway_ip = match.group(1)
    except Exception:
        pass

    if not gateway_ip:
        try:
            if os.path.exists("/etc/resolv.conf"):
                with open("/etc/resolv.conf", "r") as f:
                    content = f.read()
                    match = re.search(r"nameserver\s+([0-9\.]+)", content)
                    if match:
                        gateway_ip = match.group(1)
        except Exception:
            pass

    if gateway_ip:
        target_url = f"http://{gateway_ip}:11434"
        try:
            response = requests.get(f"{target_url}/api/tags", timeout=0.5)
            if response.status_code == 200:
                return target_url
        except Exception:
            pass

    return "http://localhost:11434"

def get_available_qwen_model(base_url):
    """
    查詢 Ollama 上可用的 Qwen 模型，優先匹配 qwen3:1.7b 或 qwen3.5:2b 等
    """
    default_model = "qwen3:1.7b"
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=1.5)
        if response.status_code == 200:
            models_info = response.json().get("models", [])
            model_names = [m.get("name") for m in models_info]
            
            # 1. 精準匹配使用者提到的模型 (例如 qwen3:1.7b)
            if default_model in model_names:
                return default_model
                
            # 2. 匹配名稱中含有 qwen3 且帶有 1.7b / 2b / 1.5b / latest 的模型
            for name in model_names:
                if "qwen3" in name.lower() and ("1.7b" in name or "2b" in name or "1.5b" in name):
                    return name
            
            # 3. 匹配先前偵測到的 qwen3.5:2b 或是 qwen3.5:9b
            for name in model_names:
                if "qwen3.5" in name:
                    return name
                    
            # 4. 匹配任何包含 qwen3 的模型
            for name in model_names:
                if "qwen3" in name.lower():
                    return name
                    
            # 5. 匹配任何 qwen 模型
            for name in model_names:
                if "qwen" in name.lower():
                    return name
                    
            if model_names:
                return model_names[0]
    except Exception as e:
        print(f"[Title Transformer] 查詢可用模型失敗: {e}")
        
    return default_model

def transform_title(original_title):
    """
    調用本地 Ollama 模型，將新聞標題轉換為吸引人的特殊社群口吻
    """
    base_url = get_ollama_base_url()
    url = f"{base_url}/api/chat"
    
    # 獲取合適的模型名稱
    model_name = get_available_qwen_model(base_url)
    print(f"[Title Transformer] 使用 Ollama 連線: {base_url} | 模型: {model_name}")
    
    prompt = f"""你是一個專業的社群媒體小編。請將以下新聞標題轉換為一種更活潑、吸引人、且帶點吸睛社群風格的標題（例如適當搭配 Emoji，語氣生動活潑，適合作為 Discord 發布之用）。

要求：
1. 請直接輸出轉換後的標題本身。
2. 絕對不要輸出任何解釋、引導句、引號或無關字眼（不要說「這是轉換後的標題：」或加上「」引號）。
3. 必須使用繁體中文。

原始新聞標題：{original_title.strip()}
"""

    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,  # 提高創意思維
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        transformed = result.get("message", {}).get("content", "").strip()
        
        # 備用防護：針對某些思考模型
        if not transformed:
            thinking = result.get("message", {}).get("thinking", "").strip()
            if thinking:
                lines = [line.strip() for line in thinking.split('\n') if line.strip()]
                for line in reversed(lines):
                    if len(line) > 10 and not line.startswith("Let") and not line.startswith("Draft") and not line.startswith("Wait"):
                        transformed = line
                        break
        
        # 清除不必要的引號
        transformed = re.sub(r'^["\'「『]|["\'」』]$', '', transformed).strip()
        
        # 去除常見的 AI 囉嗦引導詞
        unwanted_prefixes = ["轉換後的標題", "社群風標題", "吸睛標題", "標題：", "標題"]
        for prefix in unwanted_prefixes:
            if transformed.startswith(prefix):
                transformed = re.sub(rf"^{prefix}[:：\s]*", "", transformed)
                
        return transformed if transformed else original_title
    except Exception as e:
        print(f"[Title Transformer] 轉換標題失敗: {e}")
        return original_title

if __name__ == "__main__":
    test_title = "日央行宣布升息1碼 創1995年以來基準利率新高"
    new_title = transform_title(test_title)
    print("\n--- 標題轉換測試 ---")
    print(f"原標題: {test_title}")
    print(f"新標題: {new_title}")
