import os
import json
import re

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RAW_NEWS_PATH = os.path.join(DATA_DIR, "raw_news.jsonl")
TEMP_NEWS_PATH = os.path.join(DATA_DIR, "raw_news_temp.jsonl")

BLACK_LIST_CATEGORIES = {
    "台語新聞", "英語新聞", "印尼語新聞", "越南語新聞", "泰語新聞", 
    "Hakka", "English", "Vietnam", "Thai", "Indonesian"
}

def is_traditional_chinese_news(headline, article_body, category):
    if category in BLACK_LIST_CATEGORIES:
        return False
        
    text_to_check = (headline or "") + (article_body or "")
    if not text_to_check.strip():
        return False
        
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text_to_check)
    non_space_text = re.sub(r'\s+', '', text_to_check)
    if not non_space_text:
        return False
        
    ratio = len(chinese_chars) / len(non_space_text)
    if ratio < 0.35:
        return False
        
    thai_chars = re.findall(r'[\u0e00-\u0e7f]', text_to_check)
    if len(thai_chars) > 5:
        return False
        
    return True

def main():
    if not os.path.exists(RAW_NEWS_PATH):
        print(f"錯誤: 找不到原始新聞檔案 {RAW_NEWS_PATH}")
        return
        
    original_count = 0
    valid_count = 0
    skipped_articles = []
    
    with open(RAW_NEWS_PATH, "r", encoding="utf-8") as f_in:
        with open(TEMP_NEWS_PATH, "w", encoding="utf-8") as f_out:
            for line in f_in:
                if line.strip():
                    original_count += 1
                    try:
                        data = json.loads(line)
                        headline = data.get("headline", "")
                        body = data.get("article_body", "")
                        category = data.get("category", "")
                        
                        if is_traditional_chinese_news(headline, body, category):
                            # 在此處進行標題尾綴清理 (｜ 公視新聞網 PNN)
                            if headline:
                                data["headline"] = re.sub(r'\s*[|｜]\s*公視新聞網\s*PNN\s*$', '', headline).strip()
                            f_out.write(json.dumps(data, ensure_ascii=False) + "\n")
                            valid_count += 1
                        else:
                            skipped_articles.append((data.get("id"), headline, category))
                    except Exception as e:
                        print(f"解析錯誤: {e}")
                        
    if os.path.exists(TEMP_NEWS_PATH):
        if os.path.exists(RAW_NEWS_PATH):
            os.remove(RAW_NEWS_PATH)
        os.rename(TEMP_NEWS_PATH, RAW_NEWS_PATH)
        
    print(f"清理完畢！")
    print(f"- 原始文章總數: {original_count} 筆")
    print(f"- 保留繁中文章 (已自動移除標題尾綴): {valid_count} 筆")
    print(f"- 剔除非繁中文章: {original_count - valid_count} 筆")
    
    if skipped_articles:
        print(f"\n已成功將剔除的 {len(skipped_articles)} 筆非繁中報導自 {RAW_NEWS_PATH} 中清除。")

if __name__ == "__main__":
    main()
