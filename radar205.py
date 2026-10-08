import os
import re
import json
import time
import random
import hashlib
import threading
import concurrent.futures
from datetime import datetime, timedelta
from calendar import timegm
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import feedparser

# ===============================
# CONFIG
# ===============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
try:
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID") or "1938209271")
except ValueError:
    ADMIN_CHAT_ID = 1938209271

CACHE_FILE = "radar205_cache.json"
SUBSCRIBERS_FILE = "subscribers.json"
UPDATES_FILE = "telegram_updates.json"

# Chỉ nhận bài trong N ngày gần đây (tránh gửi lại bài cũ do Google News trả về)
MAX_AGE_DAYS = int(os.getenv("MAX_AGE_DAYS", "7"))
# Tối đa số cảnh báo gửi mỗi lần chạy (phần còn lại để lần sau, KHÔNG bị đánh dấu đã gửi)
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "25"))
# Gửi báo cáo tổng kết mỗi lần chạy cho admin (không gửi cho tất cả người đăng ký)
SEND_ADMIN_SUMMARY = os.getenv("SEND_ADMIN_SUMMARY", "1") == "1"

# Thời gian nhớ tin đã gửi
SEEN_KEEP_DAYS = 90
TITLES_KEEP_DAYS = 21
MAX_SEEN = 40000
MAX_TITLES = 5000
# Ngưỡng giống nhau giữa 2 tiêu đề để coi là cùng một vụ việc
SIMILARITY_THRESHOLD = 0.6

MIN_SCORE = 45

EXACT_LOCATIONS = [
    "Lào Cai", "Lâm Thượng", "xã Khánh Hòa", "xã Phúc Lợi", "Bảo Ái",
    "Mường Lai", "xã Yên Bình", "Thác Bà", "hồ Thác Bà",
    "Cảm Nhân", "Lục Yên", "xã Yên Thành", "Tân Lĩnh", "huyện Yên Bình", "Yên Bái"
]

RULE_ENGINE = {
    "Môi trường & Sinh thái": {
        "score": 25,
        "keywords": ["ô nhiễm", "đổ rác bừa bãi", "bột đá", "xả thải", "bụi bặm", "khói bụi", "đá văng",
                     "nước đục", "cá chết", "nước hồ", "nước sông", "nước thải", "bụi mù mịt", "rác thải",
                     "mùi hôi", "bụi trắng", "môi trường"],
        "hint": "Cần xác minh mức độ ảnh hưởng đến cộng đồng dân cư xung quanh (NQ205)."
    },
    "Quản lý Đất đai & Tài nguyên": {
        "score": 25,
        "keywords": ["lấn chiếm đất", "lấn chiếm", "đất công", "khai thác khoáng sản", "mỏ đá", "khai thác cát",
                     "san gạt", "vật liệu xây dựng", "đất hiếm", "đào đất", "đào núi", "nổ mìn", "đập đá",
                     "máy nghiền", "đất rừng", "tài sản công", "phá rừng"],
        "hint": "Kiểm tra tính pháp lý của dự án, ranh giới cấp phép và thiệt hại tài nguyên (NQ205)."
    },
    "Bảo vệ Nhóm yếu thế": {
        "score": 30,
        "keywords": ["bạo hành trẻ em", "xâm hại trẻ em", "người dân tộc thiểu số", "người già neo đơn",
                     "bóc lột lao động", "giấy khai sinh", "người khuyết tật", "trợ cấp", "bạo lực gia đình"],
        "hint": "Cần có biện pháp bảo vệ khẩn cấp quyền và lợi ích hợp pháp của nhóm yếu thế (NQ205)."
    },
    "Tham nhũng & Lợi ích công": {
        "score": 25,
        "keywords": ["tham nhũng", "nhận hối lộ", "tham ô", "chiếm đoạt tài sản", "cán bộ vòi tiền"],
        "hint": "Nghiên cứu hồ sơ xem có yếu tố khởi kiện dân sự đòi bồi thường thiệt hại cho Nhà nước không (NQ205)."
    },
    "An toàn & Tiêu dùng Dân sinh": {
        "score": 20,
        "keywords": ["hàng giả", "thực phẩm bẩn", "ngộ độc", "thuốc giả", "tai nạn lao động"],
        "hint": "Đánh giá số lượng người bị ảnh hưởng để xác định vi phạm lợi ích công cộng (NQ205)."
    },
    # Nhóm "yếu": chỉ cộng điểm, KHÔNG đủ để một bài được gửi nếu đứng một mình
    "Báo chí phản ánh": {
        "score": 5,
        "weak": True,
        "keywords": ["kêu cứu", "bức xúc", "phản ánh", "kiến nghị", "dân khổ", "đe dọa an toàn"],
        "hint": "Đối chiếu nguồn tin với chính quyền cơ sở để xác minh tính khách quan."
    }
}

# Bài chứa các cụm này sẽ bị loại (tin nhiễu không thuộc phạm vi NQ205)
EXCLUDE_PHRASES = [
    "tai nạn giao thông", "va chạm giao thông", "xổ số", "bóng đá", "giá vàng", "chứng khoán",
    "tỷ giá", "dự báo thời tiết", "khuyến mãi", "tuyển sinh", "lịch thi đấu", "kết quả xổ số",
]

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

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Radar205Bot/2.0)"}

# ===============================
# TIỆN ÍCH
# ===============================
file_lock = threading.Lock()


def load_json(f, d):
    try:
        if os.path.exists(f):
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as ex:
        print(f"[WARN] Không đọc được {f}: {ex}")
    return d


def save_json(f, d):
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, f)


def build_pattern(words):
    """Khớp nguyên cụm từ (không khớp nằm giữa từ khác), không phân biệt hoa thường."""
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(w.lower()) for w in words) + r")(?!\w)", re.IGNORECASE)


LOC_PATTERNS = {l: build_pattern([l]) for l in EXACT_LOCATIONS}
KW_PATTERNS = {
    d: {k: build_pattern([k]) for k in r["keywords"]} for d, r in RULE_ENGINE.items()
}
EXCLUDE_PATTERN = build_pattern(EXCLUDE_PHRASES)


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def clean_title(title):
    """Bỏ đuôi ' - Tên báo' mà Google News thêm vào để so sánh tiêu đề chính xác hơn."""
    t = strip_html(title)
    t = re.sub(r"\s+[-–—|]\s+[^-–—|]{2,50}$", "", t)
    return t.strip()


def title_tokens(title):
    return frozenset(re.findall(r"\w+", clean_title(title).lower()))


def similar(a, b):
    if not a or not b:
        return False
    inter = len(a & b)
    if inter == 0:
        return False
    # Jaccard và độ phủ của tiêu đề ngắn hơn
    jac = inter / len(a | b)
    cover = inter / min(len(a), len(b))
    return jac >= SIMILARITY_THRESHOLD or (cover >= 0.85 and min(len(a), len(b)) >= 6)


def normalize_link(link):
    try:
        p = urlsplit(link.strip())
        host = p.netloc.lower().replace("www.", "")
        # Google News: giữ đường dẫn bài viết, bỏ tham số
        return urlunsplit(("https", host, p.path.rstrip("/"), "", ""))
    except Exception:
        return link.strip()


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def keys_for(title, link):
    ct = clean_title(title).lower()
    return {
        "L:" + md5(normalize_link(link)),
        "T:" + md5(re.sub(r"\W+", " ", ct).strip()),
        md5(title.lower()[:80]),  # khóa kiểu cũ -> tương thích cache cũ
    }


def entry_time(e):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(e, attr, None)
        if t:
            try:
                return datetime.utcfromtimestamp(timegm(t))
            except Exception:
                pass
    return None


# ===============================
# CACHE (lưu theo THỜI GIAN, không cắt cứng 2000 mục)
# ===============================
def load_cache():
    raw = load_json(CACHE_FILE, {})
    now = time.time()
    if isinstance(raw, list):  # cache cũ: danh sách md5
        raw = {"seen": {k: now for k in raw}, "titles": []}
    seen = raw.get("seen", {}) if isinstance(raw, dict) else {}
    titles = raw.get("titles", []) if isinstance(raw, dict) else []
    return seen, titles


def prune_and_save_cache(seen, titles):
    now = time.time()
    seen = {k: ts for k, ts in seen.items() if now - ts < SEEN_KEEP_DAYS * 86400}
    if len(seen) > MAX_SEEN:
        seen = dict(sorted(seen.items(), key=lambda x: x[1], reverse=True)[:MAX_SEEN])
    titles = [t for t in titles if now - t["ts"] < TITLES_KEEP_DAYS * 86400][-MAX_TITLES:]
    save_json(CACHE_FILE, {"seen": seen, "titles": titles})


seen_keys, seen_titles = load_cache()
seen_title_tokens = [(frozenset(t["t"].split()), t["ts"]) for t in seen_titles]

candidates = []  # các bài đạt điều kiện trong lần chạy này
seen_in_run_keys = set()
cand_lock = threading.Lock()


def is_duplicate(keys, tokens):
    """Đã gửi trước đây hoặc đã gặp trong lần chạy này (kể cả khác tiêu đề nhưng cùng vụ việc)."""
    if keys & seen_keys.keys() or keys & seen_in_run_keys:
        return True
    for tk, _ in seen_title_tokens:
        if similar(tokens, tk):
            return True
    for c in candidates:
        if similar(tokens, c["tokens"]):
            return True
    return False


# ===============================
# TELEGRAM
# ===============================
def tg_send(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(3):
        try:
            r = requests.post(url, data={"chat_id": chat_id, "text": text[:4000]}, timeout=20)
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 3)
                time.sleep(min(wait + 1, 30))
                continue
            return r.ok
        except Exception:
            time.sleep(1.5)
    return False


def subscribers_list():
    subs = load_json(SUBSCRIBERS_FILE, [])
    return list(dict.fromkeys(subs))  # bỏ trùng, giữ thứ tự


def broadcast(m):
    for cid in subscribers_list():
        tg_send(cid, m)
        time.sleep(0.05)


# ===============================
# PHÂN TÍCH BÀI VIẾT
# ===============================
def analyze(title, content):
    text = f"{title} {content}"
    if EXCLUDE_PATTERN.search(text):
        return None

    locs = [l for l, p in LOC_PATTERNS.items() if p.search(text)]
    if not locs:
        return None

    score = min(len(locs), 2) * 25  # tối đa 2 địa danh được tính điểm
    kws, doms, hints, strong = [], [], [], False
    for d, r in RULE_ENGINE.items():
        matched = [k for k, p in KW_PATTERNS[d].items() if p.search(text)]
        if not matched:
            continue
        score += r["score"] * min(len(matched), 2)  # mỗi lĩnh vực tối đa 2 từ khóa
        kws.extend(matched)
        doms.append(d)
        hints.append(r["hint"])
        if not r.get("weak"):
            strong = True

    # BẮT BUỘC có ít nhất 1 lĩnh vực chính (không chỉ nhắc địa danh hoặc chỉ "phản ánh/bức xúc")
    if not strong or score < MIN_SCORE:
        return None
    return {"locs": locs, "kws": kws, "doms": doms, "hints": hints, "score": score}


def process_article(title, content, link):
    title = strip_html(title)
    content = strip_html(content)
    res = analyze(title, content)
    if not res:
        return
    keys = keys_for(title, link)
    tokens = title_tokens(title)
    with cand_lock:
        if is_duplicate(keys, tokens):
            return
        seen_in_run_keys.update(keys)
        candidates.append({"title": clean_title(title) or title, "link": link, "keys": keys,
                           "tokens": tokens, **res})


def fetch_feed(url):
    r = requests.get(url, headers=HTTP_HEADERS, timeout=20)
    r.raise_for_status()
    return feedparser.parse(r.content)


def process_single_feed(feed_info):
    url, name = feed_info
    time.sleep(random.uniform(0.5, 2.0))
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    try:
        f = fetch_feed(url)
        for e in f.entries[:30]:
            title = getattr(e, "title", "") or ""
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue
            dt = entry_time(e)
            if dt and dt < cutoff:
                continue  # bài cũ
            c = (getattr(e, "summary", "") or "") + " " + (getattr(e, "description", "") or "")
            process_article(title, c, link)
    except Exception as ex:
        print(f"[WARN] Lỗi nguồn {name}: {url[:80]} -> {type(ex).__name__}")


def build_alert(c):
    lvl = "🔴 RẤT CAO" if c["score"] >= 80 else "🟠 CAO" if c["score"] >= 60 else "🟡 TRUNG BÌNH"
    hints = list(dict.fromkeys(c["hints"]))
    return (
        f"🚨 NGUỒN TIN NQ 205 - {lvl} ({c['score']} điểm)\n\n"
        f"📰 {c['title']}\n\n"
        f"📍 Địa bàn: {', '.join(sorted(set(c['locs'])))}\n"
        f"🔍 Lĩnh vực: {', '.join(c['doms'])}\n"
        f"🏷️ Từ khóa: {', '.join(dict.fromkeys(c['kws']))}\n"
        f"✓ Gợi ý: {' '.join(hints)}\n\n"
        f"🔗 {c['link']}"
    )


# ===============================
# NHẬN LỆNH TELEGRAM
# ===============================
def get_updates():
    state = load_json(UPDATES_FILE, {"offset": 0})
    offset = state.get("offset", 0)
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                         params={"offset": offset, "timeout": 0}, timeout=20)
        data = r.json()
        if not data.get("ok"):
            return
        subscribers = subscribers_list()
        for item in data["result"]:
            state["offset"] = item["update_id"] + 1
            msg = item.get("message", {}) or {}
            text = (msg.get("text") or "").strip().split("@")[0]
            chat_id = (msg.get("chat") or {}).get("id")
            if not chat_id:
                continue
            if text == "/start":
                if chat_id not in subscribers:
                    subscribers.append(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)
                tg_send(chat_id, "✅ Đã đăng ký nhận tin.")
            elif text == "/stop":
                if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                    subscribers.remove(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)
                tg_send(chat_id, "⛔ Đã hủy đăng ký.")
    except Exception as ex:
        print(f"[WARN] getUpdates lỗi: {type(ex).__name__}")
    finally:
        save_json(UPDATES_FILE, state)


# ===============================
# MAIN
# ===============================
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise SystemExit("Thiếu TELEGRAM_TOKEN")

    started = datetime.now()
    get_updates()

    tasks = [(u, "RSS") for u in RSS_SOURCES]
    for l in EXACT_LOCATIONS:
        for k in GOOGLE_QUERIES:
            q = f"{l} {k} when:{MAX_AGE_DAYS}d"
            u = f"https://news.google.com/rss/search?q={quote(q)}&hl=vi&gl=VN&ceid=VN:vi"
            tasks.append((u, "Google News"))
    tasks = list(dict.fromkeys(tasks))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(process_single_feed, tasks))

    # Ưu tiên bài điểm cao, chỉ gửi tối đa MAX_ALERTS_PER_RUN
    candidates.sort(key=lambda c: c["score"], reverse=True)
    to_send = candidates[:MAX_ALERTS_PER_RUN]

    now = time.time()
    for c in to_send:
        broadcast(build_alert(c))
        # Chỉ đánh dấu "đã gửi" những bài thực sự đã gửi
        for k in c["keys"]:
            seen_keys[k] = now
        seen_titles.append({"t": " ".join(sorted(c["tokens"])), "ts": now})
        seen_title_tokens.append((c["tokens"], now))

    prune_and_save_cache(seen_keys, seen_titles)

    sent = len(to_send)
    pending = len(candidates) - sent
    print(f"Đã quét {len(tasks)} nguồn, gửi {sent} tin, còn chờ {pending} tin.")

    # Chỉ báo cáo cho admin, KHÔNG làm phiền các thành viên khác
    if SEND_ADMIN_SUMMARY:
        dur = int((datetime.now() - started).total_seconds())
        tg_send(
            ADMIN_CHAT_ID,
            f"🤖 Radar NQ205 đã chạy xong ({started.strftime('%d/%m/%Y %H:%M')}, {dur}s)\n"
            f"• Nguồn đã quét: {len(tasks)}\n• Tin mới đã gửi: {sent}\n"
            f"• Tin còn chờ lần sau: {pending}\n• Người đăng ký: {len(subscribers_list())}"
        )
