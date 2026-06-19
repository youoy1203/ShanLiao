import os
import re
import subprocess
import requests

def get_ollama_base_url():
    """
    獲取 Ollama 服務的 Base URL，優先使用環境變數 OLLAMA_BASE_URL，預設為 http://localhost:11434
    """
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

def get_available_qwen_model(base_url):
    """
    查詢 Ollama 上可用的 Qwen 模型，優先匹配 shanliao-qwen
    """
    default_model = "shanliao-qwen"
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=1.5)
        if response.status_code == 200:
            models_info = response.json().get("models", [])
            model_names = [m.get("name") for m in models_info]
            
            # 1. 精準匹配 shanliao-qwen
            if default_model in model_names:
                return default_model
                
            # 2. 優先匹配包含 shanliao 的任何模型
            for name in model_names:
                if "shanliao" in name.lower():
                    return name
            
            # 3. 匹配名稱中含有 qwen3 且帶有 1.7b / 2b / 1.5b 的模型
            for name in model_names:
                if "qwen3" in name.lower() and ("1.7b" in name or "2b" in name or "1.5b" in name):
                    return name
            
            # 4. 匹配先前偵測到的 qwen3.5:2b 或是 qwen3.5:9b
            for name in model_names:
                if "qwen3.5" in name:
                    return name
                    
            # 5. 匹配任何包含 qwen 的模型
            for name in model_names:
                if "qwen" in name.lower():
                    return name
                    
            if model_names:
                return model_names[0]
    except Exception as e:
        print(f"[Title Transformer] 查詢可用模型失敗: {e}")
        
    return default_model

def transform_title(original_title, summary):
    """
    調用本地 Ollama 模型，將新聞標題與摘要轉換為「黃山料腔調」的去實體化療癒金句標題
    """
    base_url = get_ollama_base_url()
    url = f"{base_url}/api/chat"
    
    # 獲取合適的模型名稱
    model_name = get_available_qwen_model(base_url)
    print(f"[Title Transformer] 使用 Ollama 連線: {base_url} | 模型: {model_name}")
    
    # 對齊訓練與推理格式 (System / User 角色分工)
    system_content = "你是一位擅長寫療癒系散文的作家（筆名黃山料）。請閱讀使用者提供的原始標題與新聞摘要，將其轉化為一句 25 ~ 40 字、去實體化且符合情感投射的黃山料風格標題。"
    user_content = f"【原始標題】：{original_title.strip()}\n【新聞摘要】：{summary.strip()}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,      # 低溫確保模型遵守去實體化與長度限制
            "num_predict": 1024,     # 給予充足 token 以利思考模型完成推理並輸出
            "stop": ["<|im_end|>"]   # 僅採用 stop token 結束，避免 \n 在開頭截斷
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=45)
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
        
        if transformed:
            # 優先提取書名號《》、雙引號「」內的標題內容
            match = re.search(r"[《\"'「『](.*?)[》\"'」』]", transformed)
            if match:
                transformed = match.group(1).strip()
            else:
                # 否則截取換行符前第一行
                transformed = transformed.split('\n')[0].strip()
                
            # 去除可能殘留的首尾書名號與引號
            transformed = re.sub(r'^[《"\'「『]|[》"\'」』]$', '', transformed).strip()
            
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
    test_title = "Threads、IG帳號停權災情 Meta：技術錯誤、積極修復"
    test_summary = "近日Meta旗下Threads、Instagram等平台爆發大規模帳號停權事件，系統誤判原因均為「年齡未滿13歲」。受影響者包括公視、中央社等媒體，以及陳水扁、柯文哲、陳之漢等公眾人物。Meta坦承因技術錯誤導致誤判，正積極修復。"
    
    new_title = transform_title(test_title, test_summary)
    print("\n--- 標題轉換測試 ---")
    print(f"原標題: {test_title}")
    print(f"新標題: {new_title}")
