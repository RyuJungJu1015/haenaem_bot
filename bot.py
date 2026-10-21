import discord
from discord.ext import commands
import datetime
import json
import os
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- [ 설정 파트 ] ---
TARGET_CHANNEL_NAME = "오늘도-해냄"
TOKEN = "MTU0MzQyOTQ5NDk3MzM5OTA0MA.GXPRed.CK_vCwkO-ZbTYeKt0rrCAYqDYGL4GXUQIOa-no"  # 👈 현재 직접 입력된 토큰
RESET_HOUR = 15  # 인증 기준 시각: 매일 오후 3시(한국 시간)
ALLOWED_EXTS = {
    "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp",  # 사진 + GIF
    "mp4", "mov", "webm", "m4v", "mkv", "avi",                   # 영상
}  # 올릴 수 있는 파일 종류
ALLOW_CAPTION = True  # 사진/영상과 함께 쓴 글(설명)을 허용할지. False로 바꾸면 글이 같이 있는 게시물도 삭제됨
# ----------------------

# 한국 시간(KST, UTC+9). Render 서버는 UTC라서 직접 맞춰줘야 함
KST = datetime.timezone(datetime.timedelta(hours=9))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "attendance_data.json"

# 인증 성공 시 랜덤으로 뽑아서 보내는 칭찬 문구 50개
# {mention} = 인증한 사람 멘션, {count} = 누적 인증 횟수 (이 두 가지 외의 중괄호는 쓰면 안 됨)
PRAISE_MESSAGES = [
    "👏 {mention}님, 오늘도 해냈네요! 정말 멋져요!",
    "🔥 {mention}님 오늘도 불태웠군요! 총 {count}회째, 대단해요!",
    "🌟 {mention}님, 꾸준함이 빛나고 있어요. {count}번째 인증 축하해요!",
    "💪 {mention}님이 또 해냈습니다! 오늘의 한 걸음, 멋졌어요!",
    "🎉 인증 성공! {mention}님 덕분에 서버가 더 힘을 내요!",
    "✨ {mention}님, 하루하루 쌓아 올린 노력이 정말 대단해요!",
    "🏃 {mention}님, 오늘도 멈추지 않고 해냈어요. 박수 짝짝짝!",
    "😆 오늘의 숙제 완료! {mention}님 최고예요!",
    "🌱 {mention}님의 작은 노력이 쑥쑥 자라고 있어요. {count}회째 인증 완료!",
    "🏅 {mention}님, 오늘도 금메달감이에요! 정말 잘했어요!",
    "🚀 {mention}님, 한 걸음 더 도약했어요! {count}회째 인증 성공!",
    "💯 오늘도 100점짜리 하루예요, {mention}님!",
    "🎊 {mention}님, 해냈다! 오늘도 해냈다! 정말 고생 많았어요!",
    "🥳 {mention}님 덕분에 오늘 채널이 더 반짝반짝해요!",
    "🌈 {mention}님, 힘든 날에도 해낸 오늘이 더 값져요. 수고했어요!",
    "👑 {mention}님은 오늘도 해냄의 주인공이에요! {count}회째 인증 성공!",
    "🍀 꾸준히 해내는 {mention}님, 좋은 일이 가득할 거예요!",
    "🙌 {mention}님, 오늘도 약속을 지켰네요. 정말 멋져요!",
    "⭐ 별처럼 빛나는 하루였어요, {mention}님! 인증 완료!",
    "🔔 딩동! {mention}님의 {count}번째 해냄이 도착했어요!",
    "🎯 {mention}님, 오늘 목표도 명중이에요! 잘했어요!",
    "🧗 {mention}님, 한 칸 한 칸 올라가고 있어요. 오늘도 수고했어요!",
    "😎 {mention}님, 오늘도 해냈다니... 역시 믿고 있었어요!",
    "🌞 {mention}님 덕분에 오늘 하루가 환해졌어요. 고생했어요!",
    "💖 {mention}님, 오늘의 노력에 진심으로 박수를 보내요!",
    "🥇 {mention}님, 어제의 나보다 한 걸음 더 나아갔어요! 멋져요!",
    "🎈 {mention}님, 오늘도 해냈으니 마음껏 뿌듯해해도 돼요!",
    "🌻 {mention}님의 꾸준함에 감탄이 나와요. 오늘도 잘했어요!",
    "🐣 {mention}님, 하루하루 성장하는 모습이 정말 대단해요!",
    "📈 {mention}님의 기록이 쑥쑥 올라가는 중이에요! 현재 {count}회, 굿굿!",
    "🎶 랄랄라~ {mention}님이 또 해냈어요! 기분 좋은 소식이네요!",
    "🍰 {mention}님, 오늘 고생한 만큼 달콤한 휴식도 챙기세요! 인증 완료!",
    "🧡 {mention}님, 오늘도 포기하지 않아서 고마워요. 정말 잘했어요!",
    "🛡️ {mention}님, 귀찮음을 이겨낸 오늘의 용사예요! 인증 성공!",
    "🚩 {mention}님, 오늘도 목표 지점에 깃발을 꽂았어요! 축하해요!",
    "🤩 와, {mention}님! 이 꾸준함 실화예요? 정말 대단해요!",
    "🌙 {mention}님, 오늘 하루도 알차게 채웠네요. 잘했어요!",
    "🥁 두구두구두구~ {mention}님의 인증, 합격입니다!",
    "🧩 {mention}님, 오늘도 한 조각을 멋지게 맞췄어요! 큰 그림이 완성되고 있어요!",
    "🍊 {mention}님의 상큼한 노력, 오늘도 잘 받았습니다! 짝짝짝!",
    "🪄 {mention}님이 오늘도 마법처럼 해냈어요! 대단해요!",
    "🦸 {mention}님, 오늘도 해냄 서버의 히어로예요! 멋져요!",
    "🌊 {mention}님, 작은 물결이 모여 큰 파도가 되고 있어요. {count}회째 인증 성공!",
    "🏆 {mention}님, 오늘도 트로피 하나 추가요! 수고했어요!",
    "😊 {mention}님, 오늘도 스스로와의 약속을 지켰네요. 참 잘했어요!",
    "🔥 {mention}님의 열정에 불이 붙었어요! 오늘도 활활 타올랐네요!",
    "🎁 {mention}님, 오늘의 해냄은 내일의 나에게 주는 선물이에요! 잘했어요!",
    "👏 {mention}님, 박수가 모자랄 정도예요! 오늘도 정말 고생했어요!",
    "🌟 {mention}님의 {count}번째 별이 떴어요! 오늘도 반짝반짝 빛났어요!",
    "💫 {mention}님, 오늘도 해냈다는 사실, 스스로 칭찬해 주세요! 정말 잘했어요!",
]

# 이모티콘이 바뀌는 단계 (이 횟수에 도달하면 이모티콘 변경, 다음 단계 전까지는 그대로 유지)
EMOJI_STAGES = [
    (50, "🏆"),
    (35, "👑"),
    (25, "💎"),
    (15, "⭐"),
    (10, "🔥"),
    (5,  "🌿"),
    (1,  "🐣"),
    (0,  "🌱"),
]
MAX_LEVEL = 50  # 역할이 존재하는 최대 횟수 (0회 ~ 50회)

def get_emoji(count):
    """현재 횟수에 해당하는 이모티콘 (직전 단계 이모티콘을 이어받음)"""
    for min_count, emoji in EMOJI_STAGES:
        if count >= min_count:
            return emoji
    return EMOJI_STAGES[-1][1]

def get_role_name(count):
    """횟수 -> 역할 이름. 예) 3 -> '🐣 해냄 3회' / 50회 초과는 50회 역할 유지"""
    level = max(0, min(count, MAX_LEVEL))
    return f"{get_emoji(level)} 해냄 {level}회"

# 0회 ~ 50회 전체 역할 이름 (51개)
ROLE_NAMES_ORDERED = [get_role_name(i) for i in range(MAX_LEVEL + 1)]
ALL_ROLE_NAMES = set(ROLE_NAMES_ORDERED)

async def ensure_roles(guild):
    """서버에 없는 해냄 역할을 자동으로 생성 (50회 -> 0회 순서로 만들어 목록에서 위에서부터 0회가 보이게 함)"""
    existing = {r.name for r in guild.roles}
    missing = [n for n in reversed(ROLE_NAMES_ORDERED) if n not in existing]
    if not missing:
        return
    print(f"🔧 [{guild.name}] 없는 역할 {len(missing)}개 생성 시작")
    for name in missing:
        try:
            await guild.create_role(name=name, reason="해냄이봇 역할 자동 생성")
        except discord.Forbidden:
            print(f"⚠️ [{guild.name}] 역할 생성 권한이 없습니다. 봇에게 '역할 관리' 권한을 주세요.")
            return
        except discord.HTTPException as e:
            print(f"⚠️ [{guild.name}] '{name}' 생성 실패: {e}")
    print(f"✅ [{guild.name}] 역할 생성 완료")

def is_allowed_attachment(att):
    """사진(이미지), GIF, 영상 파일만 허용. pdf/zip 같은 문서·기타 파일은 불허"""
    ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
    if ext not in ALLOWED_EXTS:
        return False
    ctype = att.content_type or ""
    # 확장자만 .mp4로 바꾼 문서 파일 같은 우회 방지: 실제 파일 형식도 이미지/영상이어야 함
    return ctype == "" or ctype.startswith(("image/", "video/"))

def get_cycle_date():
    """
    '인증 주기 날짜'를 반환.
    오후 3시를 하루의 시작으로 보기 때문에, 현재 한국 시간에서 15시간을 빼서 날짜를 구함.
    예) 10/21 14:59 -> 10/20 주기 / 10/21 15:00 -> 10/21 주기 / 10/22 14:59 -> 10/21 주기
    """
    now_kst = datetime.datetime.now(KST)
    shifted = now_kst - datetime.timedelta(hours=RESET_HOUR)
    return str(shifted.date())

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공! 봇 이름: {bot.user.name}")
    # 봇이 켜질 때마다 모든 서버에서 빠진 해냄 역할(0~50회)이 있는지 확인하고 만들어 둠
    for guild in bot.guilds:
        await ensure_roles(guild)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.name == TARGET_CHANNEL_NAME:
        # 사진(첨부파일) 확인
        if not message.attachments:
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention}님, 이 채널에는 인증 사진이나 영상을 함께 올려주셔야 합니다!", delete_after=5)
            return

        # 사진/GIF/영상이 아닌 파일(문서, 압축파일 등)이 하나라도 있으면 차단 (인증 횟수에도 반영 안 됨)
        if not all(is_allowed_attachment(a) for a in message.attachments):
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention}님, 사진, GIF, 영상 파일만 올릴 수 있어요! (문서나 압축파일 등은 올릴 수 없어요)", delete_after=5)
            return

        # 글이 같이 있는 게시물을 막고 싶을 때 (ALLOW_CAPTION = False)
        if not ALLOW_CAPTION and message.content.strip():
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention}님, 이 채널에는 글 없이 사진이나 영상만 올려주세요!", delete_after=5)
            return

        user_id = str(message.author.id)
        cycle = get_cycle_date()  # 오후 3시 기준 주기

        data = load_data()

        if user_id not in data:
            data[user_id] = {"count": 0, "last_date": ""}

        # 오후 3시 ~ 다음날 오후 3시 사이 1회 제한
        if data[user_id]["last_date"] == cycle:
            await message.delete()
            await message.channel.send(f"❌ {message.author.mention}님, 이번 인증은 이미 완료하셨습니다! 오후 3시 이후에 다시 도전해 주세요 🔥", delete_after=5)
            return

        # 인증 성공 처리
        data[user_id]["count"] += 1
        data[user_id]["last_date"] = cycle
        save_data(data)

        new_count = data[user_id]["count"]
        target_role_name = get_role_name(new_count)

        guild = message.guild
        member = message.author

        # 기존 해냄 관련 역할 전부 제거 후 새로운 역할 부여
        roles_to_remove = [r for r in member.roles if r.name in ALL_ROLE_NAMES and r.name != target_role_name]
        target_role = discord.utils.get(guild.roles, name=target_role_name)

        # 칭찬 문구 50개 중 랜덤으로 하나 뽑기
        praise = random.choice(PRAISE_MESSAGES).format(mention=member.mention, count=new_count)

        try:
            # 혹시 역할이 아직 없다면 그 자리에서 바로 생성
            if target_role is None:
                target_role = await guild.create_role(name=target_role_name, reason="해냄이봇 역할 자동 생성")

            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)

            if target_role and target_role not in member.roles:
                await member.add_roles(target_role)

            await message.add_reaction("👏")
            await message.channel.send(
                f"**{praise}**\n"
                f"현재 역할: `{target_role_name}`",
                delete_after=7
            )
        except discord.Forbidden:
            await message.add_reaction("👏")
            await message.channel.send(
                f"**{praise}**\n"
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