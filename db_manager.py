import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.db")

def get_db_connection():
    """
    獲取資料庫連接，並設定 row_factory 方便讀取字典格式的資料
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    初始化資料庫，如果 news 資料表不存在則建立
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            summary TEXT,
            published_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print(f"[DB Manager] 資料庫初始化成功，路徑: {DB_PATH}")

def is_news_exists(link):
    """
    檢查指定連結的新聞是否已存在於資料庫中
    """
    if not link:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM news WHERE link = ?", (link.strip(),))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def insert_news(title, link, summary, published_at):
    """
    將新處理的新聞存入資料庫
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO news (title, link, summary, published_at) VALUES (?, ?, ?, ?)",
            (title.strip(), link.strip(), summary.strip() if summary else None, published_at.strip() if published_at else None)
        )
        conn.commit()
        print(f"[DB Manager] 成功寫入新聞至資料庫: {title}")
        return True
    except sqlite3.IntegrityError:
        print(f"[DB Manager] 新聞已存在，寫入跳過: {title}")
        return False
    except Exception as e:
        print(f"[DB Manager] 寫入資料庫時發生錯誤: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    # 測試程式
    test_link = "https://example.com/test-news-123"
    print(f"測試新聞是否存在: {is_news_exists(test_link)}")
    insert_news("測試新聞標題", test_link, "這是測試摘要", "2026-06-16T17:00:00Z")
    print(f"再次測試新聞是否存在: {is_news_exists(test_link)}")
    
    # 清理測試資料
    conn = get_db_connection()
    conn.execute("DELETE FROM news WHERE link = ?", (test_link,))
    conn.commit()
    conn.close()
    print("測試清理完成。")
