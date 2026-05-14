import os
import json
import hashlib
from datetime import datetime
from urllib.parse import quote

import requests
import feedparser
from newspaper import Article

# ===============================
# CONFIG
# ===============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "1938209271"))

CACHE_FILE = "radar205_cache.json"
SUBSCRIBERS_FILE = "subscribers.json"
UPDATES_FILE = "telegram_updates.json"

BASE_LOCATIONS = [
    "Lâm Thượng",
    "xã Khánh Hòa",
    "xã Phúc Lợi",
    "Bảo Ái",
    "Mường Lai",
    "Yên Bình",
    "Thác Bà",
    "Cảm Nhân",
    "Lục Yên",
    "xã Yên Thành",
    "Tân Lĩnh",
    "Lào Cai",
    "huyện Lục Yên",
    "hồ Thác Bà",
]

LOCATIONS = []
for loc in BASE_LOCATIONS:
    LOCATIONS.append(loc)
    LOCATIONS.append(f"xã {loc}")
    LOCATIONS.append(f"tỉnh {loc}")

KEYWORDS = [
    # môi trường
    "ô nhiễm",
    "ô nhiễm môi trường",
    "ô nhiễm không khí",
    "ô nhiễm nguồn nước",
    "bụi",
    "bụi trắng",
    "bụi mù mịt",
    "bụi bặm",
    "khói",
    "khói bụi",
    "mùi hôi",
    "xả thải",
    "xả nước thải",
    "nước thải",
    "rác",
    "rác thải",
    "đổ rác",
    "đốt rác",
    "ô nhiễm tiếng ồn",
    "ảnh hưởng sức khỏe",
    "gây ô nhiễm",
    "mỏ đá",
    "gây phiền",
    "bãi thải",
    "mỏ đá nằm sát khu dân cư",
    "mỏ đá đập đục",
    "mỏ đá trắng ở",
    "nổ mìn",
    "rung chấn",
    "đá văng",
    "đe dọa an toàn",
    "bất an",
    "lo lắng",
    "nguy hiểm",
    "xe quá tải",
    "xe chở vật liệu",
    "bụi phủ",

    # đất đai
    "lấn chiếm đất",
    "đất công",
    "hành lang giao thông",
    "hành lang suối",
    "san gạt",
    "đất rừng",
    "tài sản công",
    "khai thác khoáng sản",
    "khai thác cát",
    "khai thác sỏi",
    "sạt lở",
    "mỏ đá",
    
    # an toàn thực phẩm
    "thực phẩm bẩn",
    "ngộ độc",
    "thuốc giả",
    "thuốc hết hạn",

    # tiêu dùng
    "hàng giả",
    "hàng kém chất lượng",
    "quảng cáo sai sự thật",

    # nhóm yếu thế
    "bạo hành trẻ em",
    "bỏ mặc trẻ em",
    "không giấy khai sinh",
    "không được cấp căn cước",
    "hộ tịch",
    "người già neo đơn",
    "người dân tộc thiểu số",

    # ngôn ngữ báo chí mềm
    "phản ánh",
    "bức xúc",
    "kêu cứu",
    "kiến nghị",
    "người dân phản ánh",
    "dân khổ"
]

RSS_SOURCES = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://dantri.com.vn/rss/home.rss",
    "https://vietnamnet.vn/rss/home.rss",
    "https://laodong.vn/rss/home.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://nld.com.vn/rss/home.rss",
    "https://tienphong.vn/rss/home.rss",
    "https://plo.vn/rss/home.rss",
    "https://vov.vn/rss/vov.rss",
    "https://baotainguyenmoitruong.vn/rss/home.rss",
    "https://congly.vn/rss/home.rss",
    "https://phapluatxahoi.kinhtedothi.vn/rss/home.rss"
    "https://laodong.vn/rss/ban-doc.rss",
    "https://laodong.vn/rss/xa-hoi.rss",
    "https://laodong.vn/rss/moi-truong.rss",
    "https://baotainguyenmoitruong.vn/rss/home.rss",
    "https://phapluatxahoi.kinhtedothi.vn/rss/home.rss",

]

# ===============================
# FILE HELPERS
# ===============================

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
telegram_updates = load_json(UPDATES_FILE, {"offset": 0})

if ADMIN_CHAT_ID not in subscribers:
    subscribers.append(ADMIN_CHAT_ID)
    save_json(SUBSCRIBERS_FILE, subscribers)

# ===============================
# TELEGRAM
# ===============================

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
    except Exception as e:
        print("Telegram error:", e)


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
                if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                    subscribers.remove(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)

                send_message(
                    chat_id,
                    "⛔ Bạn đã hủy đăng ký nhận cảnh báo."
                )
    except Exception as e:
        print("Update error:", e)

    save_json(UPDATES_FILE, telegram_updates) 
# ===============================
# HELPERS
# ===============================

def make_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def detect_locations(text):
    t = text.lower()
    found = []
    for x in LOCATIONS:
        if x.lower() in t:
            found.append(x)
    return list(set(found))


def detect_keywords(text):
    t = text.lower()
    found = []
    for x in KEYWORDS:
        if x.lower() in t:
            found.append(x)
    return list(set(found))


def get_article_content(url):
    try:
        article = Article(url)
        article.download()
        article.parse()

        if article.text and len(article.text) > 200:
            return article.text
    except:
        pass

    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
            timeout=20
        )

        html = r.text

        # fallback thô nhưng hữu ích hơn
        cleaned = html.replace("<", " ").replace(">", " ")

        return cleaned
    except:
        return ""


# ===============================
# PROCESS
# ===============================

new_articles_found = 0


def process_article(title, content, link, source):
    global new_articles_found

    full = f"{title} {content}".lower()

    matched_locations = detect_locations(full)
    matched_keywords = detect_keywords(full)

    soft_location_hits = [
        "lâm thượng",
        "xã khánh hòa",
        "xã phúc lợi",
        "bảo ái",
        "mường lai",
        "yên bình",
        "thác bà",
        "cảm nhân",
        "lục yên",
        "xã yên thành",
        "tân lĩnh",
        "lào cai"
    ]

    if not matched_locations:
        if any(x in full for x in soft_location_hits):
            matched_locations = ["Nhận diện mềm theo nội dung"]

    soft_keywords = [
        "bụi",
        "khói",
        "khói bụi",
        "ô nhiễm",
        "bức xúc",
        "kêu cứu",
        "kiến nghị",
        "ảnh hưởng sức khỏe",
        "người dân phản ánh"
    ]

    if not matched_keywords:
        if any(x in full for x in soft_keywords):
            matched_keywords = ["Dấu hiệu cảnh báo mềm"]

    if not matched_locations or not matched_keywords:
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
{", ".join(matched_keywords)}

📰 Tiêu đề:
{title}

🔗 Link:
{link}
"""

    broadcast(alert)


# ===============================
# SCANNERS
# ===============================

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


def scan_rss():
    for rss_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:25]:
                content = get_article_content(entry.link)

                process_article(
                    entry.title,
                    content,
                    entry.link,
                    rss_url
                )

        except Exception as e:
            print("RSS error:", e)


# ===============================
# MAIN
# ===============================

def run():
    global new_articles_found

    get_updates()

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
