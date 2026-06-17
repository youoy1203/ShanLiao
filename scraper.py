import os
import re
import json
import time
import random
import requests
import urllib3
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from threading import Lock
import sys
import io

# 強制設定輸出為 UTF-8，解決 Windows 系統日誌亂碼問題
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 停用 SSL 未經驗證的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DATA_DIR = "data"
RAW_NEWS_PATH = os.path.join(DATA_DIR, "raw_news.jsonl")

# 線程安全的寫入鎖
file_lock = Lock()

# 非繁體中文分類黑名單
BLACK_LIST_CATEGORIES = {
    "台語新聞", "英語新聞", "印尼語新聞", "越南語新聞", "泰語新聞", 
    "Hakka", "English", "Vietnam", "Thai", "Indonesian"
}

def is_traditional_chinese_news(headline, article_body, category):
    """檢查新聞是否為一般繁體中文報導"""
    # 1. 分類黑名單過濾
    if category in BLACK_LIST_CATEGORIES:
        return False
        
    # 2. 內文與標題中文字元比例檢測
    text_to_check = (headline or "") + (article_body or "")
    if not text_to_check.strip():
        return False
        
    # 匹配中文字元 (CJK 統一漢字)
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text_to_check)
    # 去除空白字元後的總長度
    non_space_text = re.sub(r'\s+', '', text_to_check)
    if not non_space_text:
        return False
        
    ratio = len(chinese_chars) / len(non_space_text)
    if ratio < 0.35:
        return False
        
    # 3. 泰文特殊字元過濾 (泰文 Unicode 區間: \u0e00-\u0e7f)
    thai_chars = re.findall(r'[\u0e00-\u0e7f]', text_to_check)
    if len(thai_chars) > 5:
        return False
        
    return True

def get_latest_rss_id():
    """從 RSS 獲取最新的文章 ID"""
    rss_url = "https://news.pts.org.tw/xml/newsfeed.xml"
    try:
        response = requests.get(rss_url, headers=HEADERS, verify=False, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('atom:entry', ns):
                link_elem = entry.find('atom:link', ns)
                if link_elem is not None:
                    href = link_elem.attrib.get('href', '').strip()
                    match = re.search(r'article/(\d+)', href)
                    if match:
                        return int(match.group(1))
        elif response.status_code == 429:
            print("RSS 請求觸發 429 限流")
    except Exception as e:
        print(f"無法從 RSS 獲取最新 ID: {e}")
    return None

def extract_news_article(html_content):
    """從 HTML 中解析 JSON-LD NewsArticle"""
    soup = BeautifulSoup(html_content, 'html.parser')
    scripts = soup.find_all('script', type='application/ld+json')
    
    article_body = ""
    headline = ""
    author = ""
    category = ""
    date_published = ""
    description = ""
    
    for script in scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string.strip())
            
            def extract_info(item):
                nonlocal article_body, headline, author, category, date_published, description
                if item.get('@type') == 'NewsArticle':
                    article_body = item.get('articleBody', '').strip()
                    headline = item.get('headline', '').strip()
                    date_published = item.get('datePublished', '').strip()
                    description = item.get('description', '').strip()
                    
                    # 處理 author
                    auth_data = item.get('author')
                    if isinstance(auth_data, list) and len(auth_data) > 0:
                        author = auth_data[0].get('name', '').strip()
                    elif isinstance(auth_data, dict):
                        author = auth_data.get('name', '').strip()
                        
                    # 處理 category
                    sec_data = item.get('articleSection')
                    if isinstance(sec_data, list) and len(sec_data) > 0:
                        category = sec_data[0].strip()
                    elif isinstance(sec_data, str):
                        category = sec_data.strip()
                    return True
                return False

            if isinstance(data, list):
                for item in data:
                    if extract_info(item):
                        break
            elif isinstance(data, dict):
                extract_info(data)
                
            if article_body and headline:
                break
                
        except Exception:
            continue
            
    # 備份讀取方式
    if not article_body:
        article_tag = soup.find('article')
        if article_tag:
            article_body = article_tag.get_text(separator='\n').strip()
    if not headline:
        title_tag = soup.find('title')
        if title_tag:
            headline = title_tag.get_text().strip()

    # 自動清理標題末尾的「 ｜ 公視新聞網 PNN」或「 | 公視新聞網 PNN」
    if headline:
        headline = re.sub(r'\s*[|｜]\s*公視新聞網\s*PNN\s*$', '', headline).strip()

    return {
        "headline": headline,
        "article_body": article_body,
        "description": description,
        "author": author,
        "category": category,
        "date_published": date_published
    }

def download_article(article_id):
    """下載單篇文章並解析"""
    url = f"https://news.pts.org.tw/article/{article_id}"
    try:
        response = requests.get(url, headers=HEADERS, verify=False, timeout=10)
        
        if response.status_code == 200:
            article_info = extract_news_article(response.text)
            if article_info["headline"] and article_info["article_body"]:
                # 檢查是否為繁體中文報導
                if is_traditional_chinese_news(article_info["headline"], article_info["article_body"], article_info["category"]):
                    article_info["id"] = article_id
                    article_info["url"] = url
                    return {"status": "success", "data": article_info}
                else:
                    return {"status": "skipped_non_tr_chinese"}
            return {"status": "invalid_content"}
            
        elif response.status_code == 404:
            return {"status": "404"}
            
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", 300)
            try:
                retry_after = int(retry_after)
            except:
                retry_after = 300
            return {"status": "429", "retry_after": retry_after}
            
        elif response.status_code in [403, 503]:
            return {"status": "blocked", "code": response.status_code}
            
    except Exception as e:
        return {"status": "error", "message": str(e)}
        
    return {"status": "unknown"}

def load_existing_ids():
    """載入已經下載過的文章 ID"""
    if not os.path.exists(RAW_NEWS_PATH):
        return set()
    
    existing_ids = set()
    try:
        with open(RAW_NEWS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "id" in data:
                            existing_ids.add(int(data["id"]))
                    except:
                        pass
    except Exception as e:
        print(f"讀取既有資料時出錯: {e}")
    return existing_ids

def main(target_count=3000):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    existing_ids = load_existing_ids()
    print(f"已存在之有效新聞筆數: {len(existing_ids)}")
    
    latest_id = get_latest_rss_id()
    if not latest_id:
        latest_id = 813338
        print(f"無法獲取最新 RSS ID，將使用預設 ID: {latest_id}")
    else:
        print(f"最新文章 ID 為: {latest_id}")

    # 從最小的已存 ID 遞減開始抓取
    current_id = latest_id
    valid_count = len(existing_ids)
    
    if existing_ids:
        min_id = min(existing_ids)
        current_id = min_id - 1
        print(f"發現已有資料，將從最小的已存 ID 遞減開始抓取。起始 ID: {current_id}")
        
    print(f"開始抓取，目標有效新聞筆數: {target_count}...")
    print("採用單執行緒 + 隨機延遲 + 429優雅冷卻安全策略。已加入繁中與標題尾綴過濾。")
    
    t0 = time.time()
    
    with open(RAW_NEWS_PATH, "a", encoding="utf-8") as out_file:
        while valid_count < target_count and current_id > 0:
            if current_id in existing_ids:
                current_id -= 1
                continue
                
            result = download_article(current_id)
            
            if result["status"] == "success":
                data = result["data"]
                out_file.write(json.dumps(data, ensure_ascii=False) + "\n")
                out_file.flush()
                existing_ids.add(current_id)
                valid_count += 1
                print(f"[SUCCESS] ID {current_id} 下載成功！目前有效筆數: {valid_count}/{target_count}")
                time.sleep(random.uniform(1.0, 2.0))
                
            elif result["status"] == "skipped_non_tr_chinese":
                time.sleep(random.uniform(0.1, 0.3))
                
            elif result["status"] == "404":
                time.sleep(random.uniform(0.1, 0.3))
                
            elif result["status"] == "429":
                retry_after = result["retry_after"]
                print(f"\n[WARNING 429] 觸發安全防護。需要冷卻 {retry_after} 秒。暫停中...")
                time.sleep(retry_after)
                continue
                
            elif result["status"] == "blocked":
                print(f"\n[BLOCKED] 狀態碼: {result['code']}。可能被 WAF 暫時封鎖，冷卻 180 秒...")
                time.sleep(180)
                continue
                
            elif result["status"] == "error":
                print(f"[ERROR] ID {current_id} 請求失敗: {result['message']}。等待 5 秒後繼續...")
                time.sleep(5)
                
            current_id -= 1
            
            # 定期印出運行時間
            if (current_id % 100 == 0) and valid_count > len(existing_ids):
                elapsed = time.time() - t0
                print(f"-> 已運行 {elapsed:.1f} 秒，目前有效總數: {valid_count} 筆")

    t1 = time.time()
    print(f"抓取結束！共抓取了 {valid_count} 筆有效新聞。總耗時: {t1 - t0:.1f} 秒。")

if __name__ == "__main__":
    import sys
    target = 3000
    if len(sys.argv) > 1:
        try:
            target = int(sys.argv[1])
        except:
            pass
    main(target_count=target)
