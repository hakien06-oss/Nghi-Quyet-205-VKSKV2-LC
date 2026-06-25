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

# ĐIỀU KIỆN LỌC CỨNG (HARD FILTER) - Chỉ quét chính xác trong các khu vực này
EXACT_LOCATIONS = [
    "Lào Cai", 
    "Lâm Thượng", "Khánh Hòa", "xã Phúc Lợi", "Bảo Ái",
    "Mường Lai", "xã Yên Bình", "Thác Bà", "hồ Thác Bà", 
    "Cảm Nhân", "Lục Yên", "xã Yên Thành", "Tân Lĩnh", "huyện Yên Bình", "Yên Bái",
]

# KIẾN TRÚC TRUNG TÂM: RULE_ENGINE (Tích hợp Điểm số, Từ khóa và Phân tích AI)
RULE_ENGINE = {
    "Môi trường & Sinh thái": {
        "score": 20,
        "is_nq205": True,
        "keywords": ["ô nhiễm", "xả thải", "nước thải", "bụi mù mịt", "khói bụi", "rác thải", "mùi hôi", "bụi trắng", "môi trường"],
        "hint": "Cần xác minh mức độ ảnh hưởng đến cộng đồng dân cư xung quanh."
    },
    "Quản lý Đất đai & Tài nguyên": {
        "score": 25,
        "is_nq205": True,
        "keywords": ["lấn chiếm đất", "đất công", "khai thác khoáng sản", "mỏ đá", "khai thác cát", "san gạt", "đất rừng", "sạt lở", "tài sản công", "phá rừng", "đất đai"],
        "hint": "Kiểm tra tính pháp lý của dự án, hoạt động khai thác và ranh giới cấp phép."
    },
    "Bảo vệ Nhóm yếu thế": {
        "score": 30,
        "is_nq205": True,
        "keywords": ["bạo hành trẻ em", "xâm hại trẻ em", "người dân tộc thiểu số", "người già neo đơn", "bóc lột lao động", "hiếp dâm"],
        "hint": "Vi phạm nghiêm trọng liên quan đến nhóm yếu thế, ưu tiên xác minh khẩn cấp để có biện pháp bảo vệ."
    },
    "Tội phạm Hình sự & Tham nhũng": {
        "score": 30,
        "is_nq205": False,
        "keywords": ["giết người", "tham nhũng", "nhận hối lộ", "đưa hối lộ", "tham ô", "ma túy", "lừa đảo", "chiếm đoạt tài sản", "án oan", "cướp", "cán bộ vòi tiền"],
        "hint": "Dấu hiệu án hình sự, cần phối hợp kiểm tra để chuyển thông tin cho bộ phận kiểm sát điều tra."
    },
    "An toàn & Tiêu dùng Dân sinh": {
        "score": 15,
        "is_nq205": True,
        "keywords": ["hàng giả", "thực phẩm bẩn", "ngộ độc", "tai nạn", "thuốc giả", "bất an", "bạo lực gia đình", "cháy rừng", "vi phạm"],
        "hint": "Theo dõi số lượng cá nhân bị ảnh hưởng để đánh giá mức độ vi phạm lợi ích công cộng."
    },
    "Báo chí phản ánh": {
        "score": 5,
        "is_nq205": True,
        "keywords": ["kêu cứu", "bức xúc", "phản ánh", "kiến nghị", "dân khổ", "đe dọa an toàn"],
        "hint": "Cần đối chiếu với các nguồn tin khác hoặc chính quyền cơ sở để xác minh tính khách quan."
    }
}

# DANH SÁCH TỪ KHÓA CHO GOOGLE NEWS (Trích xuất để tối ưu request)
GOOGLE_QUERIES = [
    "ô nhiễm", "khai thác khoáng sản", "mỏ đá", "đất đai", 
    "lấn chiếm", "xả thải", "phá rừng", "vi phạm", "sạt lở", "xả rác", "chưa có căn cước", "giấy khai sinh", "bạo lực", "khói bụi", "ô nhiễm",
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
    "thực phẩm bẩn",
    "ngộ độc",
    "thuốc giả",
    "thuốc hết hạn",
    "hàng giả",
    "hàng kém chất lượng",
    "quảng cáo sai sự thật",
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
    "phản ánh",
    "bức xúc",
    "kêu cứu",
    "kiến nghị",
    "người dân phản ánh",
    "dân khổ"
    
]

# ĐÃ MỞ RỘNG DANH SÁCH RSS (Có thể tiếp tục dán thêm để đạt 100-120 nguồn)
RSS_SOURCES = [
    # Nhóm Báo Đảng & Chính trị - Pháp luật
    "https://baolaocai.vn/rss/home.rss",
    "https://nhandan.vn/rss/phap-luat.rss",
    "https://nhandan.vn/rss/ban-doc.rss",
    "https://baochinhphu.vn/Rss/xa-hoi.rss",
    "https://congly.vn/rss/home.rss",
    "https://congly.vn/rss/phap-luat.rss",
    "https://congly.vn/rss/ban-doc.rss",
    "https://baophapluat.vn/rss/home.rss",
    "https://baophapluat.vn/rss/ban-doc.rss",
    "https://phapluatxahoi.kinhtedothi.vn/rss/home.rss",
    "https://baotainguyenmoitruong.vn/rss/home.rss",
    "https://baotainguyenmoitruong.vn/rss/ban-doc.rss",
    "https://baotainguyenmoitruong.vn/rss/phap-luat.rss",
    "https://baotintuc.vn/phap-luat.rss",
    
    # Nhóm Báo Phổ thông & Xã hội
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://vnexpress.net/rss/phap-luat.rss",
    "https://dantri.com.vn/rss/home.rss",
    "https://dantri.com.vn/rss/phap-luat.rss",
    "https://dantri.com.vn/rss/ban-doc.rss",
    "https://vietnamnet.vn/rss/home.rss",
    "https://vietnamnet.vn/rss/phap-luat.rss",
    "https://vietnamnet.vn/rss/ban-doc.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://tuoitre.vn/rss/phap-luat.rss",
    "https://tuoitre.vn/rss/ban-doc.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://thanhnien.vn/rss/phap-luat.rss",
    "https://laodong.vn/rss/home.rss",
    "https://laodong.vn/rss/phap-luat.rss",
    "https://laodong.vn/rss/ban-doc.rss",
    "https://laodong.vn/rss/moi-truong.rss",
    "https://nld.com.vn/rss/home.rss",
    "https://nld.com.vn/rss/phap-luat.rss",
    "https://nld.com.vn/rss/ban-doc.rss",
    "https://tienphong.vn/rss/home.rss",
    "https://tienphong.vn/rss/phap-luat.rss",
    "https://plo.vn/rss/home.rss",
    "https://plo.vn/rss/phap-luat.rss",
    "https://plo.vn/rss/ban-doc.rss",
    "https://vov.vn/rss/vov.rss",
    "https://vov.vn/rss/phap-luat.rss",
    "https://baotainguyenmoitruong.vn/rss/home.rss",
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
                    "✅ Chào mừng bạn đã đăng ký nhận thông tin cảnh báo từ hệ thống AI Radar205."
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

    # 1. HARD FILTER: Loại bỏ ngay nếu không tìm thấy tên địa bàn trong EXACT_LOCATIONS
    matched_locations = [loc for loc in EXACT_LOCATIONS if loc.lower() in full]
    if not matched_locations:
        return

    # 2. SCORING & CATEGORIZATION BẰNG RULE_ENGINE
    score = len(matched_locations) * 25 # Trọng số địa bàn ưu tiên cao
    matched_keywords = []
    matched_domains = []
    hints = []
    is_nq205_flag = False

    for domain, rules in RULE_ENGINE.items():
        domain_matched = False
        for kw in rules["keywords"]:
            if kw.lower() in full:
                matched_keywords.append(kw)
                score += rules["score"]
                domain_matched = True
        
        # Nếu bài viết chạm vào từ khóa của lĩnh vực này
        if domain_matched:
            matched_domains.append(domain)
            hints.append(rules["hint"])
            if rules["is_nq205"]:
                is_nq205_flag = True

    # 3. NGƯỠNG LỌC (Tăng lên 45 để loại triệt để tin rác)
    if score < 45:
        return

    # 4. CHỐNG TRÙNG LẶP (Dựa trên 80 ký tự đầu của Tiêu đề)
    key = make_hash(title.lower()[:80])
    if key in sent_cache:
        return

    sent_cache.add(key)
    save_json(CACHE_FILE, list(sent_cache))
    new_articles_found += 1

    # 5. PHÂN LOẠI MỨC ĐỘ
    if score >= 80:
        level = "🔴 RẤT CAO"
    elif score >= 60:
        level = "🟠 CAO"
    elif score >= 50:
        level = "🟡 TRUNG BÌNH"
    else:
        level = "🟢 THẤP"

    # 6. ĐỊNH DẠNG CẢNH BÁO AN TOÀN CHO GITHUB ACTIONS
    time_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    
    # Lọc trùng lặp danh sách hiển thị
    loc_str = ", ".join(sorted(set(matched_locations)))
    kw_str = ", ".join(sorted(set(matched_keywords)))
    domain_str = ", ".join(sorted(set(matched_domains)))
    
    nq205_str = "CÓ" if is_nq205_flag else "KHÔNG (Có thể thuộc thẩm quyền Hình sự/Hành chính khác)"
    hint_str = " ".join(set(hints))

    alert = (
        f"🚨 CẢNH BÁO NGUỒN TIN - {level}\n\n"
        f"📍 Địa bàn: {loc_str}\n"
        f"🔍 Lĩnh vực: {domain_str}\n"
        f"🔑 Từ khóa: {kw_str}\n"
        f"📈 Điểm AI: {score}\n\n"
        f"🧠 NHẬN ĐỊNH BƯỚC ĐẦU:\n"
        f"✓ Thuộc phạm vi NQ 205: {nq205_str}\n"
        f"✓ Khuyến nghị: {hint_str}\n\n"
        f"📰 Tiêu đề: {title}\n"
        f"📡 Nguồn: {source} ({time_str})\n"
        f"🔗 Link: {link}"
    )

    broadcast(alert)

# ===============================
# SCANNERS
# ===============================

def scan_google_news():
    queries = []
    for loc in EXACT_LOCATIONS:
        for kw in GOOGLE_QUERIES:
            queries.append(f"{loc} {kw}")

    for query in queries:
        try:
            rss_url = (
                f"https://news.google.com/rss/search?"
                f"q={quote(query)}&hl=vi&gl=VN&ceid=VN:vi"
            )
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
                    "Google News"
                )
        except Exception as e:
            print("Google News error:", e)

def scan_google_news_all():
    for query in GOOGLE_QUERIES:
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

    broadcast("🔎 RADAR205 bắt đầu rà soát thông tin hệ thống hôm nay...")

    scan_google_news()
    scan_google_news_all()
    scan_rss()

    if new_articles_found == 0:
        broadcast(
            "📭 Hôm nay không phát hiện nguồn tin mới thuộc phạm vi rà soát bảo vệ lợi ích công cộng.\n\n"
            "Hệ thống tự động tiếp tục chế độ trực chiến."
        )
    else:
        broadcast(f"✅ Hoàn thành rà soát. Phát hiện và xử lý {new_articles_found} thông tin mới.")

if __name__ == "__main__":
    run()
