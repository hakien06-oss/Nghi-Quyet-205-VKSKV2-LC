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

MIN_SCORE = 50

# 11 xã thuộc địa bàn VKSND khu vực 2, tỉnh Lào Cai
# ambiguous=True: tên trùng với nơi khác trong cả nước -> chỉ nhận khi viết "xã <tên>"
#                 hoặc bài có nhắc Lào Cai / Yên Bái / Lục Yên / Thác Bà / huyện Yên Bình
COMMUNES = {
    "Lâm Thượng": {"aliases": ["Lâm Thượng"], "ambiguous": False},
    "xã Khánh Hòa":  {"aliases": ["Khánh Hòa"], "ambiguous": True},
    "xã Phúc Lợi":   {"aliases": ["Phúc Lợi"], "ambiguous": True},
    "Bảo Ái":     {"aliases": ["Bảo Ái"], "ambiguous": False},
    "Mường Lai":  {"aliases": ["Mường Lai"], "ambiguous": False},
    "Yên Bình":   {"aliases": ["Yên Bình"], "ambiguous": True},
    "Thác Bà":    {"aliases": ["Thác Bà"], "ambiguous": False},
    "Cảm Nhân":   {"aliases": ["Cảm Nhân", "Cảm Ân"], "ambiguous": False},
    "Lục Yên":    {"aliases": ["Lục Yên"], "ambiguous": False},
    "Yên Thành":  {"aliases": ["Yên Thành"], "ambiguous": True},
    "Tân Lĩnh":   {"aliases": ["Tân Lĩnh"], "ambiguous": True},
}
# Từ nhận diện vùng, chỉ dùng để xác nhận các tên xã dễ trùng (KHÔNG tính là địa bàn)
REGION_CONTEXT = ["Lào Cai", "Yên Bái", "Lục Yên", "Thác Bà", "huyện Yên Bình"]

# Phạm vi Nghị quyết 205/2025/QH15:
#  (1) Nhóm dễ bị tổn thương
#  (2) Lợi ích công ở 6 lĩnh vực: đầu tư công; đất đai, tài nguyên, tài sản công; môi trường, hệ sinh thái;
#      di sản văn hóa; an toàn thực phẩm, dược phẩm; quyền lợi người tiêu dùng
RULE_ENGINE = {
    "Nhóm dễ bị tổn thương": {
        "score": 30,
        "keywords": ["bạo hành trẻ em", "xâm hại trẻ em", "trẻ bị bỏ rơi", "trẻ mồ côi", "người già neo đơn",
                     "người cao tuổi bị bỏ rơi", "neo đơn", "người yếu thế", "nhóm dễ bị tổn thương",
                     "người mất năng lực hành vi", "bị bạo hành", "bị xâm hại", "bị bóc lột", "bóc lột lao động",
                     "bạo lực gia đình", "mua bán người", "không nơi nương tựa", "người khuyết tật bị"],
        "hint": "Xem xét điều kiện VKSND khởi kiện bảo vệ quyền dân sự của người thuộc nhóm dễ bị tổn thương khi họ không thể tự khởi kiện (NQ205)."
    },
    "Môi trường, hệ sinh thái": {
        "score": 25,
        "keywords": ["ô nhiễm", "ô nhiễm môi trường", "đổ rác bừa bãi", "bột đá", "xả thải", "bụi bặm", "khói bụi",
                     "đá văng", "nước đục", "cá chết", "nước thải", "bụi mù mịt", "rác thải", "mùi hôi",
                     "bụi trắng", "hệ sinh thái", "suy thoái môi trường"],
        "hint": "Xác minh mức độ ảnh hưởng đến cộng đồng và hệ sinh thái; xem xét khởi kiện bảo vệ lợi ích công (NQ205)."
    },
    "Đất đai, tài nguyên, tài sản công": {
        "score": 25,
        "keywords": ["lấn chiếm đất", "lấn chiếm", "đất công", "khai thác khoáng sản", "mỏ đá", "khai thác cát",
                     "san gạt", "đất hiếm", "đào núi", "nổ mìn", "đập đá", "máy nghiền", "đất rừng",
                     "tài sản công", "phá rừng", "khai thác trái phép", "khai thác tài nguyên"],
        "hint": "Kiểm tra tính pháp lý, ranh giới cấp phép và thiệt hại tài nguyên, tài sản công (NQ205)."
    },
    "Đầu tư công": {
        "score": 25,
        "keywords": ["đầu tư công", "vốn đầu tư công", "thất thoát vốn", "lãng phí vốn", "vốn ngân sách",
                     "dự án chậm tiến độ"],
        "hint": "Đánh giá thiệt hại, thất thoát vốn đầu tư công và trách nhiệm khởi kiện của cơ quan có thẩm quyền (NQ205)."
    },
    "Di sản văn hóa": {
        "score": 25,
        "keywords": ["di sản văn hóa", "di tích", "di tích lịch sử", "cổ vật", "xâm hại di tích", "lấn chiếm di tích"],
        "hint": "Xác định hành vi xâm hại di sản văn hóa và thiệt hại đối với lợi ích công (NQ205)."
    },
    "An toàn thực phẩm, dược phẩm": {
        "score": 25,
        "keywords": ["an toàn thực phẩm", "thực phẩm bẩn", "thực phẩm giả", "thực phẩm kém chất lượng",
                     "ngộ độc", "hàng giả", "thuốc giả", "dược phẩm", "thuốc kém chất lượng"],
        "hint": "Đánh giá số lượng người bị ảnh hưởng để xác định vi phạm lợi ích công cộng (NQ205)."
    },
    "Quyền lợi người tiêu dùng": {
        "score": 20,
        "keywords": ["quyền lợi người tiêu dùng", "người tiêu dùng", "hàng kém chất lượng", "hàng nhái",
                     "lừa dối khách hàng", "quảng cáo sai sự thật"],
        "hint": "Xem xét dấu hiệu xâm phạm quyền lợi của số đông người tiêu dùng (NQ205)."
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

# Từ khóa tìm kiếm Google News: chỉ các chủ đề thuộc NQ205 (đã bỏ các truy vấn site: và từ chung chung)
GOOGLE_QUERIES = [
    "ô nhiễm môi trường", "xả thải", "khai thác khoáng sản", "mỏ đá", "lấn chiếm đất", "phá rừng",
    "đầu tư công", "di tích", "an toàn thực phẩm", "hàng giả", "bạo hành", "người yếu thế", "bức xúc",
]

# Lời chào / lời kết (sửa tại đây nếu muốn đổi nội dung)
GREETING = (
    "Xin chào !"
    "Đây là công cụ tự động tìm kiếm nguồn thông tin liên quan đến Nghị quyết 205 của Viện kiểm sát nhân dân khu vực 2, tỉnh Lào Cai"
)
CLOSING = (
    "Trên đây là kết quả rà soát, tìm kiếm nguôn thông tin liên quan NQ 205 của ngày hôm nay !"
)

# ---- LỚP 1: RSS trực tiếp (nhanh, lấy tin mới nhất của từng chuyên mục) ----
RSS_SOURCES = [
    # Báo tổng hợp, thời sự, xã hội
    "https://vnexpress.net/rss/tin-moi-nhat.rss", "https://vnexpress.net/rss/thoi-su.rss",
    "https://vnexpress.net/rss/phap-luat.rss", "https://vnexpress.net/rss/doi-song.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss", "https://tuoitre.vn/rss/thoi-su.rss", "https://tuoitre.vn/rss/phap-luat.rss",
    "https://thanhnien.vn/rss/home.rss", "https://thanhnien.vn/rss/thoi-su.rss", "https://thanhnien.vn/rss/doi-song.rss",
    "https://dantri.com.vn/rss/home.rss", "https://dantri.com.vn/rss/xa-hoi.rss", "https://dantri.com.vn/rss/phap-luat.rss",
    "https://vietnamnet.vn/rss/home.rss", "https://vietnamnet.vn/rss/thoi-su.rss", "https://vietnamnet.vn/rss/phap-luat.rss",
    "https://laodong.vn/rss/home.rss", "https://laodong.vn/rss/xa-hoi.rss", "https://laodong.vn/rss/phap-luat.rss",
    "https://nld.com.vn/rss/home.rss", "https://tienphong.vn/rss/home.rss", "https://plo.vn/rss/home.rss",
    "https://zingnews.vn/rss/xa-hoi.rss", "https://vtv.vn/trong-nuoc.rss", "https://vov.vn/rss/xa-hoi-2.rss",
    "https://www.vietnamplus.vn/rss/xahoi.rss",
    # Pháp luật, an ninh
    "https://congly.vn/rss/home.rss", "https://baophapluat.vn/rss/home.rss", "https://baovephapluat.vn/rss/home.rss",
    "https://cand.com.vn/rss/su-kien-binh-luan-chu-diem/", "https://nhandan.vn/rss/phap-luat.rss",
    "https://baochinhphu.vn/Rss/xa-hoi.rss", "https://baotintuc.vn/phap-luat.rss", "https://congthuong.vn/rss/phap-luat.rss",
    "https://daidoanket.vn/rss/phap-luat.rss", "https://baodautu.vn/rss/phap-luat.rss", "https://doisongphapluat.com/rss/home.rss",
    "https://anninhthudo.vn/rss/home.rss", "https://kiemsat.vn/rss/home.rss", "https://phapluatxahoi.vn/rss/home.rss",
    # Môi trường, tài nguyên, nông nghiệp, xây dựng, giao thông
    "https://baotainguyenmoitruong.vn/rss/home.rss", "https://moitruongvadothi.vn/rss/home.rss",
    "https://tainguyenvamoitruong.vn/rss/home.rss", "https://moitruong.net.vn/rss", "https://tapchimoitruong.vn/rss/home.rss",
    "https://nongnghiep.vn/rss/home.rss", "https://baoxaydung.com.vn/rss/home.rss", "https://baogiaothong.vn/rss/home.rss",
    "https://khoahocdoisong.vn/rss/home.rss", "https://kinhtemoitruong.vn/rss/home.rss",
    # Sức khỏe, đời sống, tiêu dùng, văn hóa
    "https://suckhoedoisong.vn/rss/home.rss", "https://vietq.vn/rss/home.rss", "https://soha.vn/thoi-su.rss",
    "https://www.24h.com.vn/upload/rss/tintuctrongngay.rss", "https://kenh14.vn/xa-hoi.rss",
    "https://kienthuc.net.vn/rss/xa-hoi.rss", "https://www.nguoiduatin.vn/rss/trang-chu.rss", "https://1thegioi.vn/rss/home.rss",
    "https://giadinh.net.vn/rss/home.rss", "https://baovanhoa.vn/rss/home.rss", "https://phunuvietnam.vn/rss/home.rss",
    # Kinh tế, đầu tư (liên quan đầu tư công, dự án)
    "https://vneconomy.vn/rss/home.rss", "https://cafef.vn/trang-chu.rss", "https://cafebiz.vn/trang-chu.rss",
    "https://vietnamfinance.vn/rss/home.rss", "https://diendandoanhnghiep.vn/rss/home.rss",
    "https://thoibaotaichinhvietnam.vn/rss/home.rss", "https://nguoiquansat.vn/rss/home.rss", "https://kinhtedothi.vn/rss/home.rss",
    # Báo địa phương Lào Cai, Yên Bái và các tỉnh lân cận
    "https://baolaocai.vn/rss/home.rss", "https://baoyenbai.com.vn/rss/home.rss",
    "https://baothainguyen.vn/rss/home.rss", "https://baophutho.vn/rss/home.rss", "https://baotuyenquang.com.vn/rss/home.rss",
    "https://baohagiang.vn/rss/home.rss", "https://baocaobang.vn/rss/home.rss", "https://baolangson.vn/rss/home.rss",
    "https://baosonla.org.vn/rss/home.rss", "https://baodienbienphu.com.vn/rss/home.rss", "https://baolaichau.vn/rss/home.rss",
    "https://baodantoc.vn/rss/home.rss",
]

# ---- LỚP 2: ~100 đầu báo, quét qua Google News theo "site:<tên miền>" + tên 11 xã ----
# Không phụ thuộc đường dẫn RSS nên báo nào không có RSS (hoặc đổi RSS) vẫn không bị sót.
NEWS_DOMAINS = [
    # Báo trung ương, tổng hợp
    "vnexpress.net", "tuoitre.vn", "thanhnien.vn", "dantri.com.vn", "vietnamnet.vn", "zingnews.vn", "znews.vn",
    "laodong.vn", "nld.com.vn", "tienphong.vn", "nhandan.vn", "qdnd.vn", "vov.vn", "vtv.vn", "vtc.vn",
    "vietnamplus.vn", "baotintuc.vn", "baochinhphu.vn", "dangcongsan.vn", "tapchicongsan.org.vn", "quochoi.vn",
    "baodantoc.vn", "soha.vn", "kenh14.vn", "24h.com.vn", "kienthuc.net.vn", "nguoiduatin.vn", "1thegioi.vn",
    "giaoducthoidai.vn", "giadinh.net.vn", "phunuvietnam.vn", "toquoc.vn", "baodansinh.vn", "vnanet.vn",
    "baomoi.com", "sggp.org.vn", "hanoimoi.vn", "thoidai.com.vn", "baoquocte.vn",
    # Pháp luật, an ninh
    "baophapluat.vn", "plo.vn", "congly.vn", "cand.com.vn", "baovephapluat.vn", "phapluatxahoi.vn",
    "doisongphapluat.com", "anninhthudo.vn", "kiemsat.vn", "tapchitoaan.vn", "thanhtra.com.vn",
    "vksndtc.gov.vn", "tandtc.gov.vn", "thanhtra.gov.vn", "moj.gov.vn", "bocongan.gov.vn",
    # Môi trường, tài nguyên, nông nghiệp, xây dựng, giao thông, sức khỏe, văn hóa
    "baotainguyenmoitruong.vn", "moitruong.net.vn", "tapchimoitruong.vn", "tainguyenvamoitruong.vn",
    "moitruongvadothi.vn", "kinhtemoitruong.vn", "nongnghiep.vn", "nongnghiepmoitruong.vn", "nongthonviet.com.vn",
    "baoxaydung.com.vn", "baoxaydung.vn", "baogiaothong.vn", "khoahocdoisong.vn", "vietq.vn",
    "suckhoedoisong.vn", "baovanhoa.vn", "tapchicongthuong.vn",
    # Kinh tế, đầu tư
    "vneconomy.vn", "cafef.vn", "cafebiz.vn", "baodautu.vn", "congthuong.vn", "kinhtedothi.vn",
    "vietnamfinance.vn", "diendandoanhnghiep.vn", "thoibaotaichinhvietnam.vn", "nguoiquansat.vn", "daidoanket.vn",
    # Địa phương: Lào Cai, Yên Bái và các tỉnh lân cận
    "baolaocai.vn", "baoyenbai.com.vn", "laocai.gov.vn", "yenbai.gov.vn", "baothainguyen.vn", "baophutho.vn",
    "baotuyenquang.com.vn", "baohagiang.vn", "baocaobang.vn", "baolangson.vn", "baobackan.vn",
    "baodienbienphu.com.vn", "baosonla.org.vn", "baolaichau.vn", "baohoabinh.com.vn", "baoquangninh.vn",
    "baobacgiang.vn", "baobacninh.com.vn", "baovinhphuc.com.vn",
]
NEWS_DOMAINS = list(dict.fromkeys(NEWS_DOMAINS))

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


COMMUNE_PATTERNS = {}
for _name, _info in COMMUNES.items():
    COMMUNE_PATTERNS[_name] = {
        "bare": build_pattern(_info["aliases"]),
        "explicit": re.compile(
            r"(?<!\w)(xã|phường|thị trấn)\s+(" + "|".join(re.escape(a) for a in _info["aliases"]) + r")(?!\w)",
            re.IGNORECASE),
        "ambiguous": _info["ambiguous"],
    }
REGION_PATTERN = build_pattern(REGION_CONTEXT)


def find_communes(text):
    found = []
    has_region = None
    for name, p in COMMUNE_PATTERNS.items():
        if not p["bare"].search(text):
            continue
        if not p["ambiguous"] or p["explicit"].search(text):
            found.append(name)
            continue
        # Tên dễ trùng: cần có từ nhận diện vùng khác chính nó
        if has_region is None:
            has_region = {m.group(1).lower() for m in REGION_PATTERN.finditer(text)}
        own = {a.lower() for a in COMMUNES[name]["aliases"]}
        if has_region - own:
            found.append(name)
    return found


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
    save_json(CACHE_FILE, {"seen": seen, "titles": titles, "feed_fail": feed_fail})


seen_keys, seen_titles = load_cache()
_raw_cache = load_json(CACHE_FILE, {})
feed_fail = dict(_raw_cache.get("feed_fail", {})) if isinstance(_raw_cache, dict) else {}
feed_stats = {}  # url -> "ok" | "empty" | "fail" (chỉ trong lần chạy này)
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

    locs = find_communes(text)
    if not locs:
        return None  # không thuộc 11 xã -> bỏ

    score = 30  # điểm địa bàn (cố định, không cộng dồn theo số xã)
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

    # BẮT BUỘC thuộc ít nhất 1 đối tượng/lĩnh vực của NQ205 (không chỉ "phản ánh/bức xúc")
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
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HTTP_HEADERS, timeout=25)
            if r.status_code in (429, 503):  # bị giới hạn tốc độ -> chờ rồi thử lại
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(6 * (attempt + 1))
                continue
            r.raise_for_status()
            return feedparser.parse(r.content)
        except requests.RequestException as ex:
            last = ex
            time.sleep(2)
    raise last or RuntimeError("không tải được")


def process_single_feed(feed_info):
    url, name = feed_info
    time.sleep(random.uniform(0.5, 1.5))
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    is_google = "news.google.com" in url
    try:
        f = fetch_feed(url)
        n = len(f.entries)
        # RSS trực tiếp mà không có bài nào => nghi hỏng/đổi đường dẫn. Google News rỗng là bình thường.
        feed_stats[url] = "empty" if (n == 0 and not is_google) else "ok"
        for e in f.entries[:60]:
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
        feed_stats[url] = "fail"
        print(f"[WARN] Lỗi nguồn {name}: {url[:90]} -> {type(ex).__name__}")


def build_alert(c, idx=1, total=1):
    lvl = "🔴 RẤT CAO" if c["score"] >= 85 else "🟠 CAO" if c["score"] >= 65 else "🟡 TRUNG BÌNH"
    hints = list(dict.fromkeys(c["hints"]))
    return (
        f"🚨 NGUỒN TIN {idx}/{total} - {lvl} ({c['score']} điểm)\n\n"
        f"📰 {c['title']}\n\n"
        f"📍 Địa bàn (xã): {', '.join(sorted(set(c['locs'])))}\n"
        f"🔍 Đối tượng/lĩnh vực NQ205: {', '.join(c['doms'])}\n"
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
    # (a) Từng xã x từng chủ đề NQ205
    for l, info in COMMUNES.items():
        place = f"{l} Lào Cai" if info["ambiguous"] else l
        for k in GOOGLE_QUERIES:
            q = f"{place} {k} when:{MAX_AGE_DAYS}d"
            u = f"https://news.google.com/rss/search?q={quote(q)}&hl=vi&gl=VN&ceid=VN:vi"
            tasks.append((u, "Google News"))
    # (b) Từng đầu báo x tên 11 xã (bao phủ cả báo không có RSS)
    all_names = [a for info in COMMUNES.values() for a in info["aliases"]]
    names_q = " OR ".join(f'"{a}"' for a in all_names)
    for d in NEWS_DOMAINS:
        q = f"site:{d} ({names_q}) when:{MAX_AGE_DAYS}d"
        u = f"https://news.google.com/rss/search?q={quote(q)}&hl=vi&gl=VN&ceid=VN:vi"
        tasks.append((u, f"site:{d}"))
    tasks = list(dict.fromkeys(tasks))

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(process_single_feed, tasks))

    # Ưu tiên bài điểm cao, chỉ gửi tối đa MAX_ALERTS_PER_RUN
    candidates.sort(key=lambda c: c["score"], reverse=True)
    to_send = candidates[:MAX_ALERTS_PER_RUN]

    now = time.time()
    time_str = started.strftime("%H:%M ngày %d/%m/%Y")
    sent = len(to_send)

    if sent == 0:
        # Không có tin: gộp chào + thông báo + kết thành 1 tin nhắn duy nhất để tránh làm phiền
        broadcast(f"{GREETING}\n\n⏰ Thời điểm rà soát: {time_str}\n"
                  f"📭 Lần này chưa phát hiện nguồn tin mới thuộc phạm vi NQ 205 trên địa bàn.\n\n{CLOSING}")
    else:
        broadcast(f"{GREETING}\n\n⏰ Thời điểm rà soát: {time_str}\n"
                  f"📌 Phát hiện {sent} nguồn tin mới. Chi tiết như sau:")
        for i, c in enumerate(to_send, 1):
            broadcast(build_alert(c, i, sent))
            # Chỉ đánh dấu "đã gửi" những bài thực sự đã gửi
            for k in c["keys"]:
                seen_keys[k] = now
            seen_titles.append({"t": " ".join(sorted(c["tokens"])), "ts": now})
            seen_title_tokens.append((c["tokens"], now))
            prune_and_save_cache(seen_keys, seen_titles)  # lưu ngay, phòng khi bị ngắt giữa chừng
        extra = len(candidates) - sent
        tail = f"\n(Còn {extra} tin sẽ được gửi ở lần rà soát sau.)" if extra > 0 else ""
        broadcast(f"✅ Đã gửi {sent} nguồn tin.{tail}\n\n{CLOSING}")

    # Cập nhật bộ đếm lỗi của RSS trực tiếp (Google News không tính theo từng URL)
    rss_set = set(RSS_SOURCES)
    for u in rss_set:
        st = feed_stats.get(u)
        if st == "ok":
            feed_fail.pop(u, None)
        elif st in ("empty", "fail"):
            feed_fail[u] = feed_fail.get(u, 0) + 1
    for u in list(feed_fail):
        if u not in rss_set:
            feed_fail.pop(u)
    g_total = sum(1 for u in feed_stats if "news.google.com" in u)
    g_fail = sum(1 for u, st in feed_stats.items() if "news.google.com" in u and st == "fail")
    rss_total = len(rss_set)
    rss_bad_now = [u for u in rss_set if feed_stats.get(u) in ("empty", "fail")]
    rss_dead = sorted(u for u, n in feed_fail.items() if n >= 3)

    prune_and_save_cache(seen_keys, seen_titles)

    pending = len(candidates) - sent
    print(f"Đã quét {len(tasks)} nguồn, gửi {sent} tin, còn chờ {pending} tin.")

    # Chỉ báo cáo cho admin, KHÔNG làm phiền các thành viên khác
    if SEND_ADMIN_SUMMARY:
        dur = int((datetime.now() - started).total_seconds())
        msg = (
            f"🤖 Radar NQ205 đã chạy xong ({started.strftime('%d/%m/%Y %H:%M')}, {dur}s)\n"
            f"• Tổng truy vấn: {len(tasks)} (RSS trực tiếp: {rss_total}, Google News: {g_total}, "
            f"phủ {len(NEWS_DOMAINS)} đầu báo)\n"
            f"• Tin mới đã gửi: {sent}\n• Tin còn chờ lần sau: {pending}\n"
            f"• Người đăng ký: {len(subscribers_list())}\n"
            f"• RSS lỗi/rỗng lần này: {len(rss_bad_now)}/{rss_total} | Google News lỗi: {g_fail}/{g_total}"
        )
        if g_total and g_fail / g_total > 0.3:
            msg += "\n⚠️ Google News lỗi nhiều (có thể bị giới hạn tốc độ), nên chạy lại sau ít phút."
        if rss_dead:
            msg += "\n\n🛠️ RSS hỏng liên tiếp ≥3 lần (nên xóa/thay đường dẫn, các báo này vẫn được quét qua Google News):\n"
            msg += "\n".join(f"- {u}" for u in rss_dead[:15])
            if len(rss_dead) > 15:
                msg += f"\n... và {len(rss_dead) - 15} nguồn khác"
        tg_send(ADMIN_CHAT_ID, msg)
