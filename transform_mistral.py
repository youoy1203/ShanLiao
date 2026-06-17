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
SUMMARY_NEWS_PATH = os.path.join(DATA_DIR, "news_with_summary.jsonl")
TRANSFORMED_NEWS_PATH = os.path.join(DATA_DIR, "transformed_news.jsonl")
RULEBOOK_PATH = os.path.join(PROJECT_DIR, "style_rulebook.md")

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# 延遲設定（每個執行緒在每次請求後的休眠秒數，14秒可更安全地避開 5 RPM 與頻繁限流限制）
SLEEP_DELAY = 14

# 載入風格規則書內容以提供給 Prompt 參考
style_rules = ""
if os.path.exists(RULEBOOK_PATH):
    try:
        with open(RULEBOOK_PATH, "r", encoding="utf-8") as f:
            style_rules = f.read()
    except Exception as e:
        print(f"警告: 無法讀取規則書 {RULEBOOK_PATH}: {e}")

# 線程安全鎖與計數器
file_lock = threading.Lock()
progress_lock = threading.Lock()
processed_ids = set()
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

def call_mistral_transform(headline, summary, key_info):
    """呼叫 Mistral API 將摘要轉換為黃山料風格標題，具備限流冷卻與重試機制"""
    prompt = (
        "你是一位擅長寫心靈療癒散文的作家（筆名黃山料）。請閱讀以下新聞的原始標題與核心摘要，"
        "將其轉化為一句具有「黃山料風格」的療癒系標題。\n\n"
        "【嚴格轉換規則】\n"
        "1. 字數必須控制在 25-40 字之間。\n"
        "2. 必須進行「去實體化」：絕對不可以出現任何具體人名、地名、國家、公司名、數字或英文（例如不能出現：川普、台灣、100、VS Code、Meta）。\n"
        "3. 將新聞事件投射為情感隱喻（例如：衝突事件轉為青春的陣痛與放手，成功事件轉為放晴與原諒）。\n"
        "4. 請使用經典句型公式：\n"
        "   - 『那些……就像……』\n"
        "   - 『不是……是……』\n"
        "   - 『只要……就……』\n"
        "   - 『願你……』\n"
        "5. 常用詞彙：溫柔、遺憾、錯過、原諒、擁抱、相遇、青春、放手、自己。\n\n"
        f"【風格規則書參考】\n{style_rules}\n\n"
        f"【原始新聞標題】{headline}\n"
        f"【新聞核心摘要】{summary}\n\n"
        "請直接輸出轉換後的黃山料風格標題，不要有任何多餘的解釋、說明或引號。"
    )
    
    data = {
        "model": "mistral-large-latest",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3
    }
    
    while True:
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
            response = requests.post(MISTRAL_URL, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                title = result["choices"][0]["message"]["content"].strip()
                title = re.sub(r'^["\'「『]|["\'」』]$', '', title).strip()
                return title
            elif response.status_code == 429:
                key_info["cooldown_until"] = time.time() + 90
                active_cnt = get_active_keys_count()
                total_keys = len(MISTRAL_KEYS)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 觸發限流(429)，將該金鑰冷卻 90 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            elif response.status_code == 401:
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
        except Exception as e:
            key_info["cooldown_until"] = time.time() + 30
            active_cnt = get_active_keys_count()
            total_keys = len(MISTRAL_KEYS)
            print(f"\n[WARNING] 使用金鑰 {key_info['name']} 請求異常: {e}。冷卻 30 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            
        time.sleep(2)

def load_processed_ids():
    """載入已完成風格標題轉換的文章 ID"""
    if not os.path.exists(TRANSFORMED_NEWS_PATH):
        return set()
        
    ids = set()
    try:
        with open(TRANSFORMED_NEWS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "id" in data:
                            ids.add(int(data["id"]))
                    except:
                        pass
    except Exception as e:
        print(f"讀取已轉換資料時出錯: {e}")
    return ids

def worker(key_info, news_queue, total_raw):
    """工作線程執行風格標題轉換"""
    global done_count
    while True:
        try:
            news = news_queue.get_nowait()
        except queue.Empty:
            break
            
        article_id = news["id"]
        headline = news["headline"]
        summary = news["summary"]
        
        shanliao_title = call_mistral_transform(headline, summary, key_info)
        if shanliao_title:
            with file_lock:
                with open(TRANSFORMED_NEWS_PATH, "a", encoding="utf-8") as out_file:
                    output_data = dict(news)
                    output_data["shanliao_title"] = shanliao_title
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
            print(f"[PROGRESS] 標題風格轉換進度: {done_count}/{total_raw} 篇 ({percent:.2f}%) | 正在處理 ID {article_id} (標題: {clean_headline[:15]}...) | 速度: {speed_sec:.3f} 筆/秒 (每分鐘 {speed_min:.1f} 筆) | 金鑰狀態: {active_cnt}/{total_keys} 可用")
            
        news_queue.task_done()
        # 該金鑰執行緒冷卻休眠，防止共享帳戶/IP撞到 Rate Limits
        time.sleep(SLEEP_DELAY)

def main():
    global done_count, processed_ids, initial_done, start_time
    while True:
        if not os.path.exists(SUMMARY_NEWS_PATH):
            print(f"[WAIT] 找不到已摘要的新聞檔案 {SUMMARY_NEWS_PATH}，等待 summarizer.py 生成摘要。將在 30 秒後重新檢查...")
            time.sleep(30)
            continue
            
        processed_ids = load_processed_ids()
        
        summary_news = []
        try:
            with open(SUMMARY_NEWS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            summary_news.append(data)
                        except:
                            pass
        except Exception as e:
            print(f"[ERROR] 讀取已摘要新聞出錯: {e}。將在 10 秒後重試...")
            time.sleep(10)
            continue
            
        total_raw = len(summary_news)
        to_process = [news for news in summary_news if int(news["id"]) not in processed_ids]
        
        if not to_process:
            print(f"[COMPLETE] 目前已完成所有已摘要新聞的風格標題轉換！目前轉換總數: {total_raw} 筆。將在 60 秒後重新檢查是否有新摘要...")
            time.sleep(60)
            continue
            
        done_count = len(processed_ids)
        initial_done = done_count
        start_time = time.time()
        
        print(f"\n[START] 啟動多執行緒山料風格標題轉換。載入摘要總數: {total_raw} 筆，已完成: {done_count} 筆，本次待處理: {len(to_process)} 筆。")
        print(f"啟動 {len(MISTRAL_KEYS)} 個工作執行緒並行處理中 (延遲參數: {SLEEP_DELAY}秒)...")
        
        # 建立 Queue
        news_queue = queue.Queue()
        for news in to_process:
            news_queue.put(news)
            
        # 啟動執行緒
        threads = []
        for key_info in MISTRAL_KEYS:
            t = threading.Thread(target=worker, args=(key_info, news_queue, total_raw), daemon=True)
            t.start()
            threads.append(t)
            
        # 阻塞等待所有 Queue 任務完成
        news_queue.join()
        
        print("\n[INFO] 本批次已完成所有轉換。將在 10 秒後重新檢查是否有新摘要...")
        time.sleep(10)

if __name__ == "__main__":
    main()
