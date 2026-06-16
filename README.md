# 公視新聞自動化摘要與 Discord 發送系統

本專案是一個運行於 WSL (Ubuntu) 環境的新聞自動化串接與發布系統。它會自動抓取公視新聞 RSS，對比 SQLite 本地資料庫過濾重複新聞，並調用 **Mistral Large API (mistral-large-2512)** 為所有新新聞生成繁體中文摘要，最後透過 Discord 機器人以 Markdown 格式發送至指定的 Discord 頻道。

## 🌟 功能特點

1. **新聞不遺漏處理**：每次執行會主動獲取 RSS 上的所有新聞，並與本地 SQLite 資料庫比對，篩選出所有未處理的新新聞。
2. **Mistral Large 2512 整合**：採用 Mistral 最新的旗艦模型進行高水準的繁體中文新聞摘要生成。
3. **內建 Rate Limit 防護**：針對 `mistral-large-2512` 限制每秒 0.07 次請求（約每 14.3 秒 1 次）的硬性規定，程式內部對兩次 API 請求之間強制實施 15 秒的延遲，徹底杜絕 `HTTP 429 Too Many Requests` 報錯。
4. **時序發布排序**：新新聞發布順序經優化，自動調整為「較早的新聞優先發布（由舊到新）」，符合時序邏輯。
5. **新聞分類標示**：自動從新聞詳細網頁中解析出報導分類（如：國際、生活、社會等），並獨立標示於 Discord Markdown 訊息中。
6. **SQLite 自動排重**：每次發送成功後自動將新聞寫入本地 `news.db`，確保不重複發布。
7. **單次執行後自動退出**：所有任務結束後，Discord Bot 會自動斷開連線並退出程式，非常適合搭配排程（如 Cron）常駐執行。

---

## 📂 專案檔案結構

- `main.py`：整合主程式，負責 RSS 抓取、排重、摘要生成與 Discord Bot 發送控制。
- `ai_summarizer.py`：串接 Mistral Large API 的摘要生成模組。
- `db_manager.py`：本地 SQLite 資料庫排重管理器。
- `rss_parser.py`：RSS 新聞網頁與內文解析模組。
- `.env`：環境變數檔案（包含 Discord Token 與 Mistral API key，此檔案不會上傳至 GitHub）。
- `requirements.txt`：Python 依賴套件清單。
- `.gitignore`：排除臨時檔案、環境變數與 `news.db` 資料庫上傳。

---

## 🛠 安裝與設定說明

### 1. 安裝依賴套件

在 WSL (Ubuntu) 環境中，於專案目錄下執行：

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數 (`.env`)

請在專案目錄下建立 `.env` 檔案（或編輯已存在的檔案），並填入您的 Token 與 API key：

```env
Discord=您的_Discord_Bot_Token
Mistral=您的_Mistral_API_Key
```

*注意：本專案已將 `.env` 與 `news.db` 加入 `.gitignore` 中，確保您的敏感憑證與本地資料庫不會被上傳。*

---

## 🚀 執行專案

在 WSL 終端機中，執行以下指令以啟動程式：

```bash
python3 main.py
```

### 自動化排程設定 (Cron)

若您希望系統每小時自動偵測並發送新新聞，可透過 Linux 的 `crontab` 進行排程：

1. 開啟排程編輯器：
   ```bash
   crontab -e
   ```
2. 在最下方加入以下設定（請依您的環境修改專案路徑）：
   ```bash
   0 * * * * cd /home/leo/ShanLiao && python3 main.py >> cron.log 2>&1
   ```
