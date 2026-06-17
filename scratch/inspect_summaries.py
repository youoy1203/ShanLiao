import json
import os
import re

path = "data/news_with_summary.jsonl"
if not os.path.exists(path):
    print("news_with_summary.jsonl does not exist")
    exit()

print("--- 隨機抽樣 15 筆摘要內容 ---")
count = 0
ai_prefaces = [
    "這篇新聞", "以下是", "摘要如下", "主要報導", "核心事件", "本篇報導", "本文主要", "這項消息", "此篇新聞"
]
stats = {
    "contains_markdown": 0,
    "contains_ai_preface": 0,
    "contains_newlines": 0,
    "too_short": 0,
    "too_long": 0,
    "contains_quotes": 0
}

with open(path, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            summary = data.get("summary", "")
            article_id = data.get("id")
            
            # 抽樣印出
            if count < 15:
                print(f"ID {article_id}: {repr(summary)}")
                count += 1
                
            # 統計特徵
            if "**" in summary or "###" in summary or "- " in summary:
                stats["contains_markdown"] += 1
            if any(p in summary for p in ai_prefaces):
                stats["contains_ai_preface"] += 1
            if "\n" in summary:
                stats["contains_newlines"] += 1
            if len(summary) < 50:
                stats["too_short"] += 1
            if len(summary) > 250:
                stats["too_long"] += 1
            if summary.startswith('"') or summary.startswith('「') or summary.startswith('『'):
                stats["contains_quotes"] += 1
        except Exception as e:
            pass

print("\n--- 統計特徵分析 ---")
print(f"總分析筆數: {stats['contains_markdown'] + stats['contains_ai_preface'] + stats['contains_newlines'] + stats['too_short'] + stats['too_long'] + stats['contains_quotes']}")
for k, v in stats.items():
    print(f"  {k}: {v} 筆")
