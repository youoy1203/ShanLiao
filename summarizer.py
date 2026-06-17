import os
import json
import time
import re
import requests
from dotenv import load_dotenv
import sys
import io
import threading
import queue

# 強制設定輸出為 UTF-8，解決 Windows 系統日誌亂碼問題
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 設定路徑
PROJECT_DIR = "c:\\MCAS\\ShanLiao"
dotenv_path = os.path.join(PROJECT_DIR, ".env")
load_dotenv(dotenv_path=dotenv_path)

# 獲取 API 金鑰清單
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
        MISTRAL_KEYS.append({
            "name": key_name,
            "key": key_val,
            "status": "active",
            "cooldown_until": 0
        })

print(f"系統已載入的 Mistral API 金鑰數量: {len(MISTRAL_KEYS)}")
for k in MISTRAL_KEYS:
    print(f" - {k['name']}: 狀態={k['status']}")

DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_NEWS_PATH = os.path.join(DATA_DIR, "raw_news.jsonl")
SUMMARY_NEWS_PATH = os.path.join(DATA_DIR, "news_with_summary.jsonl")

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# 延遲設定（每個執行緒在每次請求後的休眠秒數，14秒可更安全地避開 5 RPM 與頻繁限流限制）
SLEEP_DELAY = 14

# 非繁體中文分類黑名單
BLACK_LIST_CATEGORIES = {
    "台語新聞", "英語新聞", "印尼語新聞", "越南語新聞", "泰語新聞", 
    "Hakka", "English", "Vietnam", "Thai", "Indonesian"
}

# 線程安全鎖與計數器
file_lock = threading.Lock()
progress_lock = threading.Lock()
processed_ids = set()

# 全域發送防撞守門人 (用於策略 C)
global_emit_lock = threading.Lock()
last_emit_time = 0.0
MIN_EMIT_GAP = 2.5  # 確保任意兩個發送間隔至少 2.5 秒，以避開 1 RPS 限制

def acquire_emit_token():
    """線程安全地獲取發送許可，若間隔過近則主動等待"""
    global last_emit_time
    with global_emit_lock:
        now = time.time()
        time_since_last = now - last_emit_time
        if time_since_last < MIN_EMIT_GAP:
            wait_time = MIN_EMIT_GAP - time_since_last
            time.sleep(wait_time)
            last_emit_time = time.time()
        else:
            last_emit_time = now
done_count = 0
initial_done = 0
start_time = 0.0

def get_active_keys_count():
    """計算當前處於活躍狀態（未在冷卻且有效）的金鑰數量"""
    now = time.time()
    cnt = 0
    for k in MISTRAL_KEYS:
        if k["status"] == "active" and now >= k["cooldown_until"]:
            cnt += 1
    return cnt

def is_traditional_chinese_news(headline, article_body, category):
    """檢查新聞是否為一般繁體中文報導"""
    if category in BLACK_LIST_CATEGORIES:
        return False
        
    text_to_check = (headline or "") + (article_body or "")
    if not text_to_check.strip():
        return False
        
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text_to_check)
    non_space_text = re.sub(r'\s+', '', text_to_check)
    if not non_space_text:
        return False
        
    ratio = len(chinese_chars) / len(non_space_text)
    if ratio < 0.35:
        return False
        
    thai_chars = re.findall(r'[\u0e00-\u0e7f]', text_to_check)
    if len(thai_chars) > 5:
        return False
        
    return True

def call_mistral_api(article_body, key_info):
    """使用特定的金鑰呼叫 Mistral API 生成摘要。具備限流冷卻與重試機制"""
    prompt = (
        "你是一位專業的新聞編輯。請閱讀以下新聞全文，提取核心事件、關鍵人物與結果，"
        "整理為一段 100-200 字的精簡摘要。保留客觀事實，不添加主觀評論。\n"
        "請使用繁體中文回答。\n\n"
        f"【新聞全文】\n{article_body}\n\n"
        "【摘要】"
    )
    
    data = {
        "model": "mistral-large-latest",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    
    while True:
        # 檢查金鑰是否在冷卻中
        now = time.time()
        if now < key_info["cooldown_until"]:
            wait_sec = int(key_info["cooldown_until"] - now) + 1
            print(f"[LIMIT 429] 金鑰 {key_info['name']} 正在冷卻中。執行緒休眠 {wait_sec} 秒後重試...")
            time.sleep(wait_sec)
            continue
            
        if key_info["status"] != "active":
            print(f"[DEPLETED] 金鑰 {key_info['name']} 已失效。執行緒等待 60 秒...")
            time.sleep(60)
            continue
            
        headers = {
            "Authorization": f"Bearer {key_info['key']}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(MISTRAL_URL, headers=headers, json=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                summary = result["choices"][0]["message"]["content"].strip()
                return summary
            elif response.status_code == 429:
                # 觸發限流，此金鑰冷卻 90 秒，並跳出通知
                key_info["cooldown_until"] = time.time() + 90
                active_cnt = get_active_keys_count()
                total_keys = len(MISTRAL_KEYS)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 觸發限流(429)，將該金鑰冷卻 90 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            elif response.status_code == 401:
                # 額度耗盡，此金鑰失效且冷卻 600 秒，並跳出通知
                key_info["status"] = "depleted"
                key_info["cooldown_until"] = time.time() + 600
                active_cnt = get_active_keys_count()
                total_keys = len(MISTRAL_KEYS)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 額度已耗盡或失效(401)！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            else:
                key_info["cooldown_until"] = time.time() + 30
                active_cnt = get_active_keys_count()
                total_keys = len(MISTRAL_KEYS)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 遇到錯誤 (代碼: {response.status_code})。冷卻 30 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            # 超時異常單獨原地重試，不降低金鑰活躍狀態
            print(f"\n[INFO] 金鑰 {key_info['name']} 請求超時 (Timeout)，將在 3 秒後原地重試，不觸發冷卻限制...\n")
            time.sleep(3)
            continue
        except Exception as e:
            key_info["cooldown_until"] = time.time() + 30
            active_cnt = get_active_keys_count()
            total_keys = len(MISTRAL_KEYS)
            print(f"\n[WARNING] 使用金鑰 {key_info['name']} 請求異常: {e}。冷卻 30 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            
        time.sleep(2)

def load_processed_ids():
    """載入已完成摘要的文章 ID"""
    if not os.path.exists(SUMMARY_NEWS_PATH):
        return set()
        
    ids = set()
    try:
        with open(SUMMARY_NEWS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "id" in data:
                            ids.add(int(data["id"]))
                    except:
                        pass
    except Exception as e:
        print(f"讀取已處理資料時出錯: {e}")
    return ids

def worker(key_info, news_queue, total_raw):
    """工作線程執行函數"""
    global done_count
    while True:
        try:
            news = news_queue.get_nowait()
        except queue.Empty:
            break
            
        # 發送前取得全域發送許可，確保任意兩個發送間隔至少 2.5 秒，避開 1 RPS 限制
        acquire_emit_token()
        
        request_start = time.time()
        article_id = news["id"]
        headline = news["headline"]
        body = news["article_body"]
        
        summary = call_mistral_api(body, key_info)
        if summary:
            # 寫入檔案與更新已處理 ID 必須加鎖
            with file_lock:
                with open(SUMMARY_NEWS_PATH, "a", encoding="utf-8") as out_file:
                    output_data = dict(news)
                    output_data["summary"] = summary
                    out_file.write(json.dumps(output_data, ensure_ascii=False) + "\n")
                    out_file.flush()
                processed_ids.add(int(article_id))
            
            with progress_lock:
                done_count += 1
                percent = (done_count / total_raw) * 100 if total_raw > 0 else 0.0
                
                # 即時速度估算 (每秒幾筆 / 每分鐘幾筆)
                elapsed = time.time() - start_time
                delta_done = done_count - initial_done
                speed_sec = delta_done / elapsed if elapsed > 0 else 0.0
                speed_min = speed_sec * 60
                
            active_cnt = get_active_keys_count()
            total_keys = len(MISTRAL_KEYS)
            
            # 清理標題末尾的「 ｜ 公視新聞網 PNN」或「 | 公視新聞網 PNN」
            clean_headline = re.sub(r'\s*[|｜]\s*公視新聞網\s*PNN\s*$', '', headline).strip()
            
            # 使用舊有的標準格式輸出，後面加上速度與金鑰狀態
            print(f"[PROGRESS] 摘要進度: {done_count}/{total_raw} 篇 ({percent:.2f}%) | 正在處理 ID {article_id} (標題: {clean_headline[:15]}...) | 速度: {speed_sec:.3f} 筆/秒 (每分鐘 {speed_min:.1f} 筆) | 金鑰狀態: {active_cnt}/{total_keys} 可用")
            
        news_queue.task_done()
        # 策略 C：固定計時週期 (扣除請求時間)，防止單一帳戶超出 5 RPM
        elapsed_run = time.time() - request_start
        if elapsed_run < SLEEP_DELAY:
            time.sleep(SLEEP_DELAY - elapsed_run)

def main():
    global done_count, processed_ids, initial_done, start_time
    while True:
        if not os.path.exists(RAW_NEWS_PATH):
            print(f"[WAIT] 找不到原始新聞檔案 {RAW_NEWS_PATH}，等待 scraper.py 下載新聞。將在 30 秒後重新檢查...")
            time.sleep(30)
            continue
            
        processed_ids = load_processed_ids()
        
        raw_news = []
        seen_ids = set()
        try:
            with open(RAW_NEWS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            article_id = int(data.get("id"))
                            if article_id not in seen_ids:
                                if is_traditional_chinese_news(data.get("headline"), data.get("article_body"), data.get("category")):
                                    seen_ids.add(article_id)
                                    raw_news.append(data)
                        except:
                            pass
        except Exception as e:
            print(f"[ERROR] 讀取原始新聞檔案時出錯: {e}。將在 10 秒後重試...")
            time.sleep(10)
            continue
            
        total_raw = len(raw_news)
        to_process = [news for news in raw_news if int(news["id"]) not in processed_ids]
        
        if not to_process:
            print(f"[COMPLETE] 目前已完成所有已下載新聞的摘要處理。目前有效總數: {total_raw} 筆。將在 60 秒後重新檢查是否有新下載的文章...")
            time.sleep(60)
            continue
            
        done_count = len(processed_ids)
        initial_done = done_count
        start_time = time.time()
        
        print(f"\n[START] 啟動多執行緒摘要生成。載入繁中新聞總數: {total_raw} 筆，已完成: {done_count} 筆，本次待處理: {len(to_process)} 筆。")
        print(f"啟動 {len(MISTRAL_KEYS)} 個工作執行緒並行處理中 (延遲參數: {SLEEP_DELAY}秒)...")
        
        news_queue = queue.Queue()
        for news in to_process:
            news_queue.put(news)
            
        threads = []
        for key_info in MISTRAL_KEYS:
            t = threading.Thread(target=worker, args=(key_info, news_queue, total_raw), daemon=True)
            t.start()
            threads.append(t)
            
        news_queue.join()
        
        print("\n[INFO] 本批次已下載新聞已全部處理完畢。將在 10 秒後重新檢查是否有新文章...")
        time.sleep(10)

if __name__ == "__main__":
    main()
