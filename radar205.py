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

# Đã làm sạch các đơn vị hành chính giải thể
BASE_LOCATIONS = [
    "Lâm Thượng", "xã Khánh Hòa", "xã Phúc Lợi", "Bảo Ái",
    "Mường Lai", "Yên Bình", "Thác Bà", "Cảm Nhân", "Lục Yên",
    "xã Yên Thành", "Tân Lĩnh", "Lào Cai", "hồ Thác Bà"
]

LOCATIONS = BASE_LOCATIONS.copy()

# Từ điển trọng số AI (Nâng cấp cốt lõi)
WEIGHTED_KEYWORDS = {
    # Dấu hiệu Tội phạm hình sự đặc biệt nghiêm trọng / Tham nhũng
    "giết người": 30, "cướp": 30, "ma túy": 30, "tham nhũng": 30,
    "nhận hối lộ": 30, "đưa hối lộ": 30, "tham ô": 30, "án oan": 30,
    "mua bán người": 30, "hiếp dâm": 30, "xâm hại trẻ em": 30, "bạo hành trẻ em": 30,
    
    # Kinh tế, Đất đai & Môi trường (Trọng tâm NQ 205)
    "khai thác khoáng sản": 25, "mỏ đá": 25, "nổ mìn": 25, "sạt lở": 25,
    "lấn chiếm đất": 25, "đất công": 25, "tài sản công": 25, "phá rừng": 25,
    "cán bộ vòi tiền": 25, "lừa đảo": 25, "chiếm đoạt tài sản": 25,
    
    # Dân sinh & Tiêu dùng
    "xả thải": 20, "hàng giả": 20, "thực phẩm bẩn": 20, "thuốc giả": 20,
    "nước thải": 20, "khai thác cát": 20, "tai nạn": 20, "cháy rừng": 20,
    "vi phạm": 20, "ngộ độc": 20, "bạo lực gia đình": 20,

    # Dấu hiệu cảnh báo mức độ 1
    "ô nhiễm": 15, "rác thải": 15, "bụi trắng": 15, "khói bụi": 15, 
    "xe quá tải": 15, "san gạt": 15, "đất đai": 15,

    # Ngôn ngữ báo chí mềm
    "kêu cứu": 10, "bức xúc": 5, "phản ánh": 5, "kiến nghị": 5, 
    "dân khổ": 5, "bất an": 5, "đe dọa an toàn": 5
}

GOOGLE_KEYWORDS = [
    "ô nhiễm", "xả thải", "nước thải", "khai thác khoáng sản",
    "mỏ đá", "mỏ cát", "khai thác cát", "đất đai", "lấn chiếm đất",
    "đất công", "tham nhũng", "hàng giả", "thực phẩm bẩn", "tai nạn",
    "sạt lở", "phá rừng", "rác thải", "cháy rừng", "vi phạm", "bức xúc"
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
    "https://phapluatxahoi.kinhtedothi.vn/rss/home.rss",
    "https://baolaocai.vn/rss/home.rss",
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
            chat_id = msg.get("chat", {}).get("id")

            if not chat_id:
                continue

            if text == "/start":
                if chat_id not in subscribers:
                    subscribers.append(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)
                send_message(
                    chat_id,
                    "✅ Chào mừng bạn đã đăng ký nhận thông tin cảnh báo các vụ việc, nguồn tin về Nghị quyết 205."
                )
            elif text == "/stop":
                if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                    subscribers.remove(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)
                send_message(chat_id, "⛔ Bạn đã hủy đăng ký nhận cảnh báo.")
    except Exception as e:
        print("Update error:", e)

    save_json(UPDATES_FILE, telegram_updates)

# ===============================
# HELPERS
# ===============================

def make_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()

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
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        html = r.text
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

    matched_locations = [loc for loc in LOCATIONS if loc.lower() in full]
    matched_keywords = []
    
    # Tính điểm AI theo trọng số
    score = 0
    score += len(matched_locations) * 15

    for kw, weight in WEIGHTED_KEYWORDS.items():
        if kw.lower() in full:
            matched_keywords.append(kw)
            score += weight

    if score < 35:
        return

    # Chống báo trùng bằng 80 ký tự đầu của Tiêu đề
    key = make_hash(title.lower()[:80])

    if key in sent_cache:
        return

    sent_cache.add(key)
    save_json(CACHE_FILE, list(sent_cache))

    new_articles_found += 1

    # Phân loại mức độ nghiêm trọng
    if score >= 80:
        level = "🔴 RẤT CAO"
    elif score >= 60:
        level = "🟠 CAO"
    elif score >= 40:
        level = "🟡 TRUNG BÌNH"
    else:
        level = "🟢 THẤP"

    # Định dạng an toàn cho GitHub Actions (Không dùng triple-quote)
    time_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    loc_str = ", ".join(matched_locations) if matched_locations else "Không xác định"
    kw_str = ", ".join(matched_keywords)

    alert = (
        f"🚨 CẢNH BÁO NGUỒN TIN CÓ DẤU HIỆU VI PHẠM\n\n"
        f"📊 MỨC ĐỘ: {level} (Điểm AI: {score})\n\n"
        f"📡 Nguồn: {source}\n"
        f"⏰ Thời gian: {time_str}\n"
        f"📍 Địa bàn: {loc_str}\n"
        f"🔍 Dấu hiệu: {kw_str}\n\n"
        f"📰 Tiêu đề: {title}\n"
        f"🔗 Link: {link}"
    )

    broadcast(alert)

# ===============================
# SCANNERS
# ===============================

def scan_google_news():
    queries = []
    for loc in BASE_LOCATIONS:
        for kw in GOOGLE_KEYWORDS:
            queries.append(f"{loc} {kw}")

    for query in queries:
        try:
            rss_url = (
                f"https://news.google.com/rss/search?"
                f"q={quote(query)}&hl=vi&gl=VN&ceid=VN:vi"
            )
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:25]:
                # Tối ưu hóa: Không tải toàn bộ bài báo nếu không cần thiết
                content = ""
                if hasattr(entry, "summary"):
                    content += entry.summary
                if hasattr(entry, "description"):
                    content += entry.description
                if len(content) < 100:
                    content = get_article_content(entry.link)

                process_article(
                    entry.title,
                    content,
                    entry.link,
                    "Google News"
                )
        except Exception as e:
            print("Google News error:", e)

def scan_google_news_all():
    queries = [
        "ô nhiễm", "khai thác khoáng sản", "đất đai", "hàng giả",
        "xả thải", "phá rừng", "tham nhũng", "vi phạm"
    ]

    for query in queries:
        try:
            rss_url = (
                f"https://news.google.com/rss/search?"
                f"q={quote(query)}&hl=vi&gl=VN&ceid=VN:vi"
            )
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:25]:
                content = entry.summary if hasattr(entry, "summary") else ""
                process_article(
                    entry.title,
                    content,
                    entry.link,
                    "Google RSS"
                )
        except Exception as e:
            print("Google News All error:", e)

def scan_rss():
    for rss_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:25]:
                content = ""
                if hasattr(entry, "summary"):
                    content += entry.summary
                if hasattr(entry, "description"):
                    content += entry.description
                if len(content) < 100:
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
    scan_google_news_all()
    scan_rss()

    if new_articles_found == 0:
        broadcast(
            "📭 Hôm nay không phát hiện thông tin mới thuộc phạm vi rà soát Nghị quyết 205.\n\n"
            "Hệ thống sẽ tiếp tục rà soát vào ngày mai."
        )
    else:
        broadcast(f"✅ Hoàn thành rà soát. Phát hiện {new_articles_found} thông tin mới.")

if __name__ == "__main__":
    run()
