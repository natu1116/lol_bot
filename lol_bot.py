import discord
from discord.ext import commands, tasks
import os
import time
import random
import asyncio
from aiohttp import web
from datetime import datetime, timedelta, timezone
import aiohttp_cors
from supabase import create_client

# -----------------------------
# Supabase 接続
# -----------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    data = supabase.table("users").select("*").eq("uid", uid).execute()
    if len(data.data) == 0:
        supabase.table("users").insert({
            "uid": uid,
            "coins": 0,
            "points": 0,
            "last_daily": 0,
            "special_role": None
        }).execute()

def get_user(uid):
    return supabase.table("users").select("*").eq("uid", uid).execute().data[0]

def update_user(uid, data):
    supabase.table("users").update(data).eq("uid", uid).execute()

# -----------------------------
# /get（1日1回コイン）
# -----------------------------
@bot.tree.command(name="get", description="1日1回コインを受け取る")
async def get_coin(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = get_user(uid)

    now = time.time()
    if now - user["last_daily"] < 24 * 60 * 60:
        await interaction.response.send_message("今日はすでに受け取っています。", ephemeral=True)
        return

    update_user(uid, {
        "coins": user["coins"] + 1,
        "last_daily": now
    })

    await interaction.response.send_message(
        f"🎁 今日のログインボーナス！\nコイン +1（現在: {user['coins'] + 1}）",
        ephemeral=True
    )

# -----------------------------
# /gacha
# -----------------------------
@bot.tree.command(name="gacha", description="5コインでガチャを回す")
async def gacha(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = get_user(uid)

    if user["coins"] < 5:
        await interaction.response.send_message("コインが足りません。（必要: 5）", ephemeral=True)
        return

    update_user(uid, {"coins": user["coins"] - 5})
    now = time.time()
    roll = random.random() * 100

    if roll < 4:
        role = discord.utils.get(interaction.guild.roles, name="神引き")
        if role is None:
            await interaction.response.send_message("神引きロールが存在しません。", ephemeral=True)
            return

        await interaction.user.add_roles(role)

        expires_at = now + 72 * 60 * 60
        update_user(uid, {
            "special_role": {
                "role_id": role.id,
                "expires_at": expires_at
            }
        })

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

    update_user(uid, {"points": user["points"] + pts})

    await interaction.response.send_message(
        f"🎰 ガチャ結果！\n✨ **{pts}ポイント** を獲得！",
        ephemeral=True
    )

# -----------------------------
# /coin
# -----------------------------
@bot.tree.command(name="coin", description="自分のコインを確認する")
async def coin(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)
    user = get_user(uid)

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
    user = get_user(uid)

    await interaction.response.send_message(
        f"💎 あなたのポイント：**{user['points']}pt**",
        ephemeral=True
    )

# -----------------------------
# 特殊ロール期限チェック
# -----------------------------
@tasks.loop(seconds=60)
async def check_special_roles():
    all_users = supabase.table("users").select("*").execute().data
    now = time.time()

    for user in all_users:
        entry = user["special_role"]
        if not entry:
            continue

        if now > entry["expires_at"]:
            for guild in bot.guilds:
                member = guild.get_member(int(user["uid"]))
                role = guild.get_role(entry["role_id"])

                if member and role:
                    await member.remove_roles(role)

            update_user(user["uid"], {"special_role": None})

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
