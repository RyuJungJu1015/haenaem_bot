import discord
from discord.ext import commands
import datetime
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- [ 설정 파트 ] ---
TARGET_CHANNEL_NAME = "오늘도-해냄"
TOKEN = "MTU0MzQyOTQ5NDk3MzM5OTA0MA.GXPRed.CK_vCwkO-ZbTYeKt0rrCAYqDYGL4GXUQIOa-no"  # 👈 현재 직접 입력된 토큰
# ----------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "attendance_data.json"

# 역할 단계 정의 (횟수: 역할 이름)
ROLE_STAGES = [
    (50, "🏆 해냄 50회"),
    (35, "👑 해냄 35회"),
    (25, "💎 해냄 25회"),
    (15, "⭐ 해냄 15회"),
    (10, "🔥 해냄 10회"),
    (5,  "🌿 해냄 5회"),
    (1,  "🐣 해냄 1회"),
    (0,  "🌱 해냄 0회")
]

ALL_ROLE_NAMES = [role_name for _, role_name in ROLE_STAGES]

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_target_role_name(count):
    """현재 횟수에 맞는 최고의 역할 이름을 반환"""
    for min_count, role_name in ROLE_STAGES:
        if count >= min_count:
            return role_name
    return "🌱 해냄 0회"

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공! 봇 이름: {bot.user.name}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.name == TARGET_CHANNEL_NAME:
        # 사진(첨부파일) 확인
        if not message.attachments:
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention}님, 이 채널에는 인증 사진을 함께 올려주셔야 합니다!", delete_after=5)
            return

        user_id = str(message.author.id)
        today = str(datetime.date.today())

        data = load_data()

        if user_id not in data:
            data[user_id] = {"count": 0, "last_date": ""}

        # 하루 1회 제한
        if data[user_id]["last_date"] == today:
            await message.delete()
            await message.channel.send(f"❌ {message.author.mention}님, 오늘 인증은 이미 완료하셨습니다! 내일 다시 도전해 주세요 🔥", delete_after=5)
            return

        # 인증 성공 처리
        data[user_id]["count"] += 1
        data[user_id]["last_date"] = today
        save_data(data)

        new_count = data[user_id]["count"]
        target_role_name = get_target_role_name(new_count)

        guild = message.guild
        member = message.author

        # 기존 해냄 관련 역할 전부 제거 후 새로운 역할 부여
        roles_to_remove = [r for r in member.roles if r.name in ALL_ROLE_NAMES and r.name != target_role_name]
        target_role = discord.utils.get(guild.roles, name=target_role_name)

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)

            if target_role and target_role not in member.roles:
                await member.add_roles(target_role)

            await message.add_reaction("👏")
            await message.channel.send(
                f"🎉 **{member.mention}님 총 {new_count}회째 인증 성공!**\n"
                f"현재 역할: `{target_role_name}`",
                delete_after=7
            )
        except discord.Forbidden:
            await message.add_reaction("👏")
            await message.channel.send(
                f"🎉 **{member.mention}님 총 {new_count}회째 인증 성공!**\n"
                f"⚠️ (봇의 역할 순위가 낮거나 권한이 부족하여 역할을 변경하지 못했습니다. 서버 설정에서 봇 역할을 다른 해냄 역할보다 상단으로 올려주세요!)",
                delete_after=10
            )

    await bot.process_commands(message)

# --- Render 포트 바인딩용 더미 웹 서버 (업타임로봇 대응 완료) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def do_HEAD(self):
        # 업타임로봇이 핑을 쏠 때 거부하지 않고 200 OK로 정상 응답
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # 불필요한 핑 로그가 터미널을 도배하는 것 방지
        return

def run_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

# 백그라운드로 웹 서버 먼저 실행
threading.Thread(target=run_server, daemon=True).start()

# --- 봇 실행 (반드시 파일 맨 마지막) ---
bot.run(TOKEN)