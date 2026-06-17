import os
import asyncio
import discord
from dotenv import load_dotenv
from datetime import datetime
import rss_parser
import db_manager
import ai_summarizer
import title_transformer

# 載入環境變數
load_dotenv()

TARGET_CHANNEL_ID = 1516009893616681043  # Discord 目標頻道 ID
DISCORD_TOKEN = os.getenv("Discord")
DISCORD_MAX_LENGTH = 1950  # Discord 單條訊息字數上限設定為 1950

class NewsBotClient(discord.Client):
    def __init__(self, final_message, prepared_items, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.final_message = final_message
        self.prepared_items = prepared_items

    async def on_ready(self):
        print(f"[Discord Bot] 機器人已成功登入: {self.user}")
        channel = self.get_channel(TARGET_CHANNEL_ID)
        
        if not channel:
            print(f"[Discord Bot] 錯誤: 找不到指定的頻道 {TARGET_CHANNEL_ID}")
            await self.close()
            return

        print(f"[Discord Bot] 正在發送合併後的快報訊息 (共 {len(self.prepared_items)} 篇報導)...")
        
        try:
            # 單次發送所有新聞打包後的訊息
            await channel.send(self.final_message)
            print("[Discord Bot] 快報發送成功！")
            
            # 發送成功後，才將這些已成功發送的新聞寫入資料庫
            print("[Discord Bot] 正在將已發送新聞寫入資料庫做排重...")
            for news in self.prepared_items:
                db_manager.insert_news(news["original_title"], news["link"], news["summary"], news["updated"])
                
        except Exception as e:
            print(f"[Discord Bot] 發送快報訊息失敗: {e}")

        print("[Discord Bot] 正在關閉機器人連線...")
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
    
    # 4. 生成快報大標題 (根據執行時間決定)
    now = datetime.now()
    date_str = now.strftime("%Y/%m/%d")
    hour = now.hour
    
    if 5 <= hour < 12:
        report_name = "晨間快報"
    elif 12 <= hour < 14:
        report_name = "午間快報"
    elif 14 <= hour < 18:
        report_name = "下午快報"
    elif 18 <= hour < 24:
        report_name = "晚間快報"
    else:
        report_name = "深夜快報"
        
    header = f"# 📅 {date_str} ｜ {report_name}\n\n"
    
    # 5. 處理新聞並進行字數長度控制
    prepared_items = []
    
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
            
        # B. 先透過 Mistral 生成摘要 (內建 Rate Limit 與 429 退避重試機制)
        # 因為黃山料標題轉換 Prompt 需要新聞摘要作為上下文輸入
        summary = ai_summarizer.generate_summary(title, body_content)
        
        # C. 透過 Ollama 本地 Qwen3 模型進行特殊口吻標題轉換 (傳入標題與生成的摘要)
        transformed_title = title_transformer.transform_title(title, summary)
        print(f"[Main] 標題轉換成功 -> 原標題: {title} | 新標題: {transformed_title}")
        
        # D. 格式化為精簡版面
        category_text = category if category else "一般新聞"
        formatted_time = news["updated"].replace('T', ' ').split('+')[0] if news["updated"] else "未知時間"
        
        item_md = (
            f"### 📰 **{transformed_title}**\n"
            f"* 原始標題：{title}\n"
            f"* 分類：`{category_text}` ｜ 連結：<{link}> ｜ 時間：`{formatted_time}`\n"
            f"* **AI 摘要**：{summary}\n\n"
        )
        
        # E. 計算加上這一篇後是否會超出 Discord 字數上限
        current_md_list = [item["md"] for item in prepared_items]
        test_message = header + "".join(current_md_list) + item_md
        
        if len(test_message) > DISCORD_MAX_LENGTH:
            print(f"\n[Main] 警告: 加上此篇報導後總字數為 {len(test_message)}，超出了 Discord 的 {DISCORD_MAX_LENGTH} 字上限限制！")
            print(f"[Main] 將此篇《{title}》以及後續所有未處理報導挪至下一次發送。")
            break  # 終止處理後續新聞，保留給下次執行
            
        # F. 未超出長度，加入準備發送列表
        prepared_items.append({
            "md": item_md,
            "original_title": title,
            "link": link,
            "summary": summary,
            "updated": news["updated"]
        })
        
    # 6. 組裝 final_message 並啟動 Discord Bot
    if prepared_items:
        final_message = header + "".join(item["md"] for item in prepared_items)
        print(f"\n[Main] 合併後快報總字數：{len(final_message)} 字元")
        print("[Main] 正在啟動 Discord 機器人合併發送...")
        
        intents = discord.Intents.default()
        intents.message_content = True
        
        client = NewsBotClient(final_message=final_message, prepared_items=prepared_items, intents=intents)
        
        try:
            await client.start(DISCORD_TOKEN)
        except Exception as e:
            print(f"[Main] Discord 機器人執行出錯: {e}")
    else:
        print("\n[Main] 沒有可供發送的新聞項目。")
            
    print("\n[Main] 任務執行結束。")

if __name__ == "__main__":
    asyncio.run(main())
