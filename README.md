# 公視新聞自動化摘要與 Discord 發送系統

本專案是一個新聞自動化串接與發布系統。它會自動抓取公視新聞 RSS，對比 SQLite 本地資料庫過濾重複新聞，調用 **Mistral Large API (mistral-large-2512)** 為所有新新聞生成繁體中文摘要，並調用本地 Ollama 服務中的 **`shanliao-qwen`** 微調模型進行黃山料風格的標題轉換，最後透過 Discord 機器人以 Markdown 格式發送至指定的 Discord 頻道。

---

## 📂 專案檔案結構

- `main.py`：整合主程式，負責 RSS 抓取、排重、摘要生成與 Discord Bot 發送控制。
- `ai_summarizer.py`：串接 Mistral Large API 的摘要生成模組（內含 429 速率重試機制）。
- `title_transformer.py`：串接本地 Ollama `shanliao-qwen` 模型的標題轉換模組（內置動態 IP 探測與 fallback 機制）。
- `db_manager.py`：本地 SQLite 資料庫排重管理器。
- `rss_parser.py`：RSS 新聞網頁與內文解析模組。
- `.env`：環境變數檔案（包含 Discord Token 與 Mistral API key，此檔案已排除於 Git 上傳之外）。
- `requirements.txt`：Python 依賴套件清單。
- `.gitignore`：排除臨時檔案、環境變數與 `news.db` 資料庫上傳。

---

## ⚙️ 環境變數設定 (`.env`)

請在專案目錄下建立 `.env` 檔案，填入您的 Token 與 API key：

```env
Discord=您的_Discord_Bot_Token
Mistral=您的_Mistral_API_Key
```

---

## 🍓 樹莓派 4B (Raspberry Pi 4B) 部署與執行指南

本系統極為輕量，非常適合部署於 **樹莓派 4B (建議 4GB 或 8GB RAM 版本)** 上作為常駐的自動化新聞推送機器人。

### 1. 安裝系統與 Python 依賴

確保您的樹莓派已連線上網，並在終端機中執行：

```bash
# 更新軟體源
sudo apt-get update && sudo apt-get upgrade -y

# 安裝 Python3 與 venv
sudo apt-get install -y python3 python3-pip python3-venv

# 複製專案代碼到樹莓派後，在專案目錄下：
# 1. 建立 Python 虛擬環境 (venv)
python3 -m venv venv

# 2. 啟用虛擬環境
source venv/bin/activate

# 3. 在虛擬環境中安裝依賴套件
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. 在樹莓派安裝並配置 Ollama

樹莓派 4B (ARM64) 原生支援 Ollama，執行微調後的 `shanliao-qwen` (Qwen 1.7B) 模型僅需消耗約 1.2GB RAM，CPU 運算速度足夠應對單次排程。

1. **一鍵安裝 Ollama**：
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```
2. **導入您的微調模型**：
   如果您已經有了微調好的 `shanliao-qwen` 權重模型，可透過建立 `Modelfile` 導入：
   ```bash
   # 1. 建立一個名為 Modelfile 的檔案，內容如下：
   # FROM /path/to/your/fine-tuned-model.gguf
   
   # 2. 在 Ollama 中創建模型：
   ollama create shanliao-qwen -f Modelfile
   ```
3. **驗證模型是否正常運行**：
   ```bash
   ollama run shanliao-qwen
   ```

### 3. 本機預設連線 (Localhost Connection)

本專案預設會連線至樹莓派本機的 `http://localhost:11434`。若您的 Ollama 服務運行於其他 IP 或連接埠，可透過設定系統環境變數 `OLLAMA_BASE_URL`（例如：`export OLLAMA_BASE_URL=http://<你的IP>:11434`）來指定連線網址。

### 4. 設定自動化排程 (Cron)

若要讓樹莓派每天在 **早上 8:00、中午 12:00、晚上 18:00、晚上 23:00** 自動啟動程式，抓取未處理的新聞、生成摘要並發送到 Discord：

1. 開啟排程編輯器：
   ```bash
   crontab -e
   ```
2. 在最下方加入以下設定（請將 `/home/pi/ShanLiao` 替換為您在樹莓派上的實際專案路徑）：
   ```bash
    # 每天 08:00、12:00、18:00、23:00 自動啟動，並透過虛擬環境運行
    0 8,12,18,23 * * * cd /home/pi/ShanLiao && /home/pi/ShanLiao/venv/bin/python3 main.py >> cron.log 2>&1
    ```
