import discord
from discord.ext import commands, tasks
import json
import os
import time
import random

DATA_FILE = "lol_data.json"

# -----------------------------
# データ読み込み / 保存
# -----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, indent=2, ensure_ascii=False)

user_data = load_data()

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

# -----------------------------
# /daily
# -----------------------------
@bot.tree.command(name="daily", description="1日1回コインを受け取る")
async def daily(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)

    now = time.time()
    diff = now - user_data[uid]["last_daily"]

    if diff < 24 * 60 * 60:
        await interaction.response.send_message("今日はすでに受け取っています。", ephemeral=True)
        return

    user_data[uid]["coins"] += 1
    user_data[uid]["last_daily"] = now
    save_data()

    await interaction.response.send_message(
        f"🎁 今日のログインボーナス！\nコイン +1（現在: {user_data[uid]['coins']}）",
        ephemeral=True
    )

# -----------------------------
# /gacha
# -----------------------------
@bot.tree.command(name="gacha", description="5コインでガチャを回す")
async def gacha(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)

    if user_data[uid]["coins"] < 5:
        await interaction.response.send_message("コインが足りません。（必要: 5）", ephemeral=True)
        return

    user_data[uid]["coins"] -= 5
    now = time.time()
    roll = random.random() * 100

    # ガチャ確率
    # 55% → 1p
    # 31% → 3p
    # 13% → 7p
    # 7% → 15p
    # 4% → 特殊ロール「神引き」
    if roll < 4:
        role = discord.utils.get(interaction.guild.roles, name="神引き")
        if role is None:
            await interaction.response.send_message("神引きロールが存在しません。", ephemeral=True)
            return

        await interaction.user.add_roles(role)

        expires_at = now + 72 * 60 * 60
        user_data[uid]["special_role"] = {
            "role_id": role.id,
            "expires_at": expires_at
        }

        save_data()
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

    user_data[uid]["points"] += pts
    save_data()

    await interaction.response.send_message(
        f"🎰 ガチャ結果！\n✨ **{pts}ポイント** を獲得！",
        ephemeral=True
    )

# -----------------------------
# /setcolor（神引き色変更）
# -----------------------------
@bot.tree.command(name="setcolor", description="神引きロールの色を変更する（神引き所持者のみ）")
async def setcolor(interaction: discord.Interaction, color: str):
    uid = str(interaction.user.id)
    ensure_user(uid)

    role = discord.utils.get(interaction.guild.roles, name="神引き")
    if role is None:
        await interaction.response.send_message("神引きロールが存在しません。", ephemeral=True)
        return

    if not interaction.user.get_role(role.id):
        await interaction.response.send_message("神引きを所持している人のみ変更できます。", ephemeral=True)
        return

    try:
        new_color = discord.Color(int(color.replace("#", ""), 16))
        await role.edit(color=new_color)
        await interaction.response.send_message(f"🎨 神引きロールの色を **{color}** に変更しました！", ephemeral=True)
    except:
        await interaction.response.send_message("色コードが不正です。例: #ff0000", ephemeral=True)

# -----------------------------
# /coin（自分のコイン確認）
# -----------------------------
@bot.tree.command(name="coin", description="自分のコインを確認する")
async def coin(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)

    await interaction.response.send_message(
        f"🪙 あなたのコイン：**{user_data[uid]['coins']}**",
        ephemeral=True
    )

# -----------------------------
# /point（自分のポイント確認）
# -----------------------------
@bot.tree.command(name="point", description="自分のポイントを確認する")
async def point(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user(uid)

    await interaction.response.send_message(
        f"💎 あなたのポイント：**{user_data[uid]['points']}pt**",
        ephemeral=True
    )

# -----------------------------
# /point set（管理者のみ）
# -----------------------------
@bot.tree.command(name="pointset", description="管理者専用：ポイントを設定する")
@discord.app_commands.checks.has_permissions(administrator=True)
async def pointset(interaction: discord.Interaction, user: discord.Member, amount: int):
    uid = str(user.id)
    ensure_user(uid)

    user_data[uid]["points"] = amount
    save_data()

    await interaction.response.send_message(
        f"🔧 {user.display_name} のポイントを **{amount}pt** に設定しました。",
        ephemeral=True
    )

# -----------------------------
# /shop（ポイント交換）
# -----------------------------
@bot.tree.command(name="shop", description="ポイントでロールやイベントを購入する")
async def shop(interaction: discord.Interaction, item: str):
    uid = str(interaction.user.id)
    ensure_user(uid)

    shop_items = {
        "event": {"cost": 20, "role": None},
        "bronze": {"cost": 50, "role": "ブロンズ"},
        "silver": {"cost": 70, "role": "シルバー"},
        "gold": {"cost": 90, "role": "ゴールド"},
        "diamond": {"cost": 150, "role": "ダイヤモンド"}
    }

    if item not in shop_items:
        await interaction.response.send_message(
            "購入可能なアイテム：event / bronze / silver / gold / diamond",
            ephemeral=True
        )
        return

    cost = shop_items[item]["cost"]
    role_name = shop_items[item]["role"]

    if user_data[uid]["points"] < cost:
        await interaction.response.send_message(
            f"ポイントが足りません。（必要: {cost}pt）",
            ephemeral=True
        )
        return

    user_data[uid]["points"] -= cost

    # イベント作成
    if item == "event":
        save_data()
        await interaction.response.send_message(
            "📅 **あなた専用のイベントが作成されました！**",
            ephemeral=True
        )
        return

    # ロール付与
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if role is None:
        await interaction.response.send_message(f"{role_name} ロールが存在しません。", ephemeral=True)
        return

    await interaction.user.add_roles(role)
    save_data()

    await interaction.response.send_message(
        f"🛒 **{role_name} ロール** を購入しました！",
        ephemeral=True
    )

# -----------------------------
# 特殊ロールの期限チェック（1分ごと）
# -----------------------------
@tasks.loop(seconds=60)
async def check_special_roles():
    now = time.time()

    for uid, data in user_data.items():
        entry = data.get("special_role")
        if not entry:
            continue

        if now > entry["expires_at"]:
            for guild in bot.guilds:
                member = guild.get_member(int(uid))
                role = guild.get_role(entry["role_id"])

                if member and role:
                    await member.remove_roles(role)

                try:
                    await role.edit(color=discord.Color(int("f1c40f", 16)))
                except:
                    pass

            data["special_role"] = None

    save_data()

@bot.event
async def on_ready():
    await bot.tree.sync()
    check_special_roles.start()
    print(f"ログイン完了: {bot.user}")





import asyncio
from aiohttp import web
from datetime import datetime, timedelta, timezone
import aiohttp_cors

PORT = int(os.getenv("PORT", 10000))  # Render が自動で割り当てる

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

    try:
        await site.start()
    except Exception as e:
        print(f"Webサーバー起動失敗: {e}")

    await asyncio.Future()  # 永久待機

async def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("FATAL ERROR: BOT_TOKEN が設定されていません。")
        return

    web_task = asyncio.create_task(start_web_server())
    bot_task = asyncio.create_task(bot.start(TOKEN))

    await asyncio.gather(web_task, bot_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot and Web Server stopped.")
    except Exception as e:
        print(f"メイン実行中にエラー: {e}")


# -----------------------------
# 起動
# -----------------------------
import os
TOKEN = os.getenv("BOT_TOKEN")
bot.run(TOKEN)
