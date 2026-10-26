"""
Telegram guruh va kanallarga har kuni ertalab va kechqurun post yuboruvchi bot.
GitHub Actions orqali bepul ishga tushiriladi (server kerak emas).

Sozlamalar (GitHub Secrets orqali beriladi):
  BOT_TOKEN  - @BotFather bergan token
  CHAT_IDS   - guruh/kanal ID lari, vergul bilan: -1001234567890,-1009876543210,@kanal_nomi
Ixtiyoriy:
  SLOT       - "morning" yoki "evening" (bo'lmasa, Toshkent vaqtiga qarab o'zi tanlaydi)
  DRY_RUN=1  - hech narsa yubormasdan, qaysi post chiqishini ko'rsatadi
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TASHKENT = timezone(timedelta(hours=5))
BASE_DIR = Path(__file__).resolve().parent
TELEGRAM_API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")


def load_posts():
    with open(BASE_DIR / "posts.json", encoding="utf-8") as f:
        return json.load(f)


def current_slot(now):
    slot = os.environ.get("SLOT", "").strip().lower()
    if slot in ("morning", "evening"):
        return slot
    # 14:00 gacha - ertalabki post, keyin - kechki post
    return "morning" if now.hour < 14 else "evening"


def pick_post(posts, slot, now):
    items = posts.get(slot) or []
    if not items:
        sys.exit(f"posts.json ichida '{slot}' uchun birorta post yo'q")
    # Har kuni navbatdagi post: 1-kun 1-post, 2-kun 2-post, ... keyin boshidan
    return items[now.toordinal() % len(items)]


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
    for name, (filename, content) in files.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def call(token, method, fields, files=None):
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    if files:
        body, ctype = _multipart(fields, files)
    else:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as e:
        result = json.load(e)
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "noma'lum xato"))
    return result


def send(token, chat_id, post):
    text = post.get("text", "")
    fields = {"chat_id": chat_id, "parse_mode": "HTML"}

    button = post.get("button")
    if button and button.get("text") and button.get("url"):
        fields["reply_markup"] = json.dumps(
            {"inline_keyboard": [[{"text": button["text"], "url": button["url"]}]]},
            ensure_ascii=False,
        )

    photo = post.get("photo")
    if photo:
        fields["caption"] = text
        if photo.startswith("http"):
            fields["photo"] = photo
            return call(token, "sendPhoto", fields)
        with open(BASE_DIR / photo, "rb") as f:
            return call(token, "sendPhoto", fields, files={"photo": (Path(photo).name, f.read())})

    fields["text"] = text
    fields["disable_web_page_preview"] = "true"
    return call(token, "sendMessage", fields)


def main():
    now = datetime.now(TASHKENT)
    slot = current_slot(now)
    post = pick_post(load_posts(), slot, now)

    print(f"Vaqt (Toshkent): {now:%Y-%m-%d %H:%M}, post turi: {slot}")
    if "[" in post.get("text", ""):
        print("DIQQAT: postda [ ] ichidagi to'ldirilmagan joy bor - posts.json ni tekshiring")

    if os.environ.get("DRY_RUN") == "1":
        print("--- Yuboriladigan post (sinov rejimi) ---")
        print(json.dumps(post, ensure_ascii=False, indent=2))
        return

    token = os.environ.get("BOT_TOKEN", "").strip()
    raw_ids = os.environ.get("CHAT_IDS", "").replace("\n", ",")
    chat_ids = [c.strip() for c in raw_ids.split(",") if c.strip()]
    if not token or not chat_ids:
        sys.exit("BOT_TOKEN yoki CHAT_IDS kiritilmagan (GitHub Secrets ni tekshiring)")

    failed = 0
    for chat_id in chat_ids:
        try:
            send(token, chat_id, post)
            print(f"OK   -> {chat_id}")
        except Exception as e:
            failed += 1
            print(f"XATO -> {chat_id}: {e}")
        time.sleep(1)  # Telegram cheklovlariga tushmaslik uchun

    print(f"Yuborildi: {len(chat_ids) - failed}/{len(chat_ids)}")
    if failed:
        sys.exit(1)  # GitHub sizga xato haqida email yuboradi


if __name__ == "__main__":
    main()
