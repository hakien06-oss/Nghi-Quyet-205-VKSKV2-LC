import os
import json
import hashlib
from datetime import datetime
from urllib.parse import quote

import requests
import feedparser
from newspaper import Article

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

CACHE_FILE = "radar205_cache.json"

BASE_LOCATIONS = [
    "Lâm Thượng",
    "Lục Yên",
    "Khánh Hòa",
    "Tân Lĩnh",
    "Bảo Ái",
    "Mường Lai",
    "Yên Thành",
    "Thác Bà",
    "Cảm Nhân",
    "Yên Bình",
    "Phúc Lợi"
]

LOCATIONS = []
for loc in BASE_LOCATIONS:
    LOCATIONS.append(loc)
    LOCATIONS.append(f"xã {loc}")

KEYWORDS = [
    "đổ rác","rác thải","ô nhiễm","ô nhiễm môi trường","ô nhiễm nguồn nước",
    "ô nhiễm không khí","đốt rác","xả nước thải","xả thải","nước thải",
    "khai thác khoáng sản","khai thác cát","khai thác sỏi","sạt lở","phá rừng",
    "hủy hoại môi trường","lấn chiếm đất","đất công","hành lang giao thông",
    "hành lang suối","san gạt","đất rừng","tài sản công","thực phẩm bẩn",
    "thuốc giả","thuốc hết hạn","ngộ độc thực phẩm","suất ăn học đường",
    "hàng giả","hàng kém chất lượng","quảng cáo sai sự thật","thu phí trái quy định",
    "xâm hại di tích","phá dỡ di tích","cổ vật","bạo hành trẻ em","bỏ mặc trẻ em",
    "trẻ em khuyết tật","người già neo đơn","mất năng lực hành vi","phụ nữ mang thai",
    "người dân tộc thiểu số","không giấy khai sinh","không được cấp căn cước","hộ tịch"
]

RSS_SOURCES = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://dantri.com.vn/rss/home.rss",
    "https://vietnamnet.vn/rss/home.rss",
    "https://laodong.vn/rss/home.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://nld.com.vn/rss/home.rss"
]

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(cache), f)

sent_cache = load_cache()

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": message[:4000]},
        timeout=20
    )

def make_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def detect_locations(text):
    t = text.lower()
    return list(set([x for x in LOCATIONS if x.lower() in t]))

def detect_keywords(text):
    t = text.lower()
    return list(set([x for x in KEYWORDS if x.lower() in t]))

def get_article_content(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except:
        return ""

def process_article(title, content, link, source):
    full = f"{title} {content}"

    matched_locations = detect_locations(full)
    matched_keywords = detect_keywords(full)

    if not matched_locations or not matched_keywords:
        return

    key = make_hash(link)

    if key in sent_cache:
        return

    sent_cache.add(key)
    save_cache(sent_cache)

    alert = f"""
🚨 Rà soát vụ việc có dấu hiệu thuộc phạm vi NQ 205

📡 Nguồn:
{source}

⏰ Thời gian:
{datetime.now().strftime("%d/%m/%Y %H:%M:%S")}

📍 Địa bàn:
{", ".join(matched_locations)}

🔍 Dấu hiệu:
{", ".join(matched_keywords)}

📰 Tiêu đề:
{title}

🔗 Link:
{link}
"""

    print(alert)
    send_telegram(alert)

def scan_google_news():
    for loc in BASE_LOCATIONS:
        queries = [
            loc,
            f"{loc} phản ánh",
            f"{loc} môi trường",
            f"{loc} đất đai",
            f"{loc} trẻ em",
            f"{loc} hộ tịch"
        ]

        for query in queries:
            try:
                rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=vi&gl=VN&ceid=VN:vi"
                feed = feedparser.parse(rss_url)

                for entry in feed.entries[:10]:
                    content = get_article_content(entry.link)
                    process_article(entry.title, content, entry.link, "Google News")
            except:
                pass

def scan_rss():
    for rss_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:20]:
                content = get_article_content(entry.link)
                process_article(entry.title, content, entry.link, rss_url)
        except:
            pass

def run():
    send_telegram("✅ Bắt đầu rà soát tin mới NQ205")
    scan_google_news()
    scan_rss()
    send_telegram("✅ Hoàn thành rà soát tin mới NQ205")

if __name__ == "__main__":
    run()
