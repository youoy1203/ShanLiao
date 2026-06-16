import discord
import os
from dotenv import load_dotenv
from rss_parser import fetch_latest_news, fetch_article_content

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

TARGET_CHANNEL_ID = 1516009893616681043  # 目標頻道 ID

@client.event
async def on_ready():
    print('機器人已成功登入: {0.user}'.format(client))
    
    # 取得頻道物件
    channel = client.get_channel(TARGET_CHANNEL_ID)
    
    if not channel:
        print(f"錯誤: 找不到指定的頻道 {TARGET_CHANNEL_ID}。")
        print("請確認頻道 ID 是否正確，且機器人已被加入該伺服器並擁有發送訊息的權限。")
        await client.close()
        return

    print("開始自公視新聞網抓取 RSS feed...")
    news = fetch_latest_news()
    if not news:
        print("錯誤: 無法取得 RSS 新聞。")
        await client.close()
        return
        
    print(f"成功取得最新新聞標題: {news['title']}")
    print(f"新聞連結: {news['link']}")
    
    print("正在請求新聞網頁以讀取內文...")
    details = fetch_article_content(news['link'])
    
    # 準備 Embed 排版
    embed = discord.Embed(
        title=news['title'],
        url=news['link'],
        color=discord.Color.from_rgb(0, 114, 188)  # 公視經典藍色調
    )
    
    # 設定新聞內文 (若有詳細內文就用內文，否則用 RSS 摘要)
    body_content = ""
    if details and details['article_body']:
        body_content = details['article_body']
    else:
        body_content = news['summary']
        
    # 防止長度超出 Discord Embed 4096 字元限制
    if len(body_content) > 3000:
        body_content = body_content[:3000] + "\n\n...(內文字數過多已自動截斷，請點擊上方標題連結閱讀全文)..."
        
    embed.description = body_content
    
    # 添加作者與分類資訊
    if details:
        if details['author']:
            embed.add_field(name="作者", value=details['author'], inline=True)
        if details['category']:
            embed.add_field(name="分類", value=details['category'], inline=True)
            
    # 添加發布時間
    if news['updated']:
        # 簡單整理 ISO 8601 時間格式為易讀格式
        formatted_time = news['updated'].replace('T', ' ').split('+')[0]
        embed.add_field(name="發布時間", value=formatted_time, inline=False)
        
    embed.set_footer(text="來源: 公視新聞網 PNN | 自動發布機器人")
    
    try:
        print("正在發送新聞至 Discord 頻道...")
        await channel.send(embed=embed)
        print("新聞發送成功！")
    except Exception as e:
        print(f"錯誤: 發送訊息失敗，原因: {e}")
        
    # -------------------------------------------------------------
    # 測試提醒：為了方便您此次的一次性測試，發送成功後機器人會自動關閉連線。
    # 若您未來需要讓機器人常駐在線上接收 PTT/$hello 指令，請註解掉下面這行。
    # -------------------------------------------------------------
    print("測試任務完成，正在關閉機器人連線以退出程式...")
    await client.close()

@client.event
async def on_message(message):
    # 避免自己回應自己
    if message.author == client.user:
        return

    if message.content.startswith('$hello'):
        await message.channel.send('Hello!')

# 啟動機器人
client.run(os.getenv('Discord'))
