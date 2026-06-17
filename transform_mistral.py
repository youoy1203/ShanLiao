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
import http.server
import socketserver
import urllib.parse

# 強制設定輸出為 UTF-8，解決 Windows 系統日誌亂碼問題
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 設定路徑
PROJECT_DIR = "c:\\MCAS\\ShanLiao"
dotenv_path = os.path.join(PROJECT_DIR, ".env")
load_dotenv(dotenv_path=dotenv_path)

DATA_DIR = os.path.join(PROJECT_DIR, "data")
SUMMARY_NEWS_PATH = os.path.join(DATA_DIR, "news_with_summary.jsonl")
TRANSFORMED_NEWS_PATH = os.path.join(DATA_DIR, "transformed_news.jsonl")
RULEBOOK_PATH = os.path.join(PROJECT_DIR, "style_rulebook.md")

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# 共享狀態變數 (Thread-safe)
class DashboardState:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_raw = 0
        self.done_count = 0
        self.last_transform = {
            "id": None,
            "headline": "",
            "summary": "",
            "shanliao_title": "",
            "timestamp": ""
        }
        self.sleep_delay = 14.0
        self.min_emit_gap = 2.5
        self.last_emit_time = 0.0
        self.keys = []

state = DashboardState()

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
            "cooldown_until": 0,
            "enabled": True
        })

state.keys = MISTRAL_KEYS

print(f"系統已載入的 Mistral API 金鑰數量: {len(state.keys)}")
for k in state.keys:
    print(f" - {k['name']}: 狀態={k['status']}, 啟用狀態={k['enabled']}")

# 精簡版黃山料風格規則，壓縮 token 數並加強 25-40 字數、短結構與開頭多樣性控制
style_rules = (
    "1. 字數限制：必須嚴格控制在 25 ~ 40 個繁體中文字之間，絕對不要超過 40 字。\n"
    "2. 結構限制：標題僅能由一至兩個短句構成（僅使用一個逗號分隔，並以句號收尾），避免冗長鋪陳。\n"
    "3. 嚴格去實體化：絕對禁止出現具體人名、地名、國家、公司、數字、英文或專有名詞（例如：川普、台灣、Threads 均不可出現）。\n"
    "4. 事件情感投射：將新聞衝突柔化、抽象化，轉為情感隱喻（例如：負面事件轉為青春遺憾與放手；正面事件轉為雨季後的放晴與原諒）。\n"
    "5. 句型開頭多樣化（極重要，嚴禁千篇一律以『那些』開頭）：\n"
    "   - 否定翻義開頭（推薦）：『這扇被關上的門，不是……而是……』\n"
    "   - 時間/對照開頭（推薦）：『雨終於停了，就像……』、『我們總以為……』\n"
    "   - 願式祈禱開頭（推薦）：『願你/願我們……』\n"
    "   - 自由散文詩開頭（推薦）：『有時候覺得受了傷，其實只是……』\n"
    "   - 那些開頭（比例限制小於 20%）：『那些……就像……』\n"
    "6. 常用風格詞彙：溫柔、遺憾、錯過、原諒、擁抱、相遇、青春、放手、自己、平靜、餘生。\n"
    "7. 多樣化風格範例（30字左右）：\n"
    "   - 否定翻義起手 -> 突然被切斷的連結，不是世界將你遺忘，而是時間溫柔地提醒你回到生活。\n"
    "   - 願式祈禱起手 -> 這世界的遙遠角落又落下了名為衝突的雨，願所有受傷的心靈找到平靜。\n"
    "   - 時間對照起手 -> 這場漫長的雨終於要停了，就像淋濕的青春，終究會在放晴的傍晚晾乾自己。"
)

# 線程安全鎖與計數器
file_lock = threading.Lock()
progress_lock = threading.Lock()
processed_ids = set()

# 全域發送防撞守門人 (用於策略 C)
global_emit_lock = threading.Lock()

def acquire_emit_token():
    """線程安全地獲取發送許可，若間隔過近則主動等待"""
    with global_emit_lock:
        now = time.time()
        with state.lock:
            current_gap = state.min_emit_gap
        time_since_last = now - state.last_emit_time
        if time_since_last < current_gap:
            wait_time = current_gap - time_since_last
            time.sleep(wait_time)
            state.last_emit_time = time.time()
        else:
            state.last_emit_time = now

done_count = 0
initial_done = 0
start_time = 0.0

def get_active_keys_count():
    """計算當前處於活躍狀態（未在冷卻且有效且被啟用）的金鑰數量"""
    now = time.time()
    cnt = 0
    with state.lock:
        for k in state.keys:
            if k["enabled"] and k["status"] == "active" and now >= k["cooldown_until"]:
                cnt += 1
    return cnt

def call_mistral_transform(headline, summary, key_info):
    """呼叫 Mistral API 將摘要轉換為黃山料風格標題，具備限流冷卻與重試機制"""
    prompt = (
        "你是一位擅長寫心靈療癒散文的作家（筆名黃山料）。請閱讀以下新聞的原始標題與核心摘要，"
        "將其轉化為一句具有「黃山料風格」的療癒系標題。\n\n"
        "【嚴格轉換規則】\n"
        "1. 字數必須控制在 25-40 字之間，絕對不可超過 40 字。\n"
        "2. 必須進行「去實體化」：絕對不可以出現任何具體人名、地名、國家、公司名、數字或英文（例如不能出現：川普、台灣、100、VS Code、Meta）。\n"
        "3. 將新聞事件投射為情感隱喻（例如：衝突事件轉為青春的陣痛與放手，成功事件轉為放晴與原諒）。\n"
        "4. 【極重要：句型起手式多樣化限制】\n"
        "   - 絕對禁止連續多句以『那些……』開頭。你必須靈活變更開頭的字詞與句子骨架！\n"
        "   - 請多嘗試使用以下多元起手式：\n"
        "     * 否定翻義起手：『不是……是……』 / 『這扇被關上的門，不是……而是……』\n"
        "     * 願式祈願起手：『願你……』 / 『願我們……』\n"
        "     * 時間對照起手：『雨終於要停了，就像……』 / 『我們總以為……』\n"
        "     * 自由主語起手：『有時候覺得受了傷，其實只是……』 / 『我們總是急著……』\n"
        "     * 僅在少數情況下（不超過20%）才可使用：『那些……就像……』\n"
        "5. 常用詞彙：溫柔、遺憾、錯過、原諒、擁抱、相遇、青春、放手、自己、平靜。\n\n"
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
        # 動態檢查此金鑰是否已被停用
        with state.lock:
            if not key_info["enabled"]:
                time.sleep(1)
                continue
                
        now = time.time()
        if now < key_info["cooldown_until"]:
            wait_sec = int(key_info["cooldown_until"] - now) + 1
            print(f"[LIMIT 429] 金鑰 {key_info['name']} 正在冷卻中。執行緒休眠 {wait_sec} 秒後重試...")
            time.sleep(wait_sec)
            continue
            
        with state.lock:
            if key_info["status"] == "cooldown" and now >= key_info["cooldown_until"]:
                key_info["status"] = "active"
                
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
                title = result["choices"][0]["message"]["content"].strip()
                title = re.sub(r'^["\'「『]|["\'」』]$', '', title).strip()
                return title
            elif response.status_code == 429:
                with state.lock:
                    key_info["cooldown_until"] = time.time() + 90
                    key_info["status"] = "cooldown"
                active_cnt = get_active_keys_count()
                total_keys = len(state.keys)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 觸發限流(429)，將該金鑰冷卻 90 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            elif response.status_code == 401:
                with state.lock:
                    key_info["status"] = "depleted"
                    key_info["cooldown_until"] = time.time() + 600
                active_cnt = get_active_keys_count()
                total_keys = len(state.keys)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 額度已耗盡或失效(401)！可用金鑰狀態: {active_cnt}/{total_keys}\n")
            else:
                with state.lock:
                    key_info["cooldown_until"] = time.time() + 30
                active_cnt = get_active_keys_count()
                total_keys = len(state.keys)
                print(f"\n[WARNING] 金鑰 {key_info['name']} 遇到錯誤 (代碼: {response.status_code})。冷卻 30 秒！可用金鑰狀態: {active_cnt}/{total_keys}\n")
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            print(f"\n[INFO] 金鑰 {key_info['name']} 請求超時 (Timeout)，將在 3 秒後原地重試，不觸發冷卻限制...\n")
            time.sleep(3)
            continue
        except Exception as e:
            with state.lock:
                key_info["cooldown_until"] = time.time() + 30
            active_cnt = get_active_keys_count()
            total_keys = len(state.keys)
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
        # 動態檢查此金鑰是否啟用
        with state.lock:
            is_enabled = key_info["enabled"]
        if not is_enabled:
            time.sleep(1.5)
            continue
            
        try:
            news = news_queue.get_nowait()
        except queue.Empty:
            break
            
        # 發送前取得全域發送許可，確保防撞間隔
        acquire_emit_token()
        
        request_start = time.time()
        article_id = news["id"]
        headline = news["headline"]
        summary = news["summary"]
        
        shanliao_title = call_mistral_transform(headline, summary, key_info)
        if shanliao_title:
            with file_lock:
                # 雙重鎖檢查以防重複寫入
                if int(article_id) not in processed_ids:
                    with open(TRANSFORMED_NEWS_PATH, "a", encoding="utf-8") as out_file:
                        output_data = dict(news)
                        output_data["shanliao_title"] = shanliao_title
                        out_file.write(json.dumps(output_data, ensure_ascii=False) + "\n")
                        out_file.flush()
                    processed_ids.add(int(article_id))
                    
                    with state.lock:
                        state.done_count = len(processed_ids)
                        state.last_transform = {
                            "id": article_id,
                            "headline": headline,
                            "summary": summary,
                            "shanliao_title": shanliao_title,
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                        }
            
            with progress_lock:
                done_count += 1
                percent = (done_count / total_raw) * 100 if total_raw > 0 else 0.0
                elapsed = time.time() - start_time
                delta_done = done_count - initial_done
                speed_sec = delta_done / elapsed if elapsed > 0 else 0.0
                speed_min = speed_sec * 60
                
            active_cnt = get_active_keys_count()
            total_keys = len(state.keys)
            clean_headline = re.sub(r'\s*[|｜]\s*公視新聞網\s*PNN\s*$', '', headline).strip()
            print(f"[PROGRESS] 標題風格轉換進度: {done_count}/{total_raw} 篇 ({percent:.2f}%) | 正在處理 ID {article_id} (標題: {clean_headline[:15]}...) | 速度: {speed_sec:.3f} 筆/秒 (每分鐘 {speed_min:.1f} 筆) | 金鑰狀態: {active_cnt}/{total_keys} 可用")
            
        news_queue.task_done()
        
        # 讀取當前的 sleep_delay 設定
        with state.lock:
            current_delay = state.sleep_delay
            
        elapsed_run = time.time() - request_start
        if elapsed_run < current_delay:
            time.sleep(current_delay - elapsed_run)

# ----------------- Web 伺服器與 HTML 模板 -----------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>新聞風格轉換控制面板</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #ffffff;
            color: #000000;
            margin: 0;
            padding: 40px;
            display: flex;
            justify-content: center;
        }
        .container {
            width: 100%;
            max-width: 800px;
        }
        h1 {
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 30px;
            letter-spacing: -0.5px;
            border-bottom: 1px solid #e0e0e0;
            padding-bottom: 10px;
        }
        .section {
            margin-bottom: 40px;
        }
        .section-title {
            font-size: 14px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #666666;
            margin-bottom: 15px;
        }
        .progress-box {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .progress-text {
            font-size: 32px;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .progress-bar-bg {
            background-color: #f0f0f0;
            height: 8px;
            border-radius: 4px;
            width: 100%;
            overflow: hidden;
        }
        .progress-bar-fill {
            background-color: #000000;
            height: 100%;
            width: 0%;
            transition: width 0.5s ease;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 40px;
        }
        @media (max-width: 600px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
        .config-group {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .input-item {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .input-item label {
            font-size: 13px;
            color: #666666;
        }
        .input-item input[type="number"] {
            border: 1px solid #cccccc;
            padding: 8px 12px;
            font-size: 14px;
            background-color: #ffffff;
            color: #000000;
            outline: none;
            transition: border-color 0.2s;
        }
        .input-item input[type="number"]:focus {
            border-color: #000000;
        }
        .btn {
            background-color: #000000;
            color: #ffffff;
            border: 1px solid #000000;
            padding: 10px 15px;
            font-size: 14px;
            cursor: pointer;
            font-weight: 500;
            transition: background-color 0.2s, color 0.2s;
            text-align: center;
        }
        .btn:hover {
            background-color: #333333;
        }
        .key-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .key-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        .key-info {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .key-item input[type="checkbox"] {
            width: 16px;
            height: 16px;
            cursor: pointer;
            accent-color: #000000;
        }
        .key-name {
            font-weight: 500;
            font-size: 14px;
        }
        .key-status {
            font-size: 13px;
            color: #666666;
        }
        .key-status.cooldown {
            color: #888888;
            font-style: italic;
        }
        .card {
            border: 1px solid #e0e0e0;
            padding: 25px;
            background-color: #ffffff;
        }
        .card-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #888888;
            margin-bottom: 8px;
        }
        .card-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 15px;
            line-height: 1.4;
        }
        .card-summary {
            font-size: 14px;
            color: #555555;
            margin-bottom: 20px;
            line-height: 1.6;
            border-left: 2px solid #e0e0e0;
            padding-left: 15px;
        }
        .card-result {
            font-size: 18px;
            font-weight: 700;
            line-height: 1.5;
            color: #000000;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>新聞風格轉換控制面板</h1>
        
        <!-- 進度區 -->
        <div class="section">
            <div class="section-title">目前轉換進度</div>
            <div class="progress-box">
                <div class="progress-text" id="progressText">0 / 0 篇 (0.00%)</div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="progressBar"></div>
                </div>
            </div>
        </div>
        
        <div class="grid">
            <!-- 設定與金鑰 -->
            <div>
                <div class="section">
                    <div class="section-title">參數調校</div>
                    <div class="config-group">
                        <div class="input-item">
                            <label for="sleepDelayInput">單次請求休眠延遲 (秒)</label>
                            <input type="number" id="sleepDelayInput" min="0.5" step="0.5" value="14">
                        </div>
                        <div class="input-item">
                            <label for="minEmitGapInput">金鑰防撞間隔 (秒)</label>
                            <input type="number" id="minEmitGapInput" min="0.1" step="0.1" value="2.5">
                        </div>
                        <button class="btn" onclick="saveConfig()">儲存設定</button>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-title">API 金鑰狀態 (勾選以啟用)</div>
                    <div class="key-list" id="keyList">
                        <!-- 金鑰動態產生 -->
                    </div>
                </div>
            </div>
            
            <!-- 最近一次轉換 -->
            <div>
                <div class="section">
                    <div class="section-title">最近一次轉換內容</div>
                    <div class="card">
                        <div class="card-label">原始新聞標題</div>
                        <div class="card-title" id="lastTitle">尚未開始轉換</div>
                        
                        <div class="card-label">新聞核心摘要</div>
                        <div class="card-summary" id="lastSummary">無</div>
                        
                        <div class="card-label">黃山料風格療癒金句</div>
                        <div class="card-result" id="lastResult">無</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function fetchStatus() {
            try {
                const response = await fetch('/api/status');
                if (response.ok) {
                    const data = await response.json();
                    updateUI(data);
                }
            } catch (err) {
                console.error("無法取得狀態資訊:", err);
            }
        }

        function updateUI(data) {
            const percent = data.total_raw > 0 ? ((data.done_count / data.total_raw) * 100).toFixed(2) : '0.00';
            document.getElementById('progressText').innerText = `${data.done_count.toLocaleString()} / ${data.total_raw.toLocaleString()} 篇 (${percent}%)`;
            document.getElementById('progressBar').style.width = `${percent}%`;

            const keyList = document.getElementById('keyList');
            let keysHtml = '';
            data.keys.forEach(k => {
                const statusText = k.status === 'depleted' 
                    ? '額度耗盡 (已禁用)' 
                    : (k.cooldown_left > 0 ? `冷卻中 (${k.cooldown_left}s)` : '正常運行');
                const isChecked = k.enabled ? 'checked' : '';
                keysHtml += `
                    <div class="key-item">
                        <div class="key-info">
                            <input type="checkbox" id="chk_${k.name}" ${isChecked} onchange="toggleKey('${k.name}', this.checked)">
                            <span class="key-name">${k.name}</span>
                        </div>
                        <span class="key-status ${k.cooldown_left > 0 ? 'cooldown' : ''}">${statusText}</span>
                    </div>
                `;
            });
            keyList.innerHTML = keysHtml;

            if (data.last_transform && data.last_transform.id) {
                document.getElementById('lastTitle').innerText = data.last_transform.headline;
                document.getElementById('lastSummary').innerText = data.last_transform.summary;
                document.getElementById('lastResult').innerText = data.last_transform.shanliao_title;
            }
        }

        async function toggleKey(name, enabled) {
            const keysConfig = {};
            const checkboxes = document.querySelectorAll('.key-item input[type="checkbox"]');
            checkboxes.forEach(cb => {
                const keyName = cb.id.replace('chk_', '');
                keysConfig[keyName] = cb.checked;
            });
            keysConfig[name] = enabled;
            await sendConfig({ keys: keysConfig });
        }

        async function saveConfig() {
            const sleepDelay = parseFloat(document.getElementById('sleepDelayInput').value);
            const minEmitGap = parseFloat(document.getElementById('minEmitGapInput').value);
            
            if (isNaN(sleepDelay) || sleepDelay < 0.5) {
                alert("休眠延遲不能小於 0.5 秒");
                return;
            }
            if (isNaN(minEmitGap) || minEmitGap < 0.1) {
                alert("防撞間隔不能小於 0.1 秒");
                return;
            }

            const success = await sendConfig({
                sleep_delay: sleepDelay,
                min_emit_gap: minEmitGap
            });
            
            if (success) {
                alert("設定已儲存並即時套用！");
            } else {
                alert("儲存設定失敗");
            }
        }

        async function sendConfig(payload) {
            try {
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                return response.ok;
            } catch (err) {
                console.error("發送設定失敗:", err);
                return false;
            }
        }

        async function initialLoad() {
            try {
                const response = await fetch('/api/status');
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('sleepDelayInput').value = data.sleep_delay;
                    document.getElementById('minEmitGapInput').value = data.min_emit_gap;
                    updateUI(data);
                }
            } catch (err) {
                console.error("初始化載入失敗:", err);
            }
        }

        initialLoad();
        setInterval(fetchStatus, 2000);
    </script>
</body>
</html>
"""

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 覆寫以避免日誌洗板
        pass
        
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode('utf-8'))
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            now = time.time()
            keys_status = []
            with state.lock:
                for k in state.keys:
                    cooldown_left = 0
                    if k["cooldown_until"] > now:
                        cooldown_left = max(0, int(k["cooldown_until"] - now))
                    
                    keys_status.append({
                        "name": k["name"],
                        "enabled": k["enabled"],
                        "status": k["status"],
                        "cooldown_left": cooldown_left
                    })
                
                status_data = {
                    "total_raw": state.total_raw,
                    "done_count": state.done_count,
                    "last_transform": state.last_transform,
                    "sleep_delay": state.sleep_delay,
                    "min_emit_gap": state.min_emit_gap,
                    "keys": keys_status
                }
            self.wfile.write(json.dumps(status_data, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_error(404, "File Not Found")
            
    def do_POST(self):
        if self.path == '/api/config':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                config = json.loads(post_data.decode('utf-8'))
                with state.lock:
                    if 'sleep_delay' in config:
                        state.sleep_delay = float(config['sleep_delay'])
                        print(f"[CONFIG] 執行中動態調整單次請求延遲為: {state.sleep_delay} 秒")
                    if 'min_emit_gap' in config:
                        state.min_emit_gap = float(config['min_emit_gap'])
                        print(f"[CONFIG] 執行中動態調整發送防撞間隔為: {state.min_emit_gap} 秒")
                    if 'keys' in config:
                        for k in state.keys:
                            name = k["name"]
                            if name in config['keys']:
                                before_val = k["enabled"]
                                k["enabled"] = bool(config['keys'][name])
                                if before_val != k["enabled"]:
                                    status_str = "啟用" if k["enabled"] else "停用"
                                    print(f"[CONFIG] 執行中動態 {status_str} 金鑰 {name}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_error(404, "File Not Found")

def start_web_server(port=8000):
    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        allow_reuse_address = True

    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), DashboardHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print(f"\n[WEB] 控制面板已啟動！請在瀏覽器中打開 http://127.0.0.1:{port} 進行監控與調整。\n")
    except Exception as e:
        print(f"[WEB] 無法在 port {port} 啟動 Web 伺服器: {e}")

# ----------------------------------------------------------

def main():
    global done_count, processed_ids, initial_done, start_time
    
    start_web_server(8000)
    
    while True:
        if not os.path.exists(SUMMARY_NEWS_PATH):
            print(f"[WAIT] 找不到已摘要的新聞檔案 {SUMMARY_NEWS_PATH}，等待 summarizer.py 生成摘要。將在 30 秒後重新檢查...")
            time.sleep(30)
            continue
            
        processed_ids = load_processed_ids()
        
        summary_news = []
        seen_ids = set()
        try:
            with open(SUMMARY_NEWS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            article_id = int(data.get("id"))
                            if article_id not in seen_ids:
                                seen_ids.add(article_id)
                                summary_news.append(data)
                        except:
                            pass
        except Exception as e:
            print(f"[ERROR] 讀取新聞摘要檔案時出錯: {e}。將在 10 秒後重試...")
            time.sleep(10)
            continue
            
        # 根本解決 7015 問題：移除了硬性截斷到 7000 的程式碼，並在上面使用 seen_ids 對資料庫進行去重載入
        
        with state.lock:
            state.total_raw = len(summary_news)
            state.done_count = len(processed_ids)
            
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
        print(f"啟動 {len(state.keys)} 個工作執行緒並行處理中...")
        
        # 建立 Queue
        news_queue = queue.Queue()
        for news in to_process:
            news_queue.put(news)
            
        # 啟動執行緒
        threads = []
        for key_info in state.keys:
            t = threading.Thread(target=worker, args=(key_info, news_queue, total_raw), daemon=True)
            t.start()
            threads.append(t)
            
        # 阻塞等待所有 Queue 任務完成
        news_queue.join()
        
        print("\n[INFO] 本批次已完成所有轉換。將在 10 秒後重新檢查是否有新摘要...")
        time.sleep(10)

if __name__ == "__main__":
    main()
