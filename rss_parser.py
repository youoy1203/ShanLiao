import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import json
import re
import urllib3

# 停用 SSL 未經驗證的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def fetch_latest_news(rss_url="https://news.pts.org.tw/xml/newsfeed.xml"):
    """
    抓取 RSS Feed，並返回第一篇新聞的標題、連結、發布時間、摘要
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # 加上 verify=False 以跳過 SSL 憑證驗證
        response = requests.get(rss_url, headers=headers, verify=False)
        response.raise_for_status()
        xml_content = response.content
        
        # 解析 Atom 格式 XML
        root = ET.fromstring(xml_content)
        # Atom namespaces
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        first_entry = root.find('atom:entry', ns)
        if first_entry is None:
            return None
            
        title_elem = first_entry.find('atom:title', ns)
        link_elem = first_entry.find('atom:link', ns)
        summary_elem = first_entry.find('atom:summary', ns)
        updated_elem = first_entry.find('atom:updated', ns)
        
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else "無標題"
        link = link_elem.attrib.get('href', '').strip() if link_elem is not None else ""
        summary = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""
        updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""
        
        # 簡單過濾 summary 裡的 HTML tag (如果有)
        if summary:
            summary = BeautifulSoup(summary, 'html.parser').get_text()
            
        return {
            "title": title,
            "link": link,
            "summary": summary,
            "updated": updated
        }
        
    except Exception as e:
        print(f"抓取 RSS 發生錯誤: {e}")
        return None

def fetch_all_news(rss_url="https://news.pts.org.tw/xml/newsfeed.xml"):
    """
    抓取 RSS Feed，並返回所有新聞的列表 (每個元素包含標題、連結、發布時間、摘要)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(rss_url, headers=headers, verify=False)
        response.raise_for_status()
        xml_content = response.content
        
        # 解析 Atom 格式 XML
        root = ET.fromstring(xml_content)
        # Atom namespaces
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        entries = root.findall('atom:entry', ns)
        news_list = []
        
        for entry in entries:
            title_elem = entry.find('atom:title', ns)
            link_elem = entry.find('atom:link', ns)
            summary_elem = entry.find('atom:summary', ns)
            updated_elem = entry.find('atom:updated', ns)
            
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "無標題"
            link = link_elem.attrib.get('href', '').strip() if link_elem is not None else ""
            summary = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""
            updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""
            
            # 簡單過濾 summary 裡的 HTML tag (如果有)
            if summary:
                summary = BeautifulSoup(summary, 'html.parser').get_text()
                
            news_list.append({
                "title": title,
                "link": link,
                "summary": summary,
                "updated": updated
            })
            
        return news_list
        
    except Exception as e:
        print(f"抓取 RSS 列表發生錯誤: {e}")
        return []

def fetch_article_content(article_url):
    """
    抓取文章連結網頁，解析 JSON-LD (NewsArticle) 以取得內文、作者與分類
    """
    if not article_url:
        return None
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # 加上 verify=False 以跳過 SSL 憑證驗證
        response = requests.get(article_url, headers=headers, verify=False)
        response.raise_for_status()
        html_content = response.text
        
        soup = BeautifulSoup(html_content, 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')
        
        article_body = ""
        author = ""
        category = ""
        
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string.strip())
                
                # 輔助處理函式：從 NewsArticle dict 提取欄位
                def extract_info(item):
                    nonlocal article_body, author, category
                    if item.get('@type') == 'NewsArticle':
                        article_body = item.get('articleBody', '').strip()
                        
                        # 處理 author 欄位 (可能是 dict 或 list of dict)
                        auth_data = item.get('author')
                        if isinstance(auth_data, list) and len(auth_data) > 0:
                            author = auth_data[0].get('name', '').strip()
                        elif isinstance(auth_data, dict):
                            author = auth_data.get('name', '').strip()
                            
                        # 處理 articleSection 欄位 (可能是 list 或 str)
                        sec_data = item.get('articleSection')
                        if isinstance(sec_data, list) and len(sec_data) > 0:
                            category = sec_data[0].strip()
                        elif isinstance(sec_data, str):
                            category = sec_data.strip()
                        return True
                    return False

                # 判斷 JSON-LD 是 List 還是 Dict
                if isinstance(data, list):
                    for item in data:
                        if extract_info(item):
                            break
                elif isinstance(data, dict):
                    extract_info(data)
                    
                if article_body:
                    break  # 已經找到新聞內容，退出迴圈
                    
            except (json.JSONDecodeError, TypeError, KeyError) as je:
                continue
        
        # 若 JSON-LD 沒抓到，嘗試用網頁常見的 article class 當備份 (針對非 PTS 或是未來改版)
        if not article_body:
            # 嘗試找 <article>
            article_tag = soup.find('article')
            if article_tag:
                article_body = article_tag.get_text(separator='\n').strip()
        
        return {
            "article_body": article_body,
            "author": author,
            "category": category
        }
        
    except Exception as e:
        print(f"抓取文章內文發生錯誤 ({article_url}): {e}")
        return None

if __name__ == "__main__":
    print("正在測試抓取 RSS...")
    news = fetch_latest_news()
    if news:
        print("\n--- RSS 第一篇新聞資訊 ---")
        print(f"標題: {news['title']}")
        print(f"連結: {news['link']}")
        print(f"時間: {news['updated']}")
        print(f"摘要: {news['summary'][:100]}...")
        
        print("\n正在抓取內文...")
        details = fetch_article_content(news['link'])
        if details:
            print("\n--- 網頁詳細內文 ---")
            print(f"作者: {details['author']}")
            print(f"分類: {details['category']}")
            print(f"內文長度: {len(details['article_body'])} 字")
            print(f"內文開頭: {details['article_body'][:200]}...")
        else:
            print("無法抓取詳細內文。")
    else:
        print("無法抓取 RSS 新聞。")
