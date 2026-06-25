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
    "Lào Cai", 
    "Lâm Thượng", "xã Khánh Hòa", "xã Phúc Lợi", "Bảo Ái",
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
    "site:thanhtra.gov.vn", "site:vksndtc.gov.vn", "site:tandtc.gov.vn", "site:bocongan.gov.vn", "site:moj.gov.vn" 
]

RSS_SOURCES = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss", "https://dantri.com.vn/rss/home.rss", "https://vietnamnet.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss", "https://thanhnien.vn/rss/home.rss", "https://laodong.vn/rss/home.rss",
    "https://nld.com.vn/rss/home.rss", "https://tienphong.vn/rss/home.rss", "https://plo.vn/rss/home.rss",
    "https://congly.vn/rss/home.rss", "https://baophapluat.vn/rss/home.rss", "https://baovephapluat.vn/rss/home.rss",
    "https://cand.com.vn/rss/su-kien-binh-luan-chu-diem/", "https://nhandan.vn/rss/phap-luat.rss",
    "https://baochinhphu.vn/Rss/xa-hoi.rss", "https://baotintuc.vn/phap-luat.rss", "https://congthuong.vn/rss/phap-luat.rss",
    "https://baoxaydung.com.vn/rss/home.rss", "https://baogiaothong.vn/rss/home.rss", "
