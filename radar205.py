import os
import json
import hashlib
from datetime import datetime
from urllib.parse import quote

import requests
import feedparser
from newspaper import Article

# ================= CONFIG =================
TELEGRAM_TOKEN = "8668493802:AAH67Cc1Sa1dlzfACDzkoKYb-2OfxGTpIiI"

CACHE_FILE = "radar205_cache.json"
SUBSCRIBERS_FILE = "subscribers.json"
UPDATES_FILE = "telegram_updates.json"

BASE_LOCATIONS = [
    "Lâm Thượng",
    "Lục Yên",
    "xã Khánh Hòa",
    "Tân Lĩnh",
    "Bảo Ái",
    "Mường Lai",
    "xã Yên Thành",
    "Thác Bà",
    "Cảm Nhân",
    "Yên Bình",
    "xã Phúc Lợi"
    "Lào Cai"
]

LOCATIONS = []
for loc in BASE_LOCATIONS:
    LOCATIONS.append(loc)
    LOCATIONS.append(f"xã {loc}")

KEYWORDS = [
    "đổ rác","rác thải","ô nhiễm","ô nhiễm môi trường","ô nhiễm nguồn nước","bụi","bột đá", "bụi trắng", "khai thác đá", "bụi đá"
    "ô nhiễm không khí","đốt rác","xả nước thải","xả thải","nước thải","khói bụi",
    "bụi trắng",
    "bụi mù mịt",
    "bụi bặm", "phản ánh",
    "bức xúc",
    "kêu cứu",
    "kiến nghị",
    "dân khổ",
    "người dân phản ánh"
    "khai thác khoáng sản","khai thác cát","khai thác sỏi","sạt lở","phá rừng",
    "hủy hoại môi trường","lấn chiếm đất","đất công","hành lang giao thông", "bãi rác", "nắp cống"
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

# ================= FILE HELPERS =================
def load_json(file_name, default):
    if os.path.exists(file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(file_name, data):
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(data, f)

sent_cache = set(load_json(CACHE_FILE, []))
subscribers = load_json(SUBSCRIBERS_FILE, [])

ADMIN_CHAT_ID = 1938209271

if ADMIN_CHAT_ID not in subscribers:
    subscribers.append(ADMIN_CHAT_ID)
    save_json(SUBSCRIBERS_FILE, subscribers)
telegram_updates = load_json(UPDATES_FILE, {"offset": 0})

# ================= TELEGRAM =================
def send_message(chat_id, message):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message[:4000]
            },
            timeout=20
        )
    except:
        pass

def broadcast(message):
    for chat_id in subscribers:
        send_message(chat_id, message)

def get_updates():
    offset = telegram_updates.get("offset", 0)

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}",
            timeout=20
        )

        data = r.json()

        if not data.get("ok"):
            return

        for item in data["result"]:
            telegram_updates["offset"] = item["update_id"] + 1

            msg = item.get("message", {})
            text = msg.get("text", "")
            chat = msg.get("chat", {})
            chat_id = chat.get("id")

            if not chat_id:
                continue

            if text == "/start":
                if chat_id not in subscribers:
                    subscribers.append(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)

                send_message(
                    chat_id,
                    "✅ Bạn đã đăng ký nhận cảnh báo RADAR205 hằng ngày."
                )

            elif text == "/stop":
                if chat_id in subscribers:
                    subscribers.remove(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)

                send_message(
                    chat_id,
                    "⛔ Bạn đã hủy đăng ký nhận cảnh báo."
                )

        save_json(UPDATES_FILE, telegram_updates)

    except:
        pass
# ================= HELPERS =================
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

# ================= PROCESS =================
new_articles_found = 0

def process_article(title, content, link, source):
    global new_articles_found

    full = f"{title} {content}"

    matched_locations = detect_locations(full)
    matched_keywords = detect_keywords(full)

    if not matched_locations:
        return

    # mềm hóa logic phát hiện
    if not matched_keywords:
        title_lower = title.lower()

        soft_hits = [
            "bụi",
            "ô nhiễm",
            "khói",
            "bức xúc",
            "kêu cứu",
            "phản ánh",
            "kiến nghị",
            "ảnh hưởng sức khỏe"
        ]

        if not any(x in title_lower for x in soft_hits):
            return

    key = make_hash(link)

    if key in sent_cache:
        return

    sent_cache.add(key)
    save_json(CACHE_FILE, list(sent_cache))

    new_articles_found += 1

    alert = f"""
🚨 RÀ SOÁT VỤ VIỆC CÓ DẤU HIỆU THUỘC NQ 205

📡 Nguồn:
{source}

⏰ Thời gian:
{datetime.now().strftime("%d/%m/%Y %H:%M:%S")}

📍 Địa bàn:
{", ".join(matched_locations)}

🔍 Dấu hiệu:
{", ".join(matched_keywords) if matched_keywords else "Dấu hiệu cảnh báo mềm (AI nhận diện tiêu đề)"}

📰 Tiêu đề:
{title}

🔗 Link:
{link}
"""

    broadcast(alert)

# ================= GOOGLE NEWS =================
def scan_google_news():
    for loc in BASE_LOCATIONS:

        queries = [
            loc,
            f"{loc} phản ánh",
            f"{loc} môi trường",
            f"{loc} ô nhiễm",
            f"{loc} bụi",
            f"{loc} khói bụi",
            f"{loc} dân bức xúc",
            f"{loc} kêu cứu",
            f"{loc} đất đai",
            f"{loc} trẻ em",
            f"{loc} hộ tịch",
            f"{loc} thực phẩm",
            f"{loc} hàng giả"
        ]

        for query in queries:
            try:
                rss_url = (
                    f"https://news.google.com/rss/search?"
                    f"q={quote(query)}&hl=vi&gl=VN&ceid=VN:vi"
                )

                feed = feedparser.parse(rss_url)

                for entry in feed.entries[:25]:
                    content = get_article_content(entry.link)

                    process_article(
                        entry.title,
                        content,
                        entry.link,
                        "Google News"
                    )

            except Exception as e:
                print("Google News error:", e)
    for rss_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:20]:
                content = get_article_content(entry.link)

                process_article(
                    entry.title,
                    content,
                    entry.link,
                    rss_url
                )
        except:
            pass
            # ================= MAIN =================
def run():
    global new_articles_found

    # đọc người dùng mới /start hoặc /stop
    get_updates()

    # nếu chưa ai đăng ký thì thôi
    if not subscribers:
        print("No subscribers.")
        return

    broadcast("🔎 RADAR205 bắt đầu rà soát thông tin hôm nay...")

    scan_google_news()
    scan_rss()

    if new_articles_found == 0:
        broadcast(
            """📭 Hôm nay không phát hiện thông tin mới thuộc phạm vi rà soát Nghị quyết 205.

Hệ thống sẽ tiếp tục rà soát vào ngày mai."""
        )
    else:
        broadcast(
            f"✅ Hoàn thành rà soát. Phát hiện {new_articles_found} thông tin mới."
        )

if __name__ == "__main__":
    run()
