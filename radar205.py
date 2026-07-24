import os
import json
import hashlib
import concurrent.futures
import threading
import time
import random
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

EXACT_LOCATIONS = [
    "Lào Cai", "Lâm Thượng", "xã Khánh Hòa", "xã Phúc Lợi", "Bảo Ái",
    "Mường Lai", "xã Yên Bình", "Thác Bà", "hồ Thác Bà", 
    "Cảm Nhân", "Lục Yên", "xã Yên Thành", "Tân Lĩnh", "huyện Yên Bình", "Yên Bái"
]

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
            "đào đất", "đào núi", "nổ mìn", "đập đá", "máy nghiền", "đất rừng", "tài sản công", "phá rừng",],
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
    "lấn chiếm", "xả thải", "phá rừng", "vi phạm", "bức xúc",
    "site:thanhtra.gov.vn", "site:vksndtc.gov.vn", "site:tandtc.gov.vn", "site:bocongan.gov.vn", "site:moj.gov.vn" 
]

RSS_SOURCES = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss", "https://dantri.com.vn/rss/home.rss", "https://vietnamnet.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss", "https://thanhnien.vn/rss/home.rss", "https://laodong.vn/rss/home.rss",
    "https://nld.com.vn/rss/home.rss", "https://tienphong.vn/rss/home.rss", "https://plo.vn/rss/home.rss",
    "https://congly.vn/rss/home.rss", "https://baophapluat.vn/rss/home.rss", "https://baovephapluat.vn/rss/home.rss",
    "https://cand.com.vn/rss/su-kien-binh-luan-chu-diem/", "https://nhandan.vn/rss/phap-luat.rss",
    "https://baochinhphu.vn/Rss/xa-hoi.rss", "https://baotintuc.vn/phap-luat.rss", "https://congthuong.vn/rss/phap-luat.rss",
    "https://baoxaydung.com.vn/rss/home.rss", "https://baogiaothong.vn/rss/home.rss", "https://daidoanket.vn/rss/phap-luat.rss",
    "https://vneconomy.vn/rss/home.rss", "https://cafef.vn/trang-chu.rss", "https://cafebiz.vn/trang-chu.rss",
    "https://vietnamfinance.vn/rss/home.rss", "https://baodautu.vn/rss/phap-luat.rss", "https://diendandoanhnghiep.vn/rss/home.rss",
    "https://thoibaotaichinhvietnam.vn/rss/home.rss", "https://nguoiquansat.vn/rss/home.rss", "https://baotainguyenmoitruong.vn/rss/home.rss",
    "https://moitruongvadothi.vn/rss/home.rss", "https://nongnghiep.vn/rss/home.rss", "https://khoahocdoisong.vn/rss/home.rss",
    "https://vietq.vn/rss/home.rss", "https://suckhoedoisong.vn/rss/home.rss", "https://moitruong.net.vn/rss",
    "https://tainguyenvamoitruong.vn/rss/home.rss", "https://soha.vn/thoi-su.rss", "https://www.24h.com.vn/upload/rss/tintuctrongngay.rss",
    "https://kenh14.vn/xa-hoi.rss", "https://kienthuc.net.vn/rss/xa-hoi.rss", "https://www.nguoiduatin.vn/rss/trang-chu.rss",
    "https://1thegioi.vn/rss/home.rss", "https://doisongphapluat.com/rss/home.rss", "https://baolaocai.vn/rss/home.rss"
]

# ===============================
# LOGIC
# ===============================
file_lock = threading.Lock()
new_articles_found = 0

def load_json(f, d): return json.load(open(f, "r", encoding="utf-8")) if os.path.exists(f) else d
def save_json(f, d): json.dump(d, open(f, "w", encoding="utf-8"))

# Cache giờ là danh sách để bảo toàn thứ tự, giới hạn 2000 tin
sent_cache = load_json(CACHE_FILE, [])

def broadcast(m):
    for id in load_json(SUBSCRIBERS_FILE, []):
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": id, "text": m[:4000]})
        except: continue

def process_article(title, content, link, source):
    global new_articles_found
    full = f"{title} {content}".lower()
    locs = [l for l in EXACT_LOCATIONS if l.lower() in full]
    if not locs: return

    score, kws, doms, hints, nq205 = len(locs)*25, [], [], [], False
    for d, r in RULE_ENGINE.items():
        matched = False
        for k in r["keywords"]:
            if k.lower() in full:
                if k not in kws: kws.append(k)
                score += r["score"]
                matched = True
        if matched:
            doms.append(d); hints.append(r["hint"])
            if r["is_nq205"]: nq205 = True

    if score < 45: return
    
    key = hashlib.md5(title.lower()[:80].encode()).hexdigest()
    
    with file_lock:
        if key in sent_cache: return
        sent_cache.append(key)
        # Giới hạn nhớ 2000 tin gần nhất để file không bị quá nặng
        if len(sent_cache) > 2000:
            sent_cache.pop(0) 
        save_json(CACHE_FILE, sent_cache)
        new_articles_found += 1

    lvl = "🔴 RẤT CAO" if score >= 80 else "🟠 CAO" if score >= 60 else "🟡 TRUNG BÌNH"
    alert = (f"🚨 CẢNH BÁO NGUỒN TIN - {lvl}\n\n📍 Địa bàn: {', '.join(sorted(set(locs)))}\n"
             f"🔍 Lĩnh vực: {', '.join(sorted(set(doms)))}\n📈 Điểm AI: {score}\n\n"
             f"🧠 NHẬN ĐỊNH: {'✓ NQ 205' if nq205 else 'Khác'}\n✓ Gợi ý: {' '.join(set(hints))}\n\n"
             f"📰 {title}\n🔗 {link}")
    broadcast(alert)

def process_single_feed(feed_info):
    url, name = feed_info
    time.sleep(random.uniform(1.0, 3.0))
    try:
        f = feedparser.parse(url)
        for e in f.entries[:25]:
            c = getattr(e, "summary", "") + getattr(e, "description", "")
            process_article(e.title, c, e.link, name)
    except: pass

def get_updates():
    telegram_updates = load_json(UPDATES_FILE, {"offset": 0})
    offset = telegram_updates.get("offset", 0)
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}", timeout=20)
        data = r.json()
        if not data.get("ok"): return
        for item in data["result"]:
            telegram_updates["offset"] = item["update_id"] + 1
            msg = item.get("message", {})
            text = msg.get("text", "")
            chat_id = msg.get("chat", {}).get("id")
            if not chat_id: continue
            
            subscribers = load_json(SUBSCRIBERS_FILE, [])
            if text == "/start":
                with file_lock:
                    if chat_id not in subscribers:
                        subscribers.append(chat_id)
                        save_json(SUBSCRIBERS_FILE, subscribers)
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": chat_id, "text": "✅ Đã đăng ký."})
            elif text == "/stop":
                with file_lock:
                    if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                        subscribers.remove(chat_id)
                        save_json(SUBSCRIBERS_FILE, subscribers)
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": chat_id, "text": "⛔ Đã hủy."})
    except: pass
    with file_lock:
        save_json(UPDATES_FILE, telegram_updates)

if __name__ == "__main__":
    get_updates()
    
    # Bổ sung câu chào khi khởi động
    time_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    greeting = (
        f"🤖 [RADAR NQ205] Khởi động hệ thống rà soát tự động...\n"
        f"⏰ Thời gian: {time_str}\n"
        f"🔎 Đang tiến hành quét đa luồng trên 60+ nguồn tin báo chí và cổng thông tin..."
    )
    broadcast(greeting)

    tasks = [(u, "RSS") for u in RSS_SOURCES]
    for l in EXACT_LOCATIONS:
        for k in GOOGLE_QUERIES:
            u = f"https://news.google.com/rss/search?q={quote(f'{l} {k}')}&hl=vi&gl=VN&ceid=VN:vi"
            tasks.append((u, "Google News"))
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as exec:
        exec.map(process_single_feed, list(set(tasks)))
    
    if new_articles_found == 0:
        broadcast("📭 Hôm nay không phát hiện nguồn tin mới thuộc phạm vi NQ 205.\n♻️ Hẹn gặp lại vào ngày mai.")
    else:
        broadcast(f"✅ Hoàn thành rà soát. Đã phát hiện và xử lý {new_articles_found} thông tin mới.")
