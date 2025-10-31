import discord
from discord.ext import commands
import requests
import re
import threading
import time
from datetime import datetime
from decouple import config
import os
import json
import sys

# ================= CONFIG ================= #
DISCORD_TOKEN = config('DISCORD_TOKEN')
TELEGRAM_TOKEN = config('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = config('TELEGRAM_CHAT_ID', cast=int)
CHANNEL_ID = config('DISCORD_CHANNEL_ID', cast=int)
ORDERS_FILE = config('ORDERS_FILE', default='orders.txt')
ERROR_LOG_FILE = "error.log"

START_TIME = time.time()
VPS_START_TIME = datetime(2025, 8, 28, 20, 0).timestamp()

# ================= LOGGING ================= #
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
    except:
        print(f"failed to save log: {msg}")

def log_info(msg, auto_clear=False, delay=10):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    print(log_line)
    if auto_clear:
        def clear_line():
            time.sleep(delay)
            sys.stdout.write("\033[F\033[K")
            sys.stdout.flush()
        threading.Thread(target=clear_line, daemon=True).start()

# ================= UPTIME ================= #
def get_uptime(start_time):
    seconds = int(time.time() - start_time)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    months = days // 30
    days = days % 30

    parts = []
    if months > 0: parts.append(f"{months} bulan")
    if days > 0: parts.append(f"{days} hari")
    if hours > 0: parts.append(f"{hours} jam")
    if minutes > 0: parts.append(f"{minutes} menit")

    return ", ".join(parts) if parts else "kurang dari 1 menit"

def get_vps_uptime():
    return get_uptime(VPS_START_TIME)

# ================= MIGRATION ================= #
def migrate_orders_if_needed():
    if not os.path.exists(ORDERS_FILE):
        return
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    if not lines:
        return
    try:
        json.loads(lines[0].strip())
        return
    except:
        pass
    print("🔄 Migrating old orders.txt format to JSON...")
    migrated = []
    for order_id in lines:
        if not order_id.strip():
            continue
        order_data = {
            "id": order_id.strip(),
            "buyer": "",
            "game": "",
            "product": "",
            "time": "",
            "link": f"https://tokoku.itemku.com/riwayat-pesanan/rincian/{order_id.replace('OD','')}"
        }
        migrated.append(order_data)
    backup_file = ORDERS_FILE + ".bak"
    os.rename(ORDERS_FILE, backup_file)
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        for order in migrated:
            f.write(json.dumps(order, ensure_ascii=False) + "\n")
    print(f"✅ Migrasi selesai! File lama disimpan sebagai {backup_file}")

# ================= ORDER STORAGE ================= #
def save_order(order_id, details=None):
    try:
        order_data = {
            "id": order_id,
            "buyer": details.get("buyer", "Tidak diketahui") if details else "",
            "game": details.get("game", "Tidak diketahui") if details else "",
            "product": details.get("product", "Tidak diketahui") if details else "",
            "time": details.get("time", "") if details else "",
            "link": details.get("link", f"https://tokoku.itemku.com/riwayat-pesanan/rincian/{order_id.replace('OD','')}")
        }
        with open(ORDERS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(order_data, ensure_ascii=False) + "\n")
        print(f"✅ Order saved: {order_id}")
    except Exception as e:
        log_error(f"failed to save order: {str(e)}")

def get_all_orders():
    if not os.path.exists(ORDERS_FILE):
        return []
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    orders = []
    for line in lines:
        try:
            orders.append(json.loads(line))
        except:
            pass
    return orders

def get_unique_orders():
    orders = get_all_orders()
    seen = set()
    unique = []
    for o in orders:
        if o["id"] not in seen:
            seen.add(o["id"])
            unique.append(o)
    return unique

# ================= PARSER ================= #
def parse_order_details(order_id, text):
    buyer_match = re.search(r"Nama Pembeli: (.*?)(?=\n|$)", text, re.DOTALL)
    game_match = re.search(r"Nama Game: (.*?)(?=\n|$)", text, re.DOTALL)
    product_match = re.search(r"Nama Produk: (.*?)(?=\n|$)", text, re.DOTALL)
    time_match = re.search(r"Tanggal & Waktu: (.*?)(?= WIB|$)", text, re.DOTALL)
    return {
        "buyer": buyer_match.group(1).strip() if buyer_match else "Tidak diketahui",
        "game": game_match.group(1).strip() if game_match else "Tidak diketahui",
        "product": product_match.group(1).strip() if product_match else "Tidak diketahui",
        "time": time_match.group(1).strip() if time_match else "Waktu tidak diketahui",
        "link": f"https://tokoku.itemku.com/riwayat-pesanan/rincian/{order_id.replace('OD','')}"
    }

# ================= TELEGRAM ================= #
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log_error(f"telegram send failed: {str(e)}")

def send_typing_action():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "action": "typing"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log_error(f"typing action failed: {str(e)}")

def telegram_polling():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"timeout": 30, "offset": offset}
            r = requests.get(url, params=params, timeout=35)
            data = r.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                if "message" not in update: continue
                msg = update["message"]
                text = msg.get("text", "")
                chat_id = msg["chat"]["id"]

                if str(chat_id) != str(TELEGRAM_CHAT_ID):
                    continue

                if text == "/lastorder":
                    send_typing_action(); time.sleep(1)
                    orders = get_unique_orders()
                    if not orders:
                        send_telegram_message("⚠️ Belum ada order.")
                    else:
                        last = orders[-1]
                        send_telegram_message(
                            f"📦 <b>LAST ORDER</b>\n"
                            f"🆔 <code>{last['id']}</code>\n"
                            f"🙍 {last['buyer']}\n"
                            f"🎮 {last['game']}\n"
                            f"📦 {last['product']}\n"
                            f"⏰ {last['time']} WIB\n"
                            f"🔗 <a href='{last['link']}'>Link</a>"
                        )
                    log_info("no error ✅", auto_clear=True)

                elif text == "/allorders":
                    send_typing_action(); time.sleep(1)
                    send_telegram_message(f"📊 Total orders: {len(get_unique_orders())}")
                    log_info("no error ✅", auto_clear=True)

                elif text == "/uptime":
                    send_typing_action(); time.sleep(1)
                    send_telegram_message(f"⏱ Bot Uptime: {get_uptime(START_TIME)}")
                    log_info("no error ✅", auto_clear=True)

                elif text == "/vpsuptime":
                    send_typing_action(); time.sleep(1)
                    send_telegram_message(f"🖥 VPS Uptime: {get_vps_uptime()}")
                    log_info("no error ✅", auto_clear=True)

                elif text == "/errorlogs":
                    send_typing_action(); time.sleep(1)
                    if not os.path.exists(ERROR_LOG_FILE) or os.path.getsize(ERROR_LOG_FILE) == 0:
                        send_telegram_message("📂 Tidak ada error logs")
                    else:
                        with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
                            lines = f.readlines()[-20:]  # ambil 20 terakhir
                        logs_text = "".join(lines)
                        send_telegram_message(f"📂 <b>ERROR LOGS (last 20)</b>\n<pre>{logs_text}</pre>")
                    log_info("no error ✅", auto_clear=True)

        except Exception as e:
            log_error(f"telegram polling failed: {str(e)}")
        time.sleep(2)

# ================= DISCORD BOT ================= #
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

# Use commands.Bot instead of Client for slash commands support
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot connected as {bot.user}")
    try:
        # Sync slash commands
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    
    await fetch_all_orders_from_history()

async def fetch_all_orders_from_history():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("❌ Channel not found, cek DISCORD_CHANNEL_ID")
        return
    print("📥 Reading order history...")
    existing_ids = {o["id"] for o in get_all_orders()}
    try:
        async for message in channel.history(limit=10000, oldest_first=True):
            if "Baru Dibayar" in message.content:
                match = re.search(r"nomor pesanan \*\*(OD.*?)\*\*", message.content, re.DOTALL)
                if match:
                    order_id = match.group(1).strip()
                    if order_id not in existing_ids:
                        details = parse_order_details(order_id, message.content)
                        save_order(order_id, details)
                        existing_ids.add(order_id)
        print("✅ History sync done")
    except Exception as e:
        log_error(f"history fetch failed: {str(e)}")

@bot.event
async def on_message(message):
    # Process commands
    await bot.process_commands(message)
    
    if message.channel.id != CHANNEL_ID:
        return
    if "Baru Dibayar" in message.content:
        match = re.search(r"nomor pesanan \*\*(OD.*?)\*\*", message.content, re.DOTALL)
        if match:
            order_id = match.group(1).strip()
            existing = [o["id"] for o in get_all_orders()]
            if order_id not in existing:
                details = parse_order_details(order_id, message.content)
                save_order(order_id, details)
                send_telegram_message(
                    f"📦 <b>NEW ORDER</b>\n"
                    f"🆔 <code>{order_id}</code>\n"
                    f"🙍 {details['buyer']}\n"
                    f"🎮 {details['game']}\n"
                    f"📦 {details['product']}\n"
                    f"⏰ {details['time']} WIB\n"
                    f"🔗 <a href='{details['link']}'>Link</a>"
                )

# ================= SLASH COMMANDS ================= #
@bot.tree.command(name="developer", description="Developer menu command for active developer badge")
async def developer(interaction: discord.Interaction):
    """Developer command for active developer badge"""
    embed = discord.Embed(
        title="🤖 Developer Menu",
        description="Active Developer Badge Bot",
        color=0x00ff00
    )
    embed.add_field(name="Status", value="Active", inline=False)
    embed.add_field(name="Version", value="1.0.0", inline=True)
    embed.add_field(name="Uptime", value=get_uptime(START_TIME), inline=True)
    embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stats", description="Show bot statistics")
async def stats(interaction: discord.Interaction):
    """Show bot statistics"""
    orders = get_unique_orders()
    embed = discord.Embed(
        title="📊 Bot Statistics",
        color=0x5865F2
    )
    embed.add_field(name="Total Orders", value=len(orders), inline=True)
    embed.add_field(name="Uptime", value=get_uptime(START_TIME), inline=True)
    embed.add_field(name="Server Count", value=len(bot.guilds), inline=True)
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! 🏓 Latency: {latency}ms")

# ================= MAIN ================= #
if __name__ == "__main__":
    migrate_orders_if_needed()
    t = threading.Thread(target=telegram_polling, daemon=True)
    t.start()
    bot.run(DISCORD_TOKEN)
