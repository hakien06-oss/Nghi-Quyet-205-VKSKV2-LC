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

LOCATIONS = [x.lower() for x in BASE_LOCATIONS]

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
    
     # DẤU HIỆU TỘI PHẠM HÌNH SỰ
    "giết người",
    "cố ý gây thương tích",
    "kêu oan",
    "án oan",
    "cán bộ vòi tiền",
    "đánh người",
    "hành hung",
    "chém người",
    "đâm người",
    "gây rối trật tự công cộng",
    "cướp",
    "cướp giật",
    "trộm cắp",
    "trộm",
    "lừa đảo",
    "chiếm đoạt tài sản",
    "tham ô",
    "nhận hối lộ",
    "đưa hối lộ",
    "môi giới hối lộ",
    "tham nhũng",
    "giả mạo giấy tờ",
    "làm giả",
    "giấy tờ giả",
    "ma túy",
    "tàng trữ ma túy",
    "mua bán ma túy",
    "tổ chức sử dụng ma túy",
    "đánh bạc",
    "tổ chức đánh bạc",
    "buôn lậu",
    "hàng cấm",
    "vận chuyển hàng cấm",
    "hủy hoại tài sản",
    "đe dọa giết người",
    "chống người thi hành công vụ",

    # nhóm yếu thế
    "bạo hành trẻ em",
    "xâm hại trẻ em",
    "xâm hại tình dục",
    "hiếp dâm",
    "dâm ô",
    "bỏ mặc trẻ em",
    "mua bán người",
    "bóc lột lao động",
    "bạo lực gia đình",
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
    # Lào Cai
    "https://baolaocai.vn/rss/home.rss",

    # Pháp luật
    "https://congly.vn/rss/home.rss",
    "https://baovephapluat.vn/rss/home.rss",
    "https://plo.vn/rss/home.rss",

    # Trung ương
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://dantri.com.vn/rss/home.rss",
    "https://vietnamnet.vn/rss/home.rss",
    "https://laodong.vn/rss/home.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://nld.com.vn/rss/home.rss",
    "https://tienphong.vn/rss/home.rss",
    "https://vov.vn/rss/vov.rss",
    "https://vtcnews.vn/rss/feed.rss",
    "https://danviet.vn/rss/home.rss",
    "https://www.vietnamplus.vn/rss/home.vnp",
    "https://xaydung.gov.vn/rss",
    "https://baochinhphu.vn/rss/home.rss",
    "https://nhandan.vn/rss/home.rss",

    # Bạn đọc - phản ánh
    "https://laodong.vn/rss/ban-doc.rss",
    "https://laodong.vn/rss/xa-hoi.rss",
    "https://laodong.vn/rss/moi-truong.rss",

    # Môi trường
    "https://baotainguyenmoitruong.vn/rss/home.rss"
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
                    "✅ Chào mừng bạn đã đã đăng ký nhận thông tin cảnh báo các vụ việc, nguồn tin về Nghị quyết 205 và các vụ việc có dấu hiệu vi phạm pháp luật trên địa bàn quản lý của VKSND khu vực 2, tỉnh Lào Cai."
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
    text = text.lower()

    found = []

    for location in LOCATIONS:
        if location in text:
            found.append(location)

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
        "lào cai",
        "mỏ đá",
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
🚨 CẢNH BÁO NGUỒN TIN CÓ DẤU HIỆU VI PHẠM PHÁP LUẬT

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
        f"{loc} kiến nghị",
        f"{loc} khiếu nại",
        f"{loc} tố cáo",
        f"{loc} môi trường",
        f"{loc} ô nhiễm",
        f"{loc} xả thải",
        f"{loc} rác thải",
        f"{loc} đất đai",
        f"{loc} lấn chiếm đất",
        f"{loc} tài sản công",
        f"{loc} khai thác khoáng sản",
        f"{loc} khai thác cát",
        f"{loc} khai thác sỏi",
        f"{loc} mỏ đá",
        f"{loc} trẻ em",
        f"{loc} xâm hại trẻ em",
        f"{loc} thực phẩm bẩn",
        f"{loc} hàng giả",
        f"{loc} lừa đảo",
        f"{loc} tham nhũng",
        f"{loc} ma túy",

        f'site:baolaocai.vn "{loc}"',
        f'site:laocai.gov.vn "{loc}"',
        f'site:congly.vn "{loc}"',
        f'site:baovephapluat.vn "{loc}"',
        f'site:plo.vn "{loc}"',
        f'site:dantri.com.vn "{loc}"',
        f'site:vietnamnet.vn "{loc}"',
        f'site:laodong.vn "{loc}"',
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
