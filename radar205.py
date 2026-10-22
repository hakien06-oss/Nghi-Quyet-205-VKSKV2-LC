import os
import re
import sys
import json
import time
import random
import hashlib
import threading
import concurrent.futures
from datetime import datetime, timedelta, timezone
import html as htmllib
from calendar import timegm
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import feedparser

# Giải mã link Google News (news.google.com/rss/articles/...) về địa chỉ bài gốc để đọc nội dung.
# Cài bằng: pip install googlenewsdecoder  (đã thêm vào requirements.txt)
try:
    from googlenewsdecoder import gnewsdecoder
except Exception:
    gnewsdecoder = None

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

# --- Bài CẤP TỈNH: nhắc Lào Cai/Yên Bái nhưng không nêu tên xã ---
# Vẫn được gửi nếu có từ khóa "mạnh" của NQ205, nhưng điểm nền thấp hơn bài có tên xã
# và được gắn nhãn "cấp tỉnh - cần xác minh địa bàn".
PROVINCE_CONTEXT = ["Lào Cai", "Yên Bái"]
PROVINCE_BASE_SCORE = int(os.getenv("PROVINCE_BASE_SCORE", "25"))

# --- Bài NÓI TRỰC TIẾP VỀ NQ205 (tuyên truyền, hướng dẫn, kết quả thí điểm...) ---
# Không đòi tên xã. Tắt bằng biến môi trường NQ205_DIRECT=0
NQ205_DIRECT_ENABLED = os.getenv("NQ205_DIRECT", "1") == "1"
NQ205_DIRECT_BASE_SCORE = 20
NQ205_DIRECT = {
    "name": "Nội dung trực tiếp về NQ205",
    "score": 40,
    "keywords": [
        "205/2025/QH15", "Nghị quyết 205/2025", "Nghị quyết số 205/2025",
        "Nghị quyết 205 của Quốc hội", "Nghị quyết số 205 của Quốc hội",
        "viện kiểm sát khởi kiện", "viện kiểm sát nhân dân khởi kiện",
        "kiểm sát viên khởi kiện", "thí điểm viện kiểm sát",
        "khởi kiện vụ án dân sự bảo vệ lợi ích công",
    ],
    "hint": "Tin về chính Nghị quyết 205/2025/QH15 (chưa gắn địa bàn cụ thể): đối chiếu xem có liên quan địa bàn VKSND KV2 không.",
}

# --- Đọc thêm thân bài khi RSS chỉ có tiêu đề/tóm tắt ngắn ---
# Chỉ áp dụng cho bài RSS trực tiếp (link Google News là link chuyển hướng, không đọc được),
# và chỉ khi tiêu đề/tóm tắt đã có từ khóa mạnh nhưng chưa thấy địa bàn.
DEEP_FETCH = os.getenv("DEEP_FETCH", "1") == "1"
MAX_DEEP_FETCH = int(os.getenv("MAX_DEEP_FETCH", "100"))  # tối đa bài đọc nội dung mỗi lần chạy
DEEP_KEEP_DAYS = 7
DEEP_WORKERS = int(os.getenv("DEEP_WORKERS", "4"))
# Điểm nền khi địa bàn chỉ được suy ra từ truy vấn Google News (tiêu đề/tóm tắt không nêu xã)
HINT_BASE_SCORE = 28
# Số bài tối đa đọc mỗi nguồn RSS
MAX_ENTRIES_PER_FEED = int(os.getenv("MAX_ENTRIES_PER_FEED", "100"))

# Giờ Việt Nam (UTC+7, không có giờ mùa hè) - GitHub Actions chạy giờ UTC nên phải đổi
VN_TZ = timezone(timedelta(hours=7))


def now_vn():
    return datetime.now(VN_TZ)


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.5",
}

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
                     "tài sản công", "phá rừng", "khai thác trái phép", "khai thác tài nguyên",
                     "đá quý", "khai thác đá", "khai thác vàng", "vàng sa khoáng", "khoáng sản",
                     "khoáng sản trái phép", "tận thu khoáng sản", "khai thác đất", "đất san lấp"],
        # Cụm có từ chen giữa, ví dụ "khai thác đá quý trái phép", "khai thác cát sỏi trái phép"
        "regex": [("khai thác … trái phép", r"khai thác\s+(?:\S+\s+){0,4}trái phép")],
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
    "ô nhiễm môi trường", "xả thải", "khai thác khoáng sản", "mỏ đá", "đá quý", "lấn chiếm đất", "phá rừng",
    "đầu tư công", "di tích", "an toàn thực phẩm", "hàng giả", "bạo hành", "người yếu thế", "bức xúc",
]

# Truy vấn riêng cho nội dung NQ205 (chạy cả có và không kèm "Lào Cai")
NQ205_QUERIES = [
    "Nghị quyết 205/2025/QH15", "viện kiểm sát khởi kiện vụ án dân sự",
    "viện kiểm sát khởi kiện bảo vệ lợi ích công",
]

# Lời chào gửi NGAY KHI BẮT ĐẦU quét ({time} được thay bằng giờ Việt Nam)
START_GREETING = (
    "Xin chào! Công cụ tự động tìm kiếm thông tin về Nghị quyết 205 của Viện kiểm sát nhân dân "
    "khu vực 2, tỉnh Lào Cai chuẩn bị rà soát thông tin lúc {time}. Vui lòng chờ trong giây lát..."
)

# Lời chào / lời kết (sửa tại đây nếu muốn đổi nội dung)
GREETING = (
    "Xin chào !"
    "Đây là công cụ tự động tìm kiếm nguồn thông tin liên quan đến Nghị quyết 205 của Viện kiểm sát nhân dân khu vực 2, tỉnh Lào Cai"
)
CLOSING = (
    "Trên đây là kết quả rà soát, tìm kiếm nguồn thông tin liên quan NQ 205 của ngày hôm nay !"
)

# ---- LỚP 1: RSS trực tiếp (nhanh, lấy tin mới nhất của từng chuyên mục) ----
RSS_SOURCES = [
    # Báo tổng hợp, thời sự, xã hội
    "https://vnexpress.net/rss/tin-moi-nhat.rss", "https://vnexpress.net/rss/thoi-su.rss",
    "https://vnexpress.net/rss/phap-luat.rss", "https://vnexpress.net/rss/doi-song.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss", "https://tuoitre.vn/rss/thoi-su.rss", "https://tuoitre.vn/rss/phap-luat.rss",
    "https://thanhnien.vn/rss/home.rss", "https://thanhnien.vn/rss/thoi-su.rss", "https://thanhnien.vn/rss/doi-song.rss",
    "https://dantri.com.vn/rss/home.rss", "https://danviet.vn/rss/home.rss", "https://dantri.com.vn/rss/xa-hoi.rss", "https://dantri.com.vn/rss/phap-luat.rss",
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
    "vnexpress.net", "tuoitre.vn", "thanhnien.vn", "dantri.com.vn", "danviet.vn", "vietnamnet.vn", "zingnews.vn", "znews.vn",
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
NEWS_DOMAINS += [
    "danviet.vn", "infonet.vietnamnet.vn", "vtcnews.vn", "nongthonngaynay.vn", "baodauthau.vn",
    "thuonghieucongluan.com.vn", "doanhnghiephoinhap.vn", "nongnghiephuuco.vn", "mae.gov.vn",
    "baotintuc.vn", "vietnamnet.vn", "tienphong.vn", "nhandan.vn",
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


def _build_kw_patterns(r):
    pats = {k: build_pattern([k]) for k in r["keywords"]}
    for label, rx in r.get("regex", []):
        pats[label] = re.compile(r"(?<!\w)(?:" + rx + r")(?!\w)", re.IGNORECASE)
    return pats


KW_PATTERNS = {d: _build_kw_patterns(r) for d, r in RULE_ENGINE.items()}
NQ205_PATTERN = build_pattern(NQ205_DIRECT["keywords"])
PROVINCE_PATTERN = build_pattern(PROVINCE_CONTEXT)
EXCLUDE_PATTERN = build_pattern(EXCLUDE_PHRASES)


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = htmllib.unescape(s).replace("\xa0", " ")
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
    deep = {k: v for k, v in deep_done.items() if now - v["ts"] < DEEP_KEEP_DAYS * 86400}
    save_json(CACHE_FILE, {"seen": seen, "titles": titles, "feed_fail": feed_fail, "deep_done": deep})


seen_keys, seen_titles = load_cache()
_raw_cache = load_json(CACHE_FILE, {})
feed_fail = dict(_raw_cache.get("feed_fail", {})) if isinstance(_raw_cache, dict) else {}
_raw_deep = _raw_cache.get("deep_done", {}) if isinstance(_raw_cache, dict) else {}
# deep_done[khóa] = {"ts": thời điểm, "n": số lần thử, "ok": đã đọc được nội dung}
deep_done = {k: (v if isinstance(v, dict) else {"ts": v, "n": 1, "ok": True}) for k, v in _raw_deep.items()}
stats_lock = threading.Lock()
deep_queue = []          # bài chưa đạt nhưng cần đọc nội dung để chắc chắn
deep_stats = {"queued": 0, "skipped_cap": 0, "read_ok": 0, "read_fail": 0, "resolved": 0, "resolve_fail": 0}
scan_stats = {"entries": 0}
near_miss = []           # tin bị loại nhưng nên kiểm tra tay (chỉ báo cho admin)
processed_pairs = set()  # (tiêu đề, gợi ý địa bàn) đã xét trong lần chạy này
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
def match_domains(text):
    """Khớp từ khóa theo lĩnh vực NQ205. Trả về (từ khóa, lĩnh vực, gợi ý, có_từ_khóa_mạnh, điểm)."""
    kws, doms, hints, strong, score = [], [], [], False, 0
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
    return kws, doms, hints, strong, score


def find_direct(text):
    if not NQ205_DIRECT_ENABLED:
        return []
    return sorted({m.group(0).lower() for m in NQ205_PATTERN.finditer(text)})


def analyze(title, content, body="", hint_locs=()):
    """hint_locs: xã suy ra từ truy vấn Google News (dùng khi tiêu đề/tóm tắt/nội dung không nêu tên xã)."""
    head = f"{title} {content}"
    if EXCLUDE_PATTERN.search(head):  # chỉ xét tiêu đề + tóm tắt, tránh nhiễu từ thân bài
        return None
    text = f"{head} {body}" if body else head

    kws, doms, hints, strong, kscore = match_domains(text)
    locs = find_communes(text)
    direct = find_direct(text)
    unverified = False
    if not locs and hint_locs:
        locs, unverified = list(hint_locs), True

    if locs and not unverified:
        tier, base = "commune", 30
    elif locs:
        tier, base = "commune", HINT_BASE_SCORE
    elif PROVINCE_PATTERN.search(text):
        tier, base = "province", PROVINCE_BASE_SCORE
    else:
        tier, base = "none", NQ205_DIRECT_BASE_SCORE

    # Bài nói trực tiếp về NQ205: không cần địa bàn
    if direct:
        return {
            "locs": locs, "tier": "commune" if locs else "nq205", "unverified": unverified,
            "kws": direct + kws, "doms": [NQ205_DIRECT["name"]] + doms,
            "hints": [NQ205_DIRECT["hint"]] + hints,
            "score": base + NQ205_DIRECT["score"] + kscore,
        }

    if tier == "none":
        return None
    score = base + kscore
    # BẮT BUỘC thuộc ít nhất 1 đối tượng/lĩnh vực của NQ205 (không chỉ "phản ánh/bức xúc")
    if not strong or score < MIN_SCORE:
        return None
    return {"locs": locs, "tier": tier, "unverified": unverified,
            "kws": kws, "doms": doms, "hints": hints, "score": score}


def resolve_google_link(link):
    """Link Google News -> địa chỉ bài gốc. Trả về chuỗi rỗng nếu không giải mã được."""
    if gnewsdecoder is None:
        return ""
    try:
        try:
            d = gnewsdecoder(link, timeout=10)
        except TypeError:  # bản thư viện cũ không có tham số timeout
            d = gnewsdecoder(link)
        ok = d.get("success", d.get("status"))
        url = (d.get("decoded_url") or "") if ok else ""
    except Exception:
        url = ""
    with stats_lock:
        deep_stats["resolved" if url else "resolve_fail"] += 1
    return url


def fetch_body(url):
    """Đọc lướt nội dung bài: mô tả (meta) + các đoạn văn đầu. Trả về chuỗi rỗng nếu không đọc được."""
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        if r.status_code != 200:
            return ""
        page = re.sub(r"(?is)<(script|style|noscript|nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", r.text)
        metas = re.findall(r'(?is)<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]*?'
                           r'content=["\']([^"\']+)', page)
        paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", page)
        txt = " ".join(metas[:1] + [strip_html(x) for x in paras[:30]]).strip()
        if len(txt) < 300:  # trang không dùng thẻ <p>: lấy toàn bộ chữ
            txt = strip_html(page)[:8000]
        # Trang chặn bot / thông báo lỗi thường rất ngắn
        if len(txt) < 200 or re.search(r"(?i)just a moment|access denied|attention required|captcha", txt[:400]):
            return ""
        return txt[:8000]
    except Exception:
        return ""


def add_candidate(title, link, res, extra_keys=(), extra=None):
    keys = keys_for(title, link) | set(extra_keys)
    tokens = title_tokens(title)
    with cand_lock:
        if is_duplicate(keys, tokens):
            return False
        seen_in_run_keys.update(keys)
        candidates.append({"title": clean_title(title) or title, "link": link, "keys": keys,
                           "tokens": tokens, **res, **(extra or {})})
    return True


def process_article(title, content, link, ctx=(2, ())):
    prio, hint = ctx
    title = strip_html(title)
    content = strip_html(content)
    pair = (title, hint)
    if pair in processed_pairs:  # cùng một bài xuất hiện ở hàng chục truy vấn: chỉ xét một lần
        return
    processed_pairs.add(pair)

    res = analyze(title, content, hint_locs=hint)
    keep = {"title_raw": title, "content": content, "rawlink": link, "hint": hint}
    if res:
        add_candidate(title, link, res, extra=keep)
        return
    if not DEEP_FETCH:
        return

    # Chưa đủ căn cứ qua tiêu đề/tóm tắt -> xếp hàng để đọc nội dung bài
    head = f"{title} {content}"
    if EXCLUDE_PATTERN.search(head):
        return
    _, _, _, strong, _ = match_domains(head)
    has_loc = bool(find_communes(head)) or bool(hint) or bool(PROVINCE_PATTERN.search(head))
    if not (strong or has_loc or find_direct(head)):
        return
    qk = keys_for(title, link)
    with cand_lock:
        if is_duplicate(qk, title_tokens(title)):
            return
        if qk & {k for it in deep_queue for k in it["keys"]}:
            return
        deep_queue.append({"kind": "new", "title": title, "content": content, "link": link, "hint": hint,
                           "keys": qk, "strong": strong, "order": (0 if strong else 1, prio)})


def _deep_key(link):
    return "D:" + md5(normalize_link(link))


def deep_one(it):
    title, content, link, hint = it["title"], it["content"], it["link"], it["hint"]
    real = resolve_google_link(link) if "news.google.com" in link else link
    body = fetch_body(real) if real else ""
    with stats_lock:
        deep_stats["read_ok" if body else "read_fail"] += 1
        prev = deep_done.get(_deep_key(link), {"n": 0})
        deep_done[_deep_key(link)] = {"ts": time.time(), "n": prev.get("n", 0) + 1, "ok": bool(body)}

    res = analyze(title, content, body, hint_locs=hint)
    if res and body:
        res["body_checked"] = True
    extra_keys = {"L:" + md5(normalize_link(real))} if real and real != link else set()

    if it["kind"] == "verify":
        c = it["cand"]
        if res:
            c.update({k: res[k] for k in res})
        if real and real != link:
            c["link"] = real
            c["keys"] = set(c["keys"]) | extra_keys
        return

    if res:
        add_candidate(title, link, res, extra_keys=extra_keys,
                      extra={"title_raw": title, "content": content, "rawlink": link, "hint": hint,
                             **({"link": real} if real else {})})
        return
    # Vẫn bị loại: ghi lại để admin kiểm tra tay nếu đáng ngờ
    why = None
    if not body:
        why = "không đọc được nội dung (trang chặn/lỗi)"
    elif it["strong"]:
        why = "có từ khóa NQ205 nhưng nội dung không nêu địa bàn thuộc KV2"
    if why:
        with stats_lock:
            if not any(similar(title_tokens(title), title_tokens(t)) for t, _, _ in near_miss):
                near_miss.append((clean_title(title) or title, why, real or link))


def run_deep_phase():
    """Đọc nội dung: (1) bài mới chưa đủ căn cứ, (2) bài cấp tỉnh / chưa xác minh xã để đối chiếu lại."""
    if not DEEP_FETCH:
        return
    items = list(deep_queue)
    for c in candidates:
        if c.get("tier") == "province" or c.get("unverified"):
            items.append({"kind": "verify", "cand": c, "title": c["title_raw"], "content": c["content"],
                          "link": c["rawlink"], "hint": c["hint"], "keys": c["keys"], "strong": True,
                          "order": (2, 0)})
    items.sort(key=lambda x: x["order"])
    todo = []
    for it in items:
        d = deep_done.get(_deep_key(it["link"]))
        if d and (d.get("ok") or d.get("n", 0) >= 2):  # đã đọc rồi, hoặc đã thử 2 lần mà trang chặn
            continue
        todo.append(it)
    deep_stats["queued"] = len(todo)
    todo, rest = todo[:MAX_DEEP_FETCH], todo[MAX_DEEP_FETCH:]
    deep_stats["skipped_cap"] = len(rest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=DEEP_WORKERS) as ex:
        list(ex.map(deep_one, todo))


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
    url, name, ctx = feed_info
    time.sleep(random.uniform(0.5, 1.5))
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
    is_google = "news.google.com" in url
    try:
        f = fetch_feed(url)
        n = len(f.entries)
        # RSS trực tiếp mà không có bài nào => nghi hỏng/đổi đường dẫn. Google News rỗng là bình thường.
        feed_stats[url] = "empty" if (n == 0 and not is_google) else "ok"
        with stats_lock:
            scan_stats["entries"] += min(n, MAX_ENTRIES_PER_FEED)
        for e in f.entries[:MAX_ENTRIES_PER_FEED]:
            title = getattr(e, "title", "") or ""
            link = getattr(e, "link", "") or ""
            if not title or not link:
                continue
            dt = entry_time(e)
            if dt and dt < cutoff:
                continue  # bài cũ
            parts = [getattr(e, "summary", "") or "", getattr(e, "description", "") or ""]
            for x in (getattr(e, "content", None) or []):  # content:encoded của nhiều báo có toàn văn
                parts.append(x.get("value", "") if hasattr(x, "get") else "")
            process_article(title, " ".join(parts), link, ctx)
    except Exception as ex:
        feed_stats[url] = "fail"
        print(f"[WARN] Lỗi nguồn {name}: {url[:90]} -> {type(ex).__name__}")


def build_alert(c, idx=1, total=1):
    lvl = "🔴 RẤT CAO" if c["score"] >= 85 else "🟠 CAO" if c["score"] >= 65 else "🟡 TRUNG BÌNH"
    hints = list(dict.fromkeys(c["hints"]))
    tier = c.get("tier", "commune")
    if tier == "commune":
        names = [x for x in c["locs"] if x != "*"]
        if c.get("unverified"):
            who = ", ".join(sorted(set(names))) if names else "một trong các xã thuộc địa bàn VKSND KV2"
            loc_line = f"📍 Địa bàn (xã): {who} (suy ra từ kết quả tìm kiếm, chưa đọc được nội dung bài - cần xác minh)"
        else:
            loc_line = f"📍 Địa bàn (xã): {', '.join(sorted(set(names)))}"
            if c.get("body_checked"):
                loc_line += " ✔ đã đối chiếu nội dung bài"
    elif tier == "province":
        loc_line = "📍 Phạm vi: CẤP TỈNH (Lào Cai/Yên Bái), chưa nêu xã - cần xác minh địa bàn thuộc VKSND KV2"
    else:
        loc_line = "📍 Tin về NQ205 nói chung (chưa gắn địa bàn cụ thể)"
    return (
        f"🚨 NGUỒN TIN {idx}/{total} - {lvl} ({c['score']} điểm)\n\n"
        f"📰 {c['title']}\n\n"
        f"{loc_line}\n"
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
def explain(title, content=""):
    """Chạy thử bộ lọc, không gửi Telegram:  python radar205.py --explain "tiêu đề" "tóm tắt" """
    text = f"{strip_html(title)} {strip_html(content)}"
    print("Loại bởi EXCLUDE_PHRASES:", bool(EXCLUDE_PATTERN.search(text)))
    print("Xã tìm thấy:", find_communes(text) or "không có")
    print("Nhắc Lào Cai/Yên Bái:", bool(PROVINCE_PATTERN.search(text)))
    print("Cụm NQ205 trực tiếp:", find_direct(text) or "không có")
    kws, doms, _, strong, kscore = match_domains(text)
    print("Từ khóa khớp:", kws or "không có", "| lĩnh vực:", doms or "không có")
    print("Có từ khóa mạnh:", strong, "| điểm từ khóa:", kscore)
    res = analyze(strip_html(title), strip_html(content))
    if res:
        print(f"=> SẼ GỬI (tầng: {res['tier']}, {res['score']} điểm)")
    else:
        print("=> BỊ LOẠI")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--explain":
        explain(sys.argv[2] if len(sys.argv) > 2 else "", sys.argv[3] if len(sys.argv) > 3 else "")
        raise SystemExit
    if not TELEGRAM_TOKEN:
        raise SystemExit("Thiếu TELEGRAM_TOKEN")

    started = now_vn()
    t0 = time.time()
    time_str = started.strftime("%H:%M ngày %d/%m/%Y")
    get_updates()
    # Lời chào ngay khi bắt đầu quét (gửi sau get_updates để người mới đăng ký cũng nhận được)
    broadcast(START_GREETING.format(time=time_str))

    def g_url(q):
        return f"https://news.google.com/rss/search?q={quote(q)}&hl=vi&gl=VN&ceid=VN:vi"

    # Mỗi nhiệm vụ: (url, tên, (độ ưu tiên, xã gợi ý)). Xã gợi ý = xã đã đưa vào truy vấn Google News:
    # Google tìm theo TOÀN VĂN bài, nên bài trả về thường có nhắc xã đó dù tiêu đề không nêu.
    tasks = [(u, "RSS", (2, ())) for u in RSS_SOURCES]
    # (a) Từng xã x từng chủ đề NQ205
    for l, info in COMMUNES.items():
        place = f"{l} Lào Cai" if info["ambiguous"] else l
        for k in GOOGLE_QUERIES:
            tasks.append((g_url(f"{place} {k} when:{MAX_AGE_DAYS}d"), "Google News", (0, (l,))))
    # (b) Từng đầu báo x tên các xã (không trùng tên nơi khác) - bao phủ cả báo không có RSS
    sure_names = [a for info in COMMUNES.values() if not info["ambiguous"] for a in info["aliases"]]
    names_q = " OR ".join(f'"{a}"' for a in sure_names)
    for d in NEWS_DOMAINS:
        tasks.append((g_url(f"site:{d} ({names_q}) when:{MAX_AGE_DAYS}d"), f"site:{d}", (0, ("*",))))
    # (b2) Các xã dễ trùng tên: bắt buộc viết "xã <tên>" kèm Lào Cai/Yên Bái
    for l, info in COMMUNES.items():
        if info["ambiguous"]:
            for prov in PROVINCE_CONTEXT:
                nm = info["aliases"][0]
                tasks.append((g_url(f'"xã {nm}" "{prov}" when:{MAX_AGE_DAYS}d'), "Google News", (0, (l,))))
    # (c) Tin cấp tỉnh: Lào Cai / Yên Bái x từng chủ đề (không đòi tên xã)
    for prov in PROVINCE_CONTEXT:
        for k in GOOGLE_QUERIES:
            tasks.append((g_url(f'"{prov}" {k} when:{MAX_AGE_DAYS}d'), "Google News", (1, ())))
    # (d) Nội dung trực tiếp về NQ205
    if NQ205_DIRECT_ENABLED:
        for k in NQ205_QUERIES:
            for suffix in ("", " Lào Cai"):
                tasks.append((g_url(f"{k}{suffix} when:{MAX_AGE_DAYS}d"), "Google News", (1, ())))
    tasks = list(dict.fromkeys(tasks))

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(process_single_feed, tasks))

    # Đọc lướt nội dung các bài chưa đủ căn cứ + đối chiếu lại bài cấp tỉnh / chưa xác minh xã
    run_deep_phase()

    # Ưu tiên bài điểm cao, chỉ gửi tối đa MAX_ALERTS_PER_RUN
    candidates.sort(key=lambda c: c["score"], reverse=True)
    to_send = candidates[:MAX_ALERTS_PER_RUN]

    now = time.time()
    sent = len(to_send)
    tier_cnt = {t: sum(1 for c in to_send if c.get("tier") == t) for t in ("commune", "province", "nq205")}

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
        dur = int(time.time() - t0)
        msg = (
            f"🤖 Radar NQ205 đã chạy xong ({started.strftime('%d/%m/%Y %H:%M')}, {dur}s)\n"
            f"• Tổng truy vấn: {len(tasks)} (RSS trực tiếp: {rss_total}, Google News: {g_total}, "
            f"phủ {len(NEWS_DOMAINS)} đầu báo)\n"
            f"• Tin mới đã gửi: {sent} (xã: {tier_cnt['commune']}, cấp tỉnh: {tier_cnt['province']}, NQ205: {tier_cnt['nq205']})\n"
            f"• Tin còn chờ lần sau: {pending}\n"
            f"• Bài đã duyệt: {scan_stats['entries']} | Cần đọc nội dung: {deep_stats['queued']} "
            f"(đọc được {deep_stats['read_ok']}, lỗi {deep_stats['read_fail']}, vượt giới hạn {deep_stats['skipped_cap']})\n"
            f"• Giải mã link Google News: {deep_stats['resolved']} được, {deep_stats['resolve_fail']} lỗi\n"
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
        if gnewsdecoder is None:
            msg += "\n⚠️ Thiếu thư viện googlenewsdecoder (thêm vào requirements.txt): bài từ Google News chỉ được xét theo tiêu đề."
        elif deep_stats["resolve_fail"] > deep_stats["resolved"] and deep_stats["resolve_fail"] >= 5:
            msg += "\n⚠️ Giải mã link Google News lỗi nhiều: nhiều bài chỉ được xét theo tiêu đề."
        if deep_stats["read_fail"] > deep_stats["read_ok"] and deep_stats["read_fail"] >= 5:
            msg += "\n⚠️ Nhiều trang báo chặn đọc nội dung từ máy chủ GitHub."
        if near_miss:
            msg += "\n\n🔎 Tin bị loại nhưng nên kiểm tra tay (tối đa 12):\n"
            msg += "\n".join(f"- {t[:90]} [{why}]\n  {lnk}" for t, why, lnk in near_miss[:12])
            if len(near_miss) > 12:
                msg += f"\n... và {len(near_miss) - 12} tin khác"
        tg_send(ADMIN_CHAT_ID, msg)
