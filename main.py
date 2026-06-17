import os
import asyncio
import discord
from dotenv import load_dotenv
import rss_parser
import db_manager
import ai_summarizer
import title_transformer

# 載入環境變數
load_dotenv()

TARGET_CHANNEL_ID = 1516390944231002173  # Discord 目標頻道 ID
DISCORD_TOKEN = os.getenv("Discord")

class NewsBotClient(discord.Client):
    def __init__(self, news_to_send, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.news_to_send = news_to_send

    async def on_ready(self):
        print(f"[Discord Bot] 機器人已成功登入: {self.user}")
        channel = self.get_channel(TARGET_CHANNEL_ID)
        
        if not channel:
            print(f"[Discord Bot] 錯誤: 找不到指定的頻道 {TARGET_CHANNEL_ID}")
            await self.close()
            return

        print(f"[Discord Bot] 開始依序發送 {len(self.news_to_send)} 篇新新聞摘要 (雙模型協作，從較早的新聞開始)...")
        
        for news in self.news_to_send:
            title = news["title"]                  # 轉換後的標題
            original_title = news["original_title"]  # 原始標題
            link = news["link"]
            summary = news["summary"]
            updated = news["updated"]
            category = news["category"]
            
            # 整理時間格式
            formatted_time = updated.replace('T', ' ').split('+')[0] if updated else "未知時間"
            category_text = category if category else "一般新聞"
            
            # 訊息排版：主標題採用轉換後口吻，並新增一欄顯示原始標題以便對照
            message_content = (
                f"## 📰 **{title}**\n\n"
                f"📝 **原始標題**：{original_title}\n"
                f"🏷️ **新聞分類**：`{category_text}`\n"
                f"🔗 **新聞連結**：<{link}>\n"
                f"⏰ **發布時間**：`{formatted_time}`\n\n"
                f"✍️ **AI 內容摘要**：\n"
                f"> {summary}\n\n"
                f"---"
            )
            
            try:
                print(f"[Discord Bot] 正在發送《{title}》...")
                await channel.send(message_content)
                
                # 發送成功後，將原始新聞標題與連結存入資料庫做排重
                db_manager.insert_news(original_title, link, summary, updated)
                
                # 稍微等待 1.5 秒，避免 Discord 頻率限制
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[Discord Bot] 發送新聞《{title}》失敗: {e}")

        print("[Discord Bot] 所有新新聞發送並記錄完成，正在關閉機器人連線...")
        await self.close()

async def main():
    # 1. 初始化資料庫
    db_manager.init_db()
    
    # 2. 抓取 RSS 的所有新聞
    print("[Main] 正在抓取公視新聞 RSS feed...")
    all_news = rss_parser.fetch_all_news()
    if not all_news:
        print("[Main] 錯誤: 無法取得 RSS 新聞。")
        return
        
    print(f"[Main] 成功取得 {len(all_news)} 篇新聞，正在進行資料庫比對...")
    
    # 3. 過濾出尚未存在於資料庫中的新聞
    new_news_list = []
    for news in all_news:
        if not db_manager.is_news_exists(news["link"]):
            new_news_list.append(news)
            
    if not new_news_list:
        print("[Main] 檢查完畢：沒有新的新聞需要處理。")
        return
        
    print(f"[Main] 發現 {len(new_news_list)} 篇未處理的新新聞。")
    
    # 時間較舊的新聞先被處理與發布
    new_news_list.reverse()
    
    # 4. 對每篇新新聞進行雙模型協作處理 (Mistral Large 摘要 + Ollama Qwen3 標題轉換)
    prepared_news = []
    for idx, news in enumerate(new_news_list, 1):
        title = news["title"]
        link = news["link"]
        print(f"\n[Main] ({idx}/{len(new_news_list)}) 正在處理: {title}")
        
        # A. 抓取詳細網頁內文與分類資訊
        details = rss_parser.fetch_article_content(link)
        body_content = ""
        category = ""
        
        if details:
            body_content = details.get("article_body") if details.get("article_body") else news["summary"]
            category = details.get("category", "")
        else:
            body_content = news["summary"]
            
        # B. 透過 Ollama 本地 Qwen3 模型進行特殊口吻標題轉換
        transformed_title = title_transformer.transform_title(title)
        print(f"[Main] 標題轉換成功 -> 原標題: {title} | 新標題: {transformed_title}")
        
        # C. 透過 Mistral 生成摘要 (內建 Rate Limit 延遲 15 秒)
        summary = ai_summarizer.generate_summary(title, body_content)
        
        prepared_news.append({
            "original_title": title,
            "title": transformed_title,
            "link": link,
            "summary": summary,
            "updated": news["updated"],
            "category": category
        })
        
    # 5. 啟動 Discord Bot 發送新新聞摘要
    if prepared_news:
        print(f"\n[Main] 正在啟動 Discord 機器人發送 {len(prepared_news)} 篇新新聞...")
        intents = discord.Intents.default()
        intents.message_content = True
        
        client = NewsBotClient(news_to_send=prepared_news, intents=intents)
        
        try:
            await client.start(DISCORD_TOKEN)
        except Exception as e:
            print(f"[Main] Discord 機器人執行出錯: {e}")
            
    print("\n[Main] 任務執行結束。")

if __name__ == "__main__":
    asyncio.run(main())
