import discord
from discord.ext import commands, tasks
import os
import time
import random
import asyncio
from aiohttp import web
from datetime import datetime, timedelta, timezone
import aiohttp_cors

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
import json

# -----------------------------
# Google Drive 永続化
# -----------------------------
def get_drive_service():
    info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

DRIVE_FILE_ID = os.getenv("DRIVE_FILE_ID")

def load_data():
    service = get_drive_service()
    file = service.files().get_media(fileId=DRIVE_FILE_ID).execute()
    return json.loads(file.decode("utf-8"))

def save_data(data):
    service = get_drive_service()
    body = json.dumps(data, ensure_ascii=False, indent=2)
    media = MediaInMemoryUpload(body, mimetype="application/json")
    service.files().update(
        fileId=DRIVE_FILE_ID,
        media_body=media
    ).execute()

# -----------------------------
# データ読み込み
# -----------------------------
try:
    user_data = load_data()
except:
    user_data = {}

# -----------------------------
# Bot 設定
# -----------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -----------------------------
# ユーザーデータ初期化
# -----------------------------
def ensure_user(uid):
    if uid not in user_data:
        user_data[uid] = {
            "coins": 0,
            "points": 0,
            "last_daily": 0,
            "special_role": None
        }
        save_data(user_data)

# -----------------------------
# /daily（1日1回コイン）
# -----------------------------
@bot.tree.command(name="daily", description="1日1回コインを受け取る")
async def get_coin(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = user_data[uid]

    # JST 現在日付（例：20260513）
    JST = timezone(timedelta(hours=+9), 'JST')
    today = int(datetime.now(JST).strftime("%Y%m%d"))

    # 初回 or 日付が変わっている → 受け取り可能
    if user["last_daily"] == today:
        await interaction.response.send_message(
            "今日はすでに受け取っています。",
            ephemeral=True
        )
        return

    # コイン付与
    user["coins"] += 1
    user["last_daily"] = today
    save_data(user_data)

    await interaction.response.send_message(
        f"🎁 今日のログインボーナス！\nコイン +1（現在: {user['coins']}）",
        ephemeral=True
    )

# -----------------------------
# /gacha
# -----------------------------
@bot.tree.command(name="gacha", description="5コインでガチャを回す")
async def gacha(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = user_data[uid]

    if user["coins"] < 5:
        await interaction.response.send_message("コインが足りません。（必要: 5）", ephemeral=True)
        return

    user["coins"] -= 5
    now = time.time()
    roll = random.random() * 100

    if roll < 4:
        role = discord.utils.get(interaction.guild.roles, name="神引き")
        if role is None:
            await interaction.response.send_message("神引きロールが存在しません。", ephemeral=True)
            return

        await interaction.user.add_roles(role)

        expires_at = now + 72 * 60 * 60
        user["special_role"] = {
            "role_id": role.id,
            "expires_at": expires_at
        }

        save_data(user_data)
        await interaction.response.send_message("🌟 **神引き！特殊ロール獲得！**（72時間限定）", ephemeral=True)
        return

    elif roll < 11:
        pts = 15
    elif roll < 24:
        pts = 7
    elif roll < 55:
        pts = 3
    else:
        pts = 1

    user["points"] += pts
    save_data(user_data)

    await interaction.response.send_message(
        f"🎰 ガチャ結果！\n✨ **{pts}ポイント** を獲得！",
        ephemeral=True
    )

# -----------------------------
# /shop（ロール購入）
# -----------------------------
@bot.tree.command(name="shop", description="ポイントでロールを購入する")
async def shop(interaction: discord.Interaction, item: str):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = user_data[uid]

    # ショップの商品一覧
    shop_items = {
        "vip": {"cost": 30, "role_name": "VIP", "duration": 24 * 60 * 60},
        "premium": {"cost": 60, "role_name": "Premium", "duration": 48 * 60 * 60},
    }

    if item not in shop_items:
        await interaction.response.send_message(
            "購入できるアイテム:\n- vip\n- premium",
            ephemeral=True
        )
        return

    item_data = shop_items[item]

    # ポイント不足
    if user["points"] < item_data["cost"]:
        await interaction.response.send_message(
            f"ポイントが足りません。（必要: {item_data['cost']}pt）",
            ephemeral=True
        )
        return

    # ロール取得
    role = discord.utils.get(interaction.guild.roles, name=item_data["role_name"])
    if role is None:
        await interaction.response.send_message("ロールが存在しません。", ephemeral=True)
        return

    # ロール付与
    await interaction.user.add_roles(role)

    # ポイント消費
    user["points"] -= item_data["cost"]

    # 期限設定
    expires_at = time.time() + item_data["duration"]
    user["special_role"] = {
        "role_id": role.id,
        "expires_at": expires_at
    }

    save_data(user_data)

    await interaction.response.send_message(
        f"🛒 **{item_data['role_name']} ロールを購入しました！**\n"
        f"⏳ 有効期限: {item_data['duration'] // 3600}時間",
        ephemeral=True
    )


# -----------------------------
# /setcolor（色ロール購入）
# -----------------------------
@bot.tree.command(name="setcolor", description="ポイントで色ロールを購入する")
async def setcolor(interaction: discord.Interaction, color: str):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = user_data[uid]

    # 色ロール一覧
    color_roles = {
        "red":    {"cost": 10, "role_name": "Red",    "duration": 24 * 60 * 60},
        "blue":   {"cost": 10, "role_name": "Blue",   "duration": 24 * 60 * 60},
        "green":  {"cost": 10, "role_name": "Green",  "duration": 24 * 60 * 60},
        "yellow": {"cost": 10, "role_name": "Yellow", "duration": 24 * 60 * 60},
        "pink":   {"cost": 10, "role_name": "Pink",   "duration": 24 * 60 * 60},
    }

    if color not in color_roles:
        await interaction.response.send_message(
            "使用できる色:\n- red\n- blue\n- green\n- yellow\n- pink",
            ephemeral=True
        )
        return

    item = color_roles[color]

    # ポイント不足
    if user["points"] < item["cost"]:
        await interaction.response.send_message(
            f"ポイントが足りません。（必要: {item['cost']}pt）",
            ephemeral=True
        )
        return

    # ロール取得
    role = discord.utils.get(interaction.guild.roles, name=item["role_name"])
    if role is None:
        await interaction.response.send_message("ロールが存在しません。", ephemeral=True)
        return

    # 既存の色ロールを剥奪
    for r in interaction.user.roles:
        if r.name in [v["role_name"] for v in color_roles.values()]:
            await interaction.user.remove_roles(r)

    # 新しい色ロール付与
    await interaction.user.add_roles(role)

    # ポイント消費
    user["points"] -= item["cost"]

    # 期限設定
    expires_at = time.time() + item["duration"]
    user["special_role"] = {
        "role_id": role.id,
        "expires_at": expires_at
    }

    save_data(user_data)

    await interaction.response.send_message(
        f"🎨 **{item['role_name']} 色ロールを購入しました！**\n"
        f"⏳ 有効期限: {item['duration'] // 3600}時間",
        ephemeral=True
    )

# -----------------------------
# /coin
# -----------------------------
@bot.tree.command(name="coin", description="自分のコインを確認する")
async def coin(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = user_data[uid]

    await interaction.response.send_message(
        f"🪙 あなたのコイン：**{user['coins']}**",
        ephemeral=True
    )

# -----------------------------
# /point
# -----------------------------
@bot.tree.command(name="point", description="自分のポイントを確認する")
async def point(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = user_data[uid]

    await interaction.response.send_message(
        f"💎 あなたのポイント：**{user['points']}pt**",
        ephemeral=True
    )

# -----------------------------
# 特殊ロール期限チェック
# -----------------------------
@tasks.loop(seconds=60)
async def check_special_roles():
    now = time.time()

    for uid, user in user_data.items():
        entry = user.get("special_role")
        if not entry:
            continue

        if now > entry["expires_at"]:
            for guild in bot.guilds:
                member = guild.get_member(int(uid))
                role = guild.get_role(entry["role_id"])

                if member and role:
                    await member.remove_roles(role)

            user["special_role"] = None

    save_data(user_data)

@bot.event
async def on_ready():
    await bot.tree.sync()
    check_special_roles.start()
    print(f"ログイン完了: {bot.user}")

# -----------------------------
# Web サーバー（Render 用）
# -----------------------------
PORT = int(os.getenv("PORT", 10000))

async def handle_ping(request):
    JST = timezone(timedelta(hours=+9), 'JST')
    current_time_jst = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S %Z")
    print(f"🌐 [Web Ping] {current_time_jst} | Status: OK")
    return web.Response(text="Bot is running and ready.")

def setup_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)

    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=("X-Requested-With", "Content-Type"),
        )
    })

    for route in list(app.router.routes()):
        cors.add(route)

    return app

async def start_web_server():
    web_app = setup_web_server()
    runner = web.AppRunner(web_app)
    await runner.setup()

    site = web.TCPSite(runner, host='0.0.0.0', port=PORT)
    print(f"🌐 Webサーバー起動: ポート {PORT}")
    await site.start()
    await asyncio.Future()

# -----------------------------
# main（Bot + Web サーバー）
# -----------------------------
async def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("FATAL ERROR: BOT_TOKEN が設定されていません。")
        return

    web_task = asyncio.create_task(start_web_server())
    bot_task = asyncio.create_task(bot.start(TOKEN))

    await asyncio.gather(web_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())
