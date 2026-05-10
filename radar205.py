import os
import json
import hashlib
from datetime import datetime
from urllib.parse import quote

import requests
import feedparser
from newspaper import Article

# ================= CONFIG =================
TELEGRAM_TOKEN = "8668493802:AAH67Cc1Sa1dlzfACDzkoKYb-2OfxGTpIiI"

CACHE_FILE = "radar205_cache.json"
SUBSCRIBERS_FILE = "subscribers.json"
UPDATES_FILE = "telegram_updates.json"

BASE_LOCATIONS = [
    "Lâm Thượng",
    "Lục Yên",
    "xã Khánh Hòa",
    "Tân Lĩnh",
    "Bảo Ái",
    "Mường Lai",
    "xã Yên Thành",
    "Thác Bà",
    "Cảm Nhân",
    "Yên Bình",
    "xã Phúc Lợi"
    "Lào Cai"
]

LOCATIONS = []
for loc in BASE_LOCATIONS:
    LOCATIONS.append(loc)
    LOCATIONS.append(f"xã {loc}")

KEYWORDS = [
    "đổ rác","rác thải","ô nhiễm","ô nhiễm môi trường","ô nhiễm nguồn nước","bụi","bột đá", "bụi trắng", "khai thác đá", "bụi đá"
    "ô nhiễm không khí","đốt rác","xả nước thải","xả thải","nước thải",
    "khai thác khoáng sản","khai thác cát","khai thác sỏi","sạt lở","phá rừng",
    "hủy hoại môi trường","lấn chiếm đất","đất công","hành lang giao thông", "bãi rác", "nắp cống"
    "hành lang suối","san gạt","đất rừng","tài sản công","thực phẩm bẩn",
    "thuốc giả","thuốc hết hạn","ngộ độc thực phẩm","suất ăn học đường",
    "hàng giả","hàng kém chất lượng","quảng cáo sai sự thật","thu phí trái quy định",
    "xâm hại di tích","phá dỡ di tích","cổ vật","bạo hành trẻ em","bỏ mặc trẻ em",
    "trẻ em khuyết tật","người già neo đơn","mất năng lực hành vi","phụ nữ mang thai",
    "người dân tộc thiểu số","không giấy khai sinh","không được cấp căn cước","hộ tịch"
]

RSS_SOURCES = [
    "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "https://dantri.com.vn/rss/home.rss",
    "https://vietnamnet.vn/rss/home.rss",
    "https://laodong.vn/rss/home.rss",
    "https://thanhnien.vn/rss/home.rss",
    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "https://nld.com.vn/rss/home.rss"
]

# ================= FILE HELPERS =================
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

# ================= TELEGRAM =================
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
    except:
        pass

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
                if chat_id in subscribers:
                    subscribers.remove(chat_id)
                    save_json(SUBSCRIBERS_FILE, subscribers)

                send_message(
                    chat_id,
                    "⛔ Bạn đã hủy đăng ký nhận cảnh báo."
                )

        save_json(UPDATES_FILE, telegram_updates)

    except:
        pass
