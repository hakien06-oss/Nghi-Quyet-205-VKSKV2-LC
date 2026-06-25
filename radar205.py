import os
import json
import hashlib
import concurrent.futures
import threading
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
    "Lâm Thượng", "xã Khánh Hòa", "xã Phúc Lợi", "Bảo Ái",
    "Mường Lai", "xã Yên Bình", "Thác Bà", "hồ Thác Bà", 
    "Cảm Nhân", "Lục Yên", "xã Yên Thành", "Tân Lĩnh", "huyện Yên Bình", "Yên Bái"
]

# TẬP TRUNG TỐI ĐA VÀO NGHỊ QUYẾT 205 - LOẠI BỎ HÌNH SỰ THUẦN TÚY
RULE_ENGINE = {
    "Môi trường & Sinh thái": {
        "score": 25,
        "is_nq205": True,
        "keywords": ["ô nhiễm", "đổ rác bừa bãi", "hôi", "bột đá", "xả thải", "bụi bặm", "khói", "đá văng", "nước đục", "cá chết", "suối", "nước hồ", "nước sông", "nước thải", "bụi mù mịt", "khói bụi", "rác thải", "mùi hôi", "bụi trắng", "môi trường"],
        "hint": "Cần xác minh mức độ ảnh hưởng đến cộng đồng dân cư xung quanh (NQ205)."
    },
    "Quản lý Đất đai & Tài nguyên": {
        "score": 25,
        "is_nq205": True,
        "keywords": ["lấn chiếm đất", "đất công", "khai thác khoáng sản", "mỏ đá", "khai thác cát", "san gạt", "vật liệu xây dựng", "đất hiếm", 
            "đào đất", "đào núi", "nổ mìn", "đập đá", "máy nghiền", "đất rừng", "sạt lở", "tài sản công", "phá rừng", "đất đai"],
        "hint": "Kiểm tra tính pháp lý của dự án, ranh giới cấp phép và thiệt hại tài nguyên (NQ205)."
    },
    "Bảo vệ Nhóm yếu thế": {
        "score": 30,
        "is_nq205": True,
        "keywords": ["bạo hành trẻ em", "xâm hại trẻ em", "người dân tộc thiểu số", "người già neo đơn", "bóc lột lao động", "căn cước", "giấy khai sinh", "người khuyết tật", "trợ cấp", "bạo lực gia đình"],
        "hint": "Cần có biện pháp bảo vệ khẩn cấp quyền và lợi ích hợp pháp của nhóm yếu thế (NQ205)."
    },
    "Tham nhũng & Lợi ích công": {
        "score": 15,
        "is_nq205": True,
        "keywords": ["tham nhũng", "nhận hối lộ", "tham ô", "lừa đảo", "chiếm đoạt tài sản", "cán bộ vòi tiền"],
        "hint": "Nghiên cứu hồ sơ xem có yếu tố khởi kiện dân sự đòi bồi thường thiệt hại cho Nhà nước không (NQ205)."
    },
    "An toàn & Tiêu dùng Dân sinh": {
        "score": 15,
        "is_nq205": True,
        "keywords": ["hàng giả", "thực phẩm bẩn", "ngộ độc", "tai nạn", "thuốc giả", "bất an"],
        "hint": "Đánh giá số lượng người bị ảnh hưởng để xác định vi phạm lợi ích công cộng (NQ205)."
    },
    "Báo chí phản ánh": {
        "score": 5,
        "is_nq205": True,
        "keywords": ["kêu cứu", "bức xúc", "phản ánh", "kiến nghị", "dân khổ", "đe dọa an toàn"],
        "hint": "Đối chiếu nguồn tin với chính quyền cơ sở để xác minh tính khách quan."
    }
}

GOOGLE_QUERIES = [
    "ô nhiễm", "khai thác khoáng sản", "mỏ đá", "đất đai", 
    "lấn chiếm", "xả thải", "phá rừng", "vi phạm", "sạt lở", "bức xúc",
    "site:thanhtra.gov.vn",
    "site:vksndtc.gov.vn",
    "site:tandtc.gov.vn",
    "site:bocongan.gov.vn",
    "site:moj.gov.vn" 
]

RSS_SOURCES = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://dantri.com.vn/rss/home.rss",
    "https://vietnamnet.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://laodong.vn/rss/home.rss",
    "https://nld.com.vn/rss/home.rss",
    "https://tienphong.vn/rss/home.rss",
    "https://plo.vn/rss/home.rss",
    "https://congly.vn/rss/home.rss",
    "https://baophapluat.vn/rss/home.rss",
    "https://baovephapluat.vn/rss/home.rss",
    "https://cand.com.vn/rss/su-kien-binh-luan-chu-diem/",
    "https://nhandan.vn/rss/phap-luat.rss",
    "https://baochinhphu.vn/Rss/xa-hoi.rss",
    "https://baotintuc.vn/phap-luat.rss",
    "https://congthuong.vn/rss/phap-luat.rss",
    "https://baoxaydung.com.vn/rss/home.rss",
    "https://baogiaothong.vn/rss/home.rss",
    "https://daidoanket.vn/rss/phap-luat.rss",
    "https://vneconomy.vn/rss/home.rss",
    "https://cafef.vn/trang-chu.rss",
    "https://cafebiz.vn/trang-chu.rss",
    "https://vietnamfinance.vn/rss/home.rss",
    "https://baodautu.vn/rss/phap-luat.rss",
    "https://diendandoanhnghiep.vn/rss/home.rss",
    "https://thoibaotaichinhvietnam.vn/rss/home.rss",
    "https://nguoiquansat.vn/rss/home.rss",
    "https://cafebiz.vn/rss.chn",
    "https://vneconomy.vn/rss.html",
    "https://vietnamfinance.vn/rss/home.rss",
    "https://mekongasean.vn/rss",
    "https://congthuong.vn/rss/home.rss",
    "https://thoibaotaichinhvietnam.vn/rss/home.rss",
    "https://diendandoanhnghiep.vn/rss/home.rss",
    "https://haiquanonline.com.vn/rss/home.rss",
    "https://kinhtedothi.vn/rss/home.rss",
    "https://doanhnghiepvn.vn/rss/home.rss",
    "https://thuonghieucongluan.com.vn/rss/home.rss",
    "https://vietq.vn/rss",
    "https://tapchitaichinh.vn/rss",
    "https://baotainguyenmoitruong.vn/rss/home.rss",
    "https://moitruongvadothi.vn/rss/home.rss",
    "https://nongnghiep.vn/rss/home.rss",
    "https://khoahocdoisong.vn/rss/home.rss",
    "https://vietq.vn/rss/home.rss",
    "https://suckhoedoisong.vn/rss/home.rss",
    "https://moitruong.net.vn/rss",
    "https://tainguyenvamoitruong.vn/rss/home.rss",
    "https://soha.vn/thoi-su.rss",
    "https://www.24h.com.vn/upload/rss/tintuctrongngay.rss",
    "https://kenh14.vn/xa-hoi.rss",
    "https://kienthuc.net.vn/rss/xa-hoi.rss",
    "https://www.nguoiduatin.vn/rss/trang-chu.rss",
    "https://1thegioi.vn/rss/home.rss",
    "https://doisongphapluat.com/rss/home.rss",
    "https://giadinh.suckhoedoisong.vn/rss/home.rss",
    "https://www.24h.com.vn/upload/rss/trangchu24h.rss",
    "https://baolaocai.vn/rss/home.rss"
]

# ===============================
# FILE HELPERS & THREAD LOCK
# ===============================

file_lock = threading.Lock()

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
                with file_lock:
                    if chat_id not in subscribers:
                        subscribers.append(chat_id)
                        save_json(SUBSCRIBERS_FILE, subscribers)
                send_message(
                    chat_id,
                    "✅ Chào mừng bạn đã đăng ký nhận thông tin cảnh báo từ hệ thống AI Radar205."
                )
            elif text == "/stop":
                with file_lock:
                    if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                        subscribers.remove(chat_id)
                        save_json(SUBSCRIBERS_FILE, subscribers)
                send_message(chat_id, "⛔ Bạn đã hủy đăng ký nhận cảnh báo.")
    except Exception as e:
        print("Update error:", e)

    with file_lock:
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

    # 1. HARD FILTER
    matched_locations = [loc for loc in EXACT_LOCATIONS if loc.lower() in full]
    if not matched_locations:
        return

    # 2. SCORING & CATEGORIZATION (Khớp chính xác - Không dùng Fuzzy Match)
    score = len(matched_locations) * 25
    matched_keywords = []
    matched_domains = []
    hints = []
    is_nq205_flag = False

    for domain, rules in RULE_ENGINE.items():
        domain_matched = False
        for kw in rules["keywords"]:
            if kw.lower() in full:
                if kw not in matched_keywords:
                    matched_keywords.append(kw)
                score += rules["score"]
                domain_matched = True
        
        if domain_matched:
            if domain not in matched_domains:
                matched_domains.append(domain)
            if rules["hint"] not in hints:
                hints.append(rules["hint"])
            if rules["is_nq205"]:
                is_nq205_flag = True

    # 3. NGƯỠNG LỌC CỨNG (Loại bỏ triệt để tin rác)
    if score < 45:
        return

    # 4. CHỐNG TRÙNG LẶP & LƯU CACHE (Bảo vệ bằng Thread Lock)
    key = make_hash(title.lower()[:80])
    with file_lock:
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

    # 6. ĐỊNH DẠNG CẢNH BÁO AN TOÀN TRÊN GITHUB ACTIONS
    time_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    
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
# MULTITHREADING SCANNERS
# ===============================

def process_single_feed(feed_info):
    url, source_name = feed_info
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:25]:
            content = getattr(entry, "summary", "") + getattr(entry, "description", "")
            if len(content) < 100: 
                content = get_article_content(entry.link)
            process_article(entry.title, content, entry.link, source_name)
    except Exception:
        pass

def run_scanners_concurrently():
    tasks = []
    
    # 1. Thêm nguồn RSS
    for url in RSS_SOURCES:
        tasks.append((url, "RSS Báo chí"))
        
    # 2. Thêm nguồn Google News Địa phương
    for loc in EXACT_LOCATIONS:
        for kw in GOOGLE_QUERIES:
            if not kw.startswith("site:"):
                query = f"{loc} {kw}"
                rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=vi&gl=VN&ceid=VN:vi"
                tasks.append((rss_url, "Google News"))
                
    # 3. Thêm nguồn Google News Lưới vét Cổng thông tin
    for kw in GOOGLE_QUERIES:
        if kw.startswith("site:"):
            rss_url = f"https://news.google.com/rss/search?q={quote(kw)}&hl=vi&gl=VN&ceid=VN:vi"
            tasks.append((rss_url, "Google News (Cổng TTĐT)"))

    # Khởi chạy đa luồng với 15 workers (siêu tốc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        executor.map(process_single_feed, tasks)

# ===============================
# MAIN
# ===============================

def run():
    global new_articles_found

    get_updates()

    if not subscribers:
        print("No subscribers.")
        return

    broadcast("🔎 RADAR205 bắt đầu rà soát thông tin hệ thống đa luồng...")

    run_scanners_concurrently()

    if new_articles_found == 0:
        broadcast(
            "📭 Hôm nay không phát hiện nguồn tin mới thuộc phạm vi rà soát bảo vệ lợi ích công cộng.\n\n"
            "Hệ thống tự động tiếp tục chế độ trực chiến."
        )
    else:
        broadcast(f"✅ Hoàn thành rà soát siêu tốc. Phát hiện và xử lý {new_articles_found} thông tin mới.")

if __name__ == "__main__":
    run()
