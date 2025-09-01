import discord
import requests
import re
from discord.ext import commands
import threading
import time
from datetime import datetime
from decouple import config
import os

# configuration settings
DISCORD_TOKEN = config('DISCORD_TOKEN')
TELEGRAM_TOKEN = config('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = config('TELEGRAM_CHAT_ID', cast=int)
CHANNEL_ID = config('DISCORD_CHANNEL_ID', cast=int)
ORDERS_FILE = config('ORDERS_FILE', default='orders.txt')
ERROR_LOG_FILE = "error.log"

# start time of the bot
START_TIME = time.time()

# save order id to file
def save_order(order_id):
    try:
        with open(ORDERS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{order_id}\n")
        print(f"order saved: {order_id}")
    except Exception as e:
        error_msg = f"failed to save order: {str(e)}"
        print(error_msg)
        log_error(error_msg)

# read all orders from file
def get_all_orders():
    try:
        if not os.path.exists(ORDERS_FILE):
            return []
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        return [line.strip() for line in lines if line.strip()]
    except Exception as e:
        log_error(f"read orders failed: {str(e)}")
        return []

# remove duplicates
def get_unique_orders():
    return list(set(get_all_orders()))

# log error to file
def log_error(msg):
    safe_msg = msg
    if TELEGRAM_TOKEN in safe_msg:
        safe_msg = safe_msg.replace(TELEGRAM_TOKEN, "*****TELEGRAM_TOKEN*****")
    if DISCORD_TOKEN in safe_msg:
        safe_msg = safe_msg.replace(DISCORD_TOKEN, "*****DISCORD_TOKEN*****")
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {safe_msg}\n")
    except Exception as e:
        print(f"failed to save log: {str(e)}")

# calculate uptime
def get_uptime():
    seconds = int(time.time() - START_TIME)
    uptime = divmod(seconds, 60)
    minutes, seconds = uptime
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    months = days // 30
    days = days % 30

    parts = []
    if months > 0:
        parts.append(f"{months} bulan")
    if days > 0:
        parts.append(f"{days} hari")
    if hours > 0:
        parts.append(f"{hours} jam")
    if minutes > 0:
        parts.append(f"{minutes} menit")

    return ", ".join(parts) if parts else "kurang dari 1 menit"

# fetch order history from discord
async def fetch_all_orders_from_history():
    channel = discord_bot.get_channel(CHANNEL_ID)
    if not channel:
        print("channel not found. check CHANNEL_ID in .env")
        return

    print("reading order history from start...")
    order_ids = set()
    try:
        async for message in channel.history(limit=10000):
            if "Baru Dibayar" in message.content:
                match = re.search(r"nomor pesanan \*\*(.*?)\*\*", message.content, re.DOTALL)
                if match:
                    order_id = match.group(1)
                    if order_id not in order_ids:
                        order_ids.add(order_id)
                        save_order(order_id)
        print(f"history done: {len(order_ids)} past orders")
    except Exception as e:
        error_msg = f"failed to read history: {str(e)}"
        print(error_msg)
        log_error(error_msg)

# send message to telegram with typing option
def send_telegram(text, chat_id, simulate_typing=True):
    if simulate_typing:
        typing_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
        typing_payload = {
            "chat_id": chat_id,
            "action": "typing"
        }
        try:
            requests.post(typing_url, json=typing_payload, timeout=10)
            time.sleep(2)
        except Exception as e:
            log_error(f"typing simulation failed: {str(e)}")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text.strip(),
        "disable_web_page_preview": True,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("telegram message sent")
            return response.json().get("result", {}).get("message_id")
        else:
            print(f"telegram failed: {response.status_code} - {response.text}")
            log_error(f"telegram error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"send failed: {str(e)}")
        log_error(f"send failed: {str(e)}")
        return None

# delete message after delay
def delete_message_later(chat_id, message_id, delay=10):
    time.sleep(delay)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

# check expiry warning
def check_expiry_warning():
    warning_date = datetime(2026, 7, 28)
    expiry_date = datetime(2026, 8, 28)
    now = datetime.now()

    if now >= warning_date:
        if now < expiry_date:
            days_left = (expiry_date - now).days
            msg = f"""
🔔 *PERINGATAN 11 BULAN!*
──────────────────
📅 *VPS akan expire pada:* 28 Agustus 2026
⏳ *Tersisa:* {days_left} hari
💡 *Siapkan backup atau migrasi sebelum habis!*
──────────────────
"""
            send_telegram(msg, TELEGRAM_CHAT_ID)
        elif now >= expiry_date:
            send_telegram("🔴 *VPS SUDAH EXPIRE.* Harap periksa Alibaba Cloud.", TELEGRAM_CHAT_ID)

# discord bot setup
intents = discord.Intents.default()
intents.message_content = True
discord_bot = commands.Bot(command_prefix="!", intents=intents)

# store order details
ORDER_DETAILS = {}

@discord_bot.event
async def on_ready():
    print(f"bot running as {discord_bot.user}")
    print(f"started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    await fetch_all_orders_from_history()

@discord_bot.event
async def on_message(message):
    if message.channel.id != CHANNEL_ID:
        return

    print(f"received message from: {message.author.name}, webhook: {message.webhook_id is not None}, content: {message.content}")  # debug log

    if "Baru Dibayar" in message.content:
        match = re.search(r"nomor pesanan \*\*(.*?)\*\*", message.content, re.DOTALL)
        if match:
            order_id = match.group(1).strip()
            existing = get_all_orders()
            if order_id not in existing:
                save_order(order_id)

                buyer_match = re.search(r"Nama Pembeli: (.*?)(?=\n|$)", message.content, re.DOTALL)
                game_match = re.search(r"Nama Game: (.*?)(?=\n|$)", message.content, re.DOTALL)
                product_match = re.search(r"Nama Produk: (.*?)(?=\n|$)", message.content, re.DOTALL)
                time_match = re.search(r"Tanggal & Waktu: (.*?)(?= WIB|$)", message.content, re.DOTALL)

                buyer = buyer_match.group(1).strip() if buyer_match else ""
                game = game_match.group(1).strip() if game_match else ""
                product = product_match.group(1).strip() if product_match else ""
                timestamp = time_match.group(1).strip() if time_match else ""

                link = f"https://tokoku.itemku.com/riwayat-pesanan/rincian/{order_id.replace('OD', '')}"

                ORDER_DETAILS[order_id] = {
                    "buyer": buyer,
                    "game": game,
                    "product": product,
                    "time": timestamp,
                    "link": link
                }

                text = f"""
🔔 *PESANAN BARU DI TOKO KAMU!*
──────────────────
📦 *ID Pesanan:* `{order_id}`
👤 *Nama Pembeli:* {buyer}
🎮 *Nama Game:* {game}
🛍️ *Produk:* {product}
🕒 *Waktu:* {timestamp} WIB
🔗 *Link:* {link}
──────────────────
"""
                print(f"sending telegram for order: {order_id}")  # debug log
                send_telegram(text, TELEGRAM_CHAT_ID, simulate_typing=False)
            else:
                print(f"order already exists: {order_id}")

    await discord_bot.process_commands(message)

# telegram command listener
def telegram_listener():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"timeout": 30, "offset": offset, "limit": 100}
            response = requests.get(url, params=params, timeout=60)
            data = response.json()

            if data["ok"]:
                for item in data["result"]:
                    offset = item["update_id"] + 1
                    message = item.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "").strip()

                    if chat_id != TELEGRAM_CHAT_ID:
                        continue

                    cmd = text.lower()

                    if cmd == "/uptime":
                        send_telegram(f"""
⏱️ *UPTIME BOT*
──────────────────
{get_uptime()}
──────────────────
""", chat_id)

                    elif cmd == "/allorders":
                        orders = get_all_orders()
                        unique = get_unique_orders()
                        send_telegram(f"""
📊 *STATISTIK PESANAN*
──────────────────
📦 *Total semua pesanan:* {len(orders)}
✅ *Total unik:* {len(unique)}
──────────────────
💡 *Gunakan /lastorder untuk detail terakhir.*
""", chat_id)

                    elif cmd == "/lastorder":
                        unique = get_unique_orders()
                        if unique:
                            last_id = unique[-1]
                            detail = ORDER_DETAILS.get(last_id, {})
                            send_telegram(f"""
📌 *LAST ORDER*
──────────────────
📦 *ID Pesanan:* `{last_id}`
👤 *Nama Pembeli:* {detail.get('buyer', '')}
🎮 *Nama Game:* {detail.get('game', '')}
🛍️ *Produk:* {detail.get('product', '')}
🕒 *Waktu:* {detail.get('time', '')} WIB
🔗 *Link:* {detail.get('link', f'https://tokoku.itemku.com/riwayat-pesanan/rincian/{last_id.replace("OD", "")}')}
──────────────────
💡 *Gunakan /allorders untuk statistik.*
""", chat_id)
                        else:
                            sent_msg_id = send_telegram("❌ *Belum ada pesanan tercatat.*", chat_id)
                            if sent_msg_id:
                                threading.Thread(target=delete_message_later, args=(chat_id, sent_msg_id, 10), daemon=True).start()

                    elif cmd == "/errorlogs":
                        if os.path.exists(ERROR_LOG_FILE):
                            with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
                                lines = f.readlines()
                            if lines:
                                recent = lines[-10:]
                                log_text = "📋 *ERROR LOG TERAKHIR*\n"
                                log_text += "──────────────────\n"
                                for i, line in enumerate(recent, 1):
                                    clean = line.strip().replace('`', '\\`').replace('*', '\\*')
                                    log_text += f"🔹 *{i}. {clean}*\n"
                                log_text += "──────────────────\n"
                                log_text += "ℹ️ *Gunakan /uptime untuk info bot.*"
                                send_telegram(log_text, chat_id)
                            else:
                                sent_msg_id = send_telegram("🟢 *Tidak ada error tercatat.*", chat_id)
                                if sent_msg_id:
                                    threading.Thread(target=delete_message_later, args=(chat_id, sent_msg_id, 10), daemon=True).start()
                        else:
                            sent_msg_id = send_telegram("🟡 *File `error.log` tidak ditemukan.*", chat_id)
                            if sent_msg_id:
                                threading.Thread(target=delete_message_later, args=(chat_id, sent_msg_id, 10), daemon=True).start()

            current_hour = int(time.time() // 3600)
            if current_hour % 6 == 0:
                check_expiry_warning()

            time.sleep(1)
        except Exception as e:
            error_msg = f"telegram listener error: {str(e)}"
            print(error_msg)
            log_error(error_msg)
            time.sleep(5)

# run the bot
if __name__ == "__main__":
    t = threading.Thread(target=telegram_listener, daemon=True)
    t.start()
    discord_bot.run(DISCORD_TOKEN)
