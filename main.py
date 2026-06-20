import os
import asyncio
import discord
import logging
import sys
from dotenv import load_dotenv
from datetime import datetime
import rss_parser
import db_manager
import ai_summarizer
import title_transformer

# ==================== 配置 Logging 帶有時間戳記 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]  # 確保 cron 能正確捕捉 stdout
)
# ==================================================================

# 載入環境變數
load_dotenv()

TARGET_CHANNEL_ID = os.getenv("channel_id")  # Discord 目標頻道 ID
# 如果環境變數讀出來是字串，轉換成 int 供 Discord API 使用
if TARGET_CHANNEL_ID:
    TARGET_CHANNEL_ID = int(TARGET_CHANNEL_ID)
DISCORD_TOKEN = os.getenv("Discord")

class NewsBotClient(discord.Client):
    def __init__(self, header, news_to_send, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.header = header
        self.news_to_send = news_to_send

    async def on_ready(self):
        logging.info(f"[Discord Bot] 機器人已成功登入: {self.user}")
        channel = self.get_channel(TARGET_CHANNEL_ID)
        
        if not channel:
            logging.error(f"[Discord Bot] 錯誤: 找不到指定的頻道 {TARGET_CHANNEL_ID}")
            await self.close()
            return

        try:
            # 1. 先單獨發送一次當前日期與屬於什麼時段的新聞大標題
            logging.info(f"[Discord Bot] 正在發送大標題: {self.header.strip()}")
            await channel.send(self.header)
            await asyncio.sleep(1.5)
            
            logging.info(f"[Discord Bot] 開始依序發送 {len(self.news_to_send)} 篇獨立新聞訊息...")
            
            # 2. 每一篇新聞獨立發送一則訊息，並用空格/空行間隔每一則訊息
            for idx, news in enumerate(self.news_to_send):
                title = news["title"]
                original_title = news["original_title"]
                link = news["link"]
                summary = news["summary"]
                updated = news["updated"]
                category = news["category"]
                
                # 整理時間與分類
                formatted_time = updated.replace('T', ' ').split('+')[0] if updated else "未知時間"
                category_text = category if category else "一般新聞"
                
                # 精簡版面 Markdown
                message_content = (
                    f"### 📰 **{title}**\n"
                    f"* 原始標題：{original_title}\n"
                    f"* 分類：`{category_text}` ｜ 連結：<{link}> ｜ 時間：`{formatted_time}`\n"
                    f"* **摘要**：{summary}"
                )
                
                logging.info(f"[Discord Bot] 正在發送 ({idx + 1}/{len(self.news_to_send)}): 《{title}》...")
                await channel.send(message_content)
                
                # 發送成功後立即寫入資料庫，確保排重安全
                db_manager.insert_news(original_title, link, summary, updated)
                await asyncio.sleep(1.5)
                
                # 用空格 (零寬度空格字元 \u200b) 間隔每一則獨立新聞訊息，製造乾淨的間距
                if idx < len(self.news_to_send) - 1:
                    await channel.send("\u200b")
                    await asyncio.sleep(1.5)
                    
            logging.info("[Discord Bot] 所有新聞獨立發送與資料庫寫入完成！")
            
        except Exception as e:
            logging.error(f"[Discord Bot] 執行發送過程出錯: {e}")

        logging.info("[Discord Bot] 正在關閉機器人連線...")
        await self.close()

async def main():
    # 1. 初始化資料庫
    db_manager.init_db()
    
    # 2. 抓取 RSS 的所有新聞
    logging.info("[Main] 正在抓取公視新聞 RSS feed...")
    all_news = rss_parser.fetch_all_news()
    if not all_news:
        logging.error("[Main] 錯誤: 無法取得 RSS 新聞。")
        return
        
    logging.info(f"[Main] 成功取得 {len(all_news)} 篇新聞，正在進行資料庫比對...")
    
    # 3. 過濾出尚未存在於資料庫中的新聞
    new_news_list = []
    for news in all_news:
        if not db_manager.is_news_exists(news["link"]):
            new_news_list.append(news)
            
    if not new_news_list:
        logging.info("[Main] 檢查完畢：沒有新的新聞需要處理。")
        return
        
    logging.info(f"[Main] 發現 {len(new_news_list)} 篇未處理的新新聞。")
    
    # 時間較舊的新聞先被處理與發布
    new_news_list.reverse()
    
    # 4. 生成快報大標題 (根據執行時間決定)
    now = datetime.now()
    date_str = now.strftime("%Y/%m/%d")
    hour = now.hour
    
    # 依據樹莓派排程啟動時間 (08:00, 12:00, 18:00, 23:00) 決定新聞時段大標題
    if 5 <= hour < 11:
        report_name = "晨間新聞"    # 早上 8 點啟動落在這 (05:00 - 10:59)
    elif 11 <= hour < 17:
        report_name = "午間新聞"    # 中午 12 點啟動落在這 (11:00 - 16:59)
    elif 17 <= hour < 22:
        report_name = "晚間新聞"    # 晚上 6 點 (18:00) 啟動落在這 (17:00 - 21:59)
    else:
        report_name = "深夜新聞"    # 晚上 11 點 (23:00) 啟動落在這 (22:00 - 04:59)
        
    header = f"# 📅 {date_str} ｜ {report_name}"
    
    # 5. 處理所有新新聞，呼叫雙模型處理
    prepared_news = []
    
    # 預載/暖機 Ollama 模型，防止首篇新聞因模型載入過慢而處理超時
    if new_news_list:
        title_transformer.warm_up()
        
    for idx, news in enumerate(new_news_list, 1):
        title = news["title"]
        link = news["link"]
        logging.info(f"[Main] ({idx}/{len(new_news_list)}) 正在處理: {title}")
        
        # A. 抓取詳細網頁內文與分類資訊
        details = rss_parser.fetch_article_content(link)
        body_content = ""
        category = ""
        
        if details:
            body_content = details.get("article_body") if details.get("article_body") else news["summary"]
            category = details.get("category", "")
        else:
            body_content = news["summary"]
            
        # B. 透過 Mistral 生成摘要 (內建 Rate Limit 與 429 退避重試機制)
        summary = ai_summarizer.generate_summary(title, body_content)
        
        # C. 透過 Ollama 本地 shanliao-qwen 模型進行特殊口吻標題轉換
        transformed_title = title_transformer.transform_title(title, summary)
        logging.info(f"[Main] 標題轉換成功 -> 原標題: {title} | 新標題: {transformed_title}")
        
        prepared_news.append({
            "original_title": title,
            "title": transformed_title,
            "link": link,
            "summary": summary,
            "updated": news["updated"],
            "category": category
        })
        
    # 6. 啟動 Discord Bot 發送新新聞摘要
    if prepared_news:
        logging.info(f"[Main] 正在啟動 Discord 機器人發送 {len(prepared_news)} 篇新新聞...")
        intents = discord.Intents.default()
        intents.message_content = True
        
        client = NewsBotClient(header=header, news_to_send=prepared_news, intents=intents)
        
        try:
            await client.start(DISCORD_TOKEN)
        except Exception as e:
            logging.error(f"[Main] Discord 機器人執行出錯: {e}")
            
    logging.info("[Main] 任務執行結束。")

if __name__ == "__main__":
    asyncio.run(main())