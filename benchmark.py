import os
import json
import time
import requests
import threading
import queue
from dotenv import load_dotenv

# 設定路徑
PROJECT_DIR = "c:\\MCAS\\ShanLiao"
dotenv_path = os.path.join(PROJECT_DIR, ".env")
load_dotenv(dotenv_path=dotenv_path)

MISTRAL_KEYS = []
for key_name in ["Mistral", "Mistral2", "Mistral3", "Mistral4", "Mistral5", "Mistral6"]:
    key_val = os.getenv(key_name)
    if not key_val:
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    if f"{key_name}" in line and "=" in line:
                        parts = line.split("=")
                        if len(parts) >= 2:
                            key_val = parts[1].strip().strip("'").strip('"')
                            break
        except Exception as e:
            pass
    if key_val:
        MISTRAL_KEYS.append({"name": key_name, "key": key_val, "status": "active", "cooldown_until": 0})

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_NEWS_PATH = os.path.join(DATA_DIR, "raw_news.jsonl")

# 測試用的鎖與計數器
test_lock = threading.Lock()
success_count = 0
failed_429_count = 0
total_tokens_used = 0
response_times = []

def test_single_request(key_info, article_body):
    """測試單次 API 請求並記錄 token 與時間"""
    global success_count, failed_429_count, total_tokens_used
    headers = {
        "Authorization": f"Bearer {key_info['key']}",
        "Content-Type": "application/json"
    }
    prompt = (
        "你是一位專業的新聞編輯。請閱讀以下新聞全文，提取核心事件、關鍵人物與結果，"
        "整理為一段 100-200 字的精簡摘要。保留客觀事實，不添加主觀評論。\n"
        "請使用繁體中文回答。\n\n"
        f"【新聞全文】\n{article_body[:800]}\n\n" # 限制長度以保證公平
        "【摘要】"
    )
    data = {
        "model": "mistral-large-latest",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    
    t0 = time.time()
    try:
        response = requests.post(MISTRAL_URL, headers=headers, json=data, timeout=20)
        latency = time.time() - t0
        
        with test_lock:
            response_times.append(latency)
            
        if response.status_code == 200:
            res_data = response.json()
            tokens = res_data.get("usage", {}).get("total_tokens", 0)
            with test_lock:
                success_count += 1
                total_tokens_used += tokens
            return {"status": "success", "tokens": tokens, "latency": latency}
        elif response.status_code == 429:
            with test_lock:
                failed_429_count += 1
            return {"status": "429"}
        else:
            return {"status": "error", "code": response.status_code}
    except Exception as e:
        return {"status": "exception", "error": str(e)}

def benchmark_worker(key_info, task_queue, sleep_delay):
    """測試執行緒"""
    while True:
        try:
            body = task_queue.get_nowait()
        except queue.Empty:
            break
            
        res = test_single_request(key_info, body)
        if res["status"] == "success":
            print(f"[{key_info['name']}] 請求成功. 耗時 {res['latency']:.1f} 秒, 消耗 {res['tokens']} tokens")
        elif res["status"] == "429":
            print(f"[{key_info['name']}] !!! 觸發 429 限流 !!!")
        else:
            print(f"[{key_info['name']}] 失敗: {res.get('code', 'exception')}")
            
        task_queue.task_done()
        time.sleep(sleep_delay)

def run_test_configuration(num_threads, sleep_delay):
    """執行特定參數的測試"""
    global success_count, failed_429_count, total_tokens_used, response_times
    success_count = 0
    failed_429_count = 0
    total_tokens_used = 0
    response_times = []
    
    # 載入一些真實新聞內文做測試
    test_articles = []
    if os.path.exists(RAW_NEWS_PATH):
        try:
            with open(RAW_NEWS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        body = data.get("article_body", "")
                        if len(body) > 200:
                            test_articles.append(body)
                        if len(test_articles) >= 12: # 測試 12 筆
                            break
        except Exception as e:
            print(f"讀取測試新聞失敗: {e}")
            
    if not test_articles:
        test_articles = ["這是一篇測試新聞全文內容" * 50] * 12
        
    task_queue = queue.Queue()
    for art in test_articles:
        task_queue.put(art)
        
    print(f"\n===== 開始測試配置: 執行緒數 = {num_threads}, 延遲 = {sleep_delay} 秒 =====")
    t_start = time.time()
    
    active_keys = MISTRAL_KEYS[:num_threads]
    threads = []
    for k_info in active_keys:
        t = threading.Thread(target=benchmark_worker, args=(k_info, task_queue, sleep_delay), daemon=True)
        t.start()
        threads.append(t)
        
    task_queue.join()
    t_end = time.time()
    
    elapsed = t_end - t_start
    avg_latency = sum(response_times) / len(response_times) if response_times else 0
    throughput_sec = success_count / elapsed if elapsed > 0 else 0
    throughput_min = throughput_sec * 60
    avg_tokens = total_tokens_used / success_count if success_count > 0 else 0
    tpm_est = throughput_min * avg_tokens
    
    print(f"\n--- 測試結果 (耗時 {elapsed:.1f} 秒) ---")
    print(f"- 成功次數: {success_count} 次")
    print(f"- 429 次數: {failed_429_count} 次")
    print(f"- 平均響應時間: {avg_latency:.2f} 秒")
    print(f"- 平均每筆消耗 Token: {avg_tokens:.1f} tokens")
    print(f"- 估算推進速度: {throughput_sec:.3f} 筆/秒 (約每分鐘 {throughput_min:.1f} 筆)")
    print(f"- 預估帳戶總 Token 負載: {tpm_est:.1f} TPM (官方免費上限為 25,000 TPM)")
    
    is_safe = (failed_429_count == 0) and (tpm_est < 25000)
    print(f"- 安全評級: {'【100% 安全無虞】' if is_safe else '【⚠️ 有觸發 429 或超出 TPM 限制的風險】'}")
    return {"safe": is_safe, "tps": throughput_sec, "tpm": tpm_est}

if __name__ == "__main__":
    # 進行不同參數的測試
    # 我們可以手動呼叫不同配置來尋找黃金搭配
    run_test_configuration(num_threads=6, sleep_delay=22.0)
