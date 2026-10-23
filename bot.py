import asyncio
import datetime
import json
import os
import random
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import aiohttp
import discord
from discord.ext import commands

# --- [ 설정 파트 ] ---
TARGET_CHANNEL_NAME = "오늘도-해냄"  # 인증을 받는 일반 텍스트 채널 이름
FORUM_CHANNEL_NAMES = ["오늘도-해냄"]  # 인증을 받는 '포럼 채널' 이름들. 포럼 게시물에 사진/영상을 올리면 댓글로 칭찬해요. 이름이 다르면 따옴표로 감싸서 바꾸거나 쉼표로 추가하세요. 예) ["인증-포럼", "오늘도-해냄"]
FORUM_DELETE_AFTER = None  # 포럼 게시물에 단 칭찬 댓글이 사라지기까지의 시간(초). None이면 지우지 않고 계속 남겨둠

DAILY_LIMIT = 5  # 하루(오후 3시~다음날 오후 3시)에 인증으로 인정되는 최대 사진/영상 게시물 수. 모두 인증 횟수로 쌓임
UNLIMITED_USER_IDS = [1048357326605779116]  # 하루 제한 없이 올릴 수 있는 사람의 디스코드 ID 목록(숫자). 예) [123456789012345678]. 서버의 .env에 UNLIMITED_USER_IDS=아이디 로 넣어도 돼요 (여러 명이면 쉼표로)
MILESTONE_CHANNEL_NAME = "관리자-화이팅-입니당"  # 50회, 100회... 달성을 알려줄 관리자 채널 이름
MILESTONE_EVERY = 50  # 몇 번 인증할 때마다 관리자 채널에 알릴지 (0이면 알리지 않음)
MILESTONE_MESSAGE = "🎉 {mention}님이 {count}번 인증을 완료하였습니다! 격려해 주세요 👏"
TOKEN = os.getenv("DISCORD_TOKEN", "")  # 봇 토큰은 코드에 쓰지 않고 서버의 환경변수(DISCORD_TOKEN)에만 넣어요
if not TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN 환경변수가 없어요. 서버 설정에 봇 토큰을 넣어주세요.")
RESET_HOUR = 15  # 인증 기준 시각: 매일 오후 3시(한국 시간)
ALLOWED_EXTS = {
    "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp",  # 사진 + GIF
    "mp4", "mov", "webm", "m4v", "mkv", "avi",                   # 영상
}  # 올릴 수 있는 파일 종류
ALLOW_CAPTION = True  # 사진/영상과 함께 쓴 글(설명)을 허용할지. False로 바꾸면 글이 같이 있는 게시물도 삭제됨

GIF_CHANCE = 1.0              # 칭찬에 GIF를 붙일 확률 (1.0 = 항상, 0.5 = 절반, 0 = 안 붙임). GIF 링크가 없는 캐릭터는 자동으로 안 붙음
DELETE_AFTER_WITH_GIF = 15    # GIF가 붙은 칭찬 메시지가 사라지기까지의 시간(초)
DELETE_AFTER_NO_GIF = 10      # GIF가 없는 칭찬 메시지가 사라지기까지의 시간(초)
# ----------------------

# Supabase 연결 정보는 코드에 쓰지 말고 Render의 환경변수(Environment)에만 넣으세요
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[: -len("/rest/v1")]
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
USE_DB = bool(SUPABASE_URL and SUPABASE_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHARACTERS_FILE = os.path.join(BASE_DIR, "characters.json")
DATA_FILE = os.path.join(BASE_DIR, "attendance_data.json")          # Supabase를 못 쓸 때만 사용하는 임시 저장 파일
CHAR_LOCAL_FILE = os.path.join(BASE_DIR, "user_characters.json")    # 위와 같은 이유

# 한국 시간(KST, UTC+9). Render 서버는 UTC라서 직접 맞춰줘야 함
KST = datetime.timezone(datetime.timedelta(hours=9))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def _load_unlimited_ids():
    """코드의 목록 + 환경변수(UNLIMITED_USER_IDS)의 아이디를 합쳐서 숫자 집합으로 만듦"""
    ids = set()
    raw = list(UNLIMITED_USER_IDS) + os.getenv("UNLIMITED_USER_IDS", "").replace(" ", "").split(",")
    for x in raw:
        if str(x).strip().isdigit():
            ids.add(int(str(x).strip()))
    return ids


UNLIMITED_IDS = _load_unlimited_ids()


# =====================================================================
# 캐릭터 문구 불러오기 (characters.json)
# =====================================================================
FALLBACK_ACHIEVEMENT = "{mention}님, 인증 {count}회 달성하셨습니다! 🎉"
FALLBACK_CHARACTERS = [{
    "key": "default", "name": "기본", "description": "해냄이 기본 말투",
    "messages": ["👏 {mention}님, 오늘도 해냈네요! 정말 멋져요!"], "gifs": [],
}]


def load_characters():
    """characters.json을 읽어옵니다. 파일이 없거나 깨져 있어도 봇이 멈추지 않도록 기본 문구로 대체합니다."""
    try:
        with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        chars = data["characters"]
        if not chars or not any(c["key"] == "default" for c in chars):
            raise ValueError("기본(default) 캐릭터가 없어요")
        for c in chars:
            if not c.get("messages"):
                raise ValueError(f"{c.get('name')} 캐릭터의 문구가 비어 있어요")
        return data.get("achievement_message") or FALLBACK_ACHIEVEMENT, chars
    except Exception as e:  # noqa
        print(f"⚠️ characters.json을 읽지 못해서 기본 문구로 대체합니다: {e}")
        return FALLBACK_ACHIEVEMENT, FALLBACK_CHARACTERS


ACHIEVEMENT_MESSAGE, _CHAR_LIST = load_characters()
CHARACTERS = {c["key"]: c for c in _CHAR_LIST}   # key -> 캐릭터 정보
CHARACTER_ORDER = [c["key"] for c in _CHAR_LIST]  # 선택창에 보여줄 순서


def pick_praise(selected_keys, mention, count):
    """
    사용자가 고른 캐릭터들 중 한 명을 먼저 뽑고(캐릭터별 같은 확률), 그 캐릭터의 문구 중 하나를 뽑습니다.
    반환: (캐릭터 정보, 완성된 칭찬 문구)
    """
    keys = [k for k in selected_keys if k in CHARACTERS] or ["default"]
    ch = CHARACTERS[random.choice(keys)]
    text = random.choice(ch["messages"]).format(mention=mention, count=count)
    return ch, text


def pick_gif(ch):
    gifs = ch.get("gifs") or []
    if gifs and random.random() < GIF_CHANCE:
        return random.choice(gifs)
    return None


# =====================================================================
# 저장소 (Supabase). 환경변수가 없으면 임시로 로컬 파일을 씁니다 (재배포하면 초기화됨)
# =====================================================================
class DBError(Exception):
    pass


_session = None


def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
    return _session


def _headers(prefer=None):
    h = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):  # 예전 방식(JWT) 키는 Authorization 헤더도 필요
        h["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if prefer:
        h["Prefer"] = prefer
    return h


async def _request(method, table, params=None, body=None, prefer=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    last_err = None
    for attempt in range(2):  # 일시적인 네트워크 오류는 한 번 더 시도
        try:
            async with get_session().request(
                method, url, params=params, json=body, headers=_headers(prefer)
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise DBError(f"Supabase 오류 {resp.status}: {text[:200]}")
                return json.loads(text) if text else None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = e
            await asyncio.sleep(0.5)
    raise DBError(f"Supabase 연결 실패: {last_err!r}")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _read_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


async def get_attendance(user_id):
    """{'count': 누적 횟수, 'last_date': 마지막 인증 주기, 'today_count': 그 주기에 인증한 횟수} 반환 (처음이면 0회)"""
    if USE_DB:
        rows = await _request("GET", "haenaem_attendance",
                              params={"user_id": f"eq.{user_id}", "select": "count,last_date,today_count"})
        if rows:
            r = rows[0]
            return {"count": int(r["count"]), "last_date": r["last_date"] or "",
                    "today_count": int(r.get("today_count") or 0)}
        return {"count": 0, "last_date": "", "today_count": 0}
    rec = _read_json(DATA_FILE).get(user_id, {})
    return {"count": int(rec.get("count", 0)), "last_date": rec.get("last_date", ""),
            "today_count": int(rec.get("today_count", 0))}


async def save_attendance(user_id, count, last_date, today_count):
    if USE_DB:
        await _request("POST", "haenaem_attendance", params={"on_conflict": "user_id"},
                       body=[{"user_id": user_id, "count": count, "last_date": last_date,
                              "today_count": today_count, "updated_at": _now_iso()}],
                       prefer="resolution=merge-duplicates,return=minimal")
        return
    data = _read_json(DATA_FILE)
    data[user_id] = {"count": count, "last_date": last_date, "today_count": today_count}
    _write_json(DATA_FILE, data)


async def get_ranking(limit=10):
    """누적 인증 횟수가 많은 순서로 [(user_id, count), ...] 반환 (0회는 제외)"""
    if USE_DB:
        rows = await _request("GET", "haenaem_attendance",
                              params={"select": "user_id,count", "order": "count.desc", "limit": str(limit)})
        pairs = [(str(r["user_id"]), int(r["count"])) for r in (rows or [])]
    else:
        data = _read_json(DATA_FILE)
        pairs = [(str(uid), int(v.get("count", 0))) for uid, v in data.items() if isinstance(v, dict)]
        pairs.sort(key=lambda p: p[1], reverse=True)
        pairs = pairs[:limit]
    return [p for p in pairs if p[1] > 0]


async def get_user_characters(user_id):
    """사용자가 고른 캐릭터 key 목록. 고른 적 없으면 ['default'](기본)"""
    keys = None
    if USE_DB:
        rows = await _request("GET", "haenaem_user_characters",
                              params={"user_id": f"eq.{user_id}", "select": "characters"})
        if rows:
            keys = rows[0]["characters"]
    else:
        keys = _read_json(CHAR_LOCAL_FILE).get(user_id)
    keys = [k for k in (keys or []) if k in CHARACTERS]
    return keys or ["default"]


async def set_user_characters(user_id, keys):
    if USE_DB:
        await _request("POST", "haenaem_user_characters", params={"on_conflict": "user_id"},
                       body=[{"user_id": user_id, "characters": keys, "updated_at": _now_iso()}],
                       prefer="resolution=merge-duplicates,return=minimal")
        return
    data = _read_json(CHAR_LOCAL_FILE)
    data[user_id] = keys
    _write_json(CHAR_LOCAL_FILE, data)


async def check_db_and_import_legacy():
    """
    봇이 켜질 때 한 번 실행:
    1) Supabase 연결과 표가 제대로 있는지 확인해서 문제가 있으면 로그에 알려줌
    2) 인증 표가 비어 있고 예전 attendance_data.json이 있으면 기존 인증 횟수를 자동으로 옮겨 옴
    """
    if not USE_DB:
        print("⚠️ [저장소] SUPABASE_URL / SUPABASE_KEY 환경변수가 없어서 임시 파일에 저장합니다. "
              "(Render가 재배포되면 인증 횟수가 초기화돼요!)")
        return
    try:
        rows = await _request("GET", "haenaem_attendance", params={"select": "user_id", "limit": "1"})
        await _request("GET", "haenaem_user_characters", params={"select": "user_id", "limit": "1"})
    except DBError as e:
        print(f"❌ [저장소] Supabase 확인 실패: {e}")
        print("   -> 주소(SUPABASE_URL), 키(SUPABASE_KEY), 표 만들기(supabase_setup.sql 실행)를 확인해 주세요.")
        return
    print("✅ [저장소] Supabase 연결 확인 완료")
    if rows:
        return
    legacy = _read_json(DATA_FILE)
    batch = [{"user_id": str(uid), "count": int(v.get("count", 0)), "last_date": str(v.get("last_date", "")),
              "today_count": int(v.get("today_count", 0))}
             for uid, v in legacy.items() if isinstance(v, dict)]
    if not batch:
        return
    try:
        await _request("POST", "haenaem_attendance", params={"on_conflict": "user_id"}, body=batch,
                       prefer="resolution=merge-duplicates,return=minimal")
        print(f"✅ [저장소] 예전 attendance_data.json의 인증 기록 {len(batch)}명을 Supabase로 옮겼어요")
    except DBError as e:
        print(f"⚠️ [저장소] 예전 기록 옮기기 실패: {e}")


_user_locks = {}


def get_user_lock(user_id):
    """같은 사람이 동시에 여러 장 올려도 횟수가 꼬이지 않도록 사람별로 줄 세우기"""
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


# =====================================================================
# 반응 이모티콘 / 파일 검사
# =====================================================================
# 인증 성공 시 인증 사진에 랜덤으로 하나 달아주는 반응 이모티콘 50개
REACTION_EMOJIS = [
    "👏", "🎉", "🔥", "💪", "⭐", "🌟", "✨", "💯", "🏆", "🥇",
    "🏅", "🎊", "🥳", "😆", "😎", "🤩", "😊", "💖", "🧡", "💙",
    "💚", "💜", "🚀", "🎯", "👍", "🙌", "👑", "🌈", "🍀", "🌻",
    "🌞", "🎈", "🎁", "🍰", "🥁", "🎶", "🔔", "🌱", "🐣", "📈",
    "🧗", "🏃", "🦸", "🌊", "🪄", "🍊", "🧩", "🚩", "💫", "🥰",
]


async def add_random_reaction(message):
    """랜덤 이모티콘 반응을 추가. 혹시 실패하면 기본 👏로 한 번 더 시도하고, 그것도 안 되면 조용히 넘어감(칭찬 메시지는 계속 나감)"""
    for emoji in (random.choice(REACTION_EMOJIS), "👏"):
        try:
            await message.add_reaction(emoji)
            return
        except discord.HTTPException:
            continue


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


# =====================================================================
# /캐릭터 명령어 (칭찬해 줄 캐릭터 고르기)
# =====================================================================
class CharacterSelect(discord.ui.Select):
    def __init__(self, selected):
        options = [
            discord.SelectOption(
                label=CHARACTERS[k]["name"],
                value=k,
                description=(CHARACTERS[k].get("description") or "")[:100] or None,
                default=(k in selected),
            )
            for k in CHARACTER_ORDER
        ]
        super().__init__(
            placeholder="칭찬해 줄 캐릭터를 골라주세요 (여러 명 가능)",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        keys = [k for k in CHARACTER_ORDER if k in self.values]
        try:
            await set_user_characters(str(interaction.user.id), keys)
        except Exception as e:  # noqa
            print(f"⚠️ 캐릭터 저장 실패: {e}")
            await interaction.response.edit_message(
                content="⚠️ 저장소에 잠깐 문제가 생겨서 저장하지 못했어요. 잠시 후 다시 시도해 주세요!", view=None)
            return
        names = ", ".join(CHARACTERS[k]["name"] for k in keys)
        await interaction.response.edit_message(
            content=f"✅ 저장했어요! 이제 인증하면 **{names}** 중에서 랜덤으로 칭찬해 드릴게요.", view=None)


class CharacterView(discord.ui.View):
    def __init__(self, selected):
        super().__init__(timeout=180)
        self.add_item(CharacterSelect(selected))


@bot.tree.command(name="캐릭터", description="인증할 때 칭찬해 줄 캐릭터를 고릅니다")
async def character_command(interaction: discord.Interaction):
    # 저장소 응답이 느려도 3초 제한에 걸리지 않도록 먼저 '생각 중' 표시를 보냄
    await interaction.response.defer(ephemeral=True)
    try:
        selected = await get_user_characters(str(interaction.user.id))
    except Exception as e:  # noqa
        print(f"⚠️ 캐릭터 불러오기 실패: {e}")
        selected = ["default"]
    names = ", ".join(CHARACTERS[k]["name"] for k in selected if k in CHARACTERS)
    await interaction.followup.send(
        f"지금 선택된 캐릭터: **{names}**\n아래에서 원하는 캐릭터를 모두 골라주세요. 고른 캐릭터들 중에서 랜덤으로 칭찬해 드려요!",
        view=CharacterView(selected),
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    print(f"⚠️ 명령어 오류: {error!r}")


# =====================================================================
# /랭킹 명령어 (인증을 가장 많이 한 사람 TOP 10)
# =====================================================================
@bot.tree.command(name="랭킹", description="인증을 가장 많이 한 사람 TOP 10을 보여줍니다")
async def ranking_command(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        ranking = await get_ranking(10)
    except Exception as e:  # noqa
        print(f"⚠️ 랭킹 불러오기 실패: {e}")
        await interaction.followup.send("⚠️ 저장소에 잠깐 문제가 생겨서 랭킹을 불러오지 못했어요. 잠시 후 다시 시도해 주세요!", ephemeral=True)
        return
    if not ranking:
        await interaction.followup.send("아직 인증 기록이 없어요. 첫 인증의 주인공이 되어보세요! 🔥")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, count) in enumerate(ranking):
        mark = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mark} <@{uid}> — {count}회")
    await interaction.followup.send("🏆 **해냄 랭킹 TOP 10**\n" + "\n".join(lines),
                                    allowed_mentions=discord.AllowedMentions.none())


async def sync_commands_for_guild(guild):
    """슬래시 명령어를 서버에 바로 등록 (서버 전용 등록은 즉시 반영됨)"""
    try:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"✅ [{guild.name}] /캐릭터, /랭킹 명령어 등록 완료")
    except discord.Forbidden:
        print(f"⚠️ [{guild.name}] 명령어 등록 권한이 없어요. 봇 초대 링크에 'applications.commands'를 체크해서 다시 초대해 주세요.")
    except discord.HTTPException as e:
        print(f"⚠️ [{guild.name}] 명령어 등록 실패: {e}")


_ready_done = False


@bot.event
async def on_ready():
    global _ready_done
    print(f"✅ 로그인 성공! 봇 이름: {bot.user.name}")
    if _ready_done:  # 연결이 끊겼다 다시 붙을 때 중복 실행 방지
        return
    _ready_done = True
    await check_db_and_import_legacy()
    if UNLIMITED_IDS:
        print(f"ℹ️ 하루 제한 없는 사용자 {len(UNLIMITED_IDS)}명 등록됨")
    for guild in bot.guilds:
        await sync_commands_for_guild(guild)
        if MILESTONE_EVERY > 0 and discord.utils.get(guild.text_channels, name=MILESTONE_CHANNEL_NAME) is None:
            print(f"⚠️ [{guild.name}] 관리자 알림 채널 '{MILESTONE_CHANNEL_NAME}'을 찾지 못했어요. "
                  f"{MILESTONE_EVERY}회 달성 알림이 가지 않아요. 코드 위쪽 MILESTONE_CHANNEL_NAME을 확인해 주세요.")


@bot.event
async def on_guild_join(guild):
    await sync_commands_for_guild(guild)


# =====================================================================
# 인증 처리
# =====================================================================
THREAD_TYPES = (discord.ChannelType.public_thread, discord.ChannelType.private_thread,
                discord.ChannelType.news_thread)


async def get_thread_parent(thread):
    """포럼 게시물(스레드)이 속한 부모 채널. 캐시에 없으면 디스코드에서 직접 가져옴"""
    parent = thread.parent
    if parent is None and getattr(thread, "parent_id", None):
        try:
            parent = await bot.fetch_channel(thread.parent_id)
        except discord.HTTPException:
            parent = None
    return parent


async def get_channel_kind(channel):
    """
    인증을 받는 곳인지 구분
    - "text"  : 인증 텍스트 채널 (TARGET_CHANNEL_NAME)
    - "forum" : 인증 포럼 채널 안의 게시물 (FORUM_CHANNEL_NAMES)
    - None    : 인증과 상관없는 곳
    """
    # 막 만들어진 포럼 게시물은 아직 봇이 모르는 채널로 올 수 있어서 한 번 더 조회
    if isinstance(channel, discord.PartialMessageable) and channel.type in THREAD_TYPES:
        try:
            channel = await bot.fetch_channel(channel.id)
        except discord.HTTPException:
            return None
    if isinstance(channel, discord.Thread):
        parent = await get_thread_parent(channel)
        if isinstance(parent, discord.ForumChannel) and parent.name in FORUM_CHANNEL_NAMES:
            return "forum"
        return None
    if getattr(channel, "name", None) == TARGET_CHANNEL_NAME:
        return "text"
    return None


async def safe_send(channel, *args, **kwargs):
    """메시지 보내기. 권한이 없어도 봇이 멈추지 않고 로그에만 남김"""
    try:
        return await channel.send(*args, **kwargs)
    except discord.Forbidden:
        print(f"⚠️ [{channel}] 메시지를 보낼 권한이 없어요. 포럼이라면 봇에게 '게시물에서 메시지 보내기' 권한을 주세요.")
    except discord.HTTPException as e:
        print(f"⚠️ 메시지 전송 실패: {e}")
    return None


async def notify_milestone(guild, member, count):
    """50회, 100회... 단위로 달성하면 관리자 채널에 알림 (알림이 실패해도 인증은 그대로 진행)"""
    if MILESTONE_EVERY <= 0 or count % MILESTONE_EVERY != 0:
        return
    channel = discord.utils.get(guild.text_channels, name=MILESTONE_CHANNEL_NAME)
    if channel is None:
        print(f"⚠️ 관리자 알림 채널 '{MILESTONE_CHANNEL_NAME}'을 찾지 못해 {count}회 달성 알림을 보내지 못했어요")
        return
    await safe_send(channel, MILESTONE_MESSAGE.format(mention=member.mention, count=count),
                    allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    kind = await get_channel_kind(message.channel)
    is_forum = kind == "forum"
    # 포럼 게시물의 첫 글(게시물 본문)은 글 번호가 게시물 번호와 같음
    is_starter = is_forum and getattr(message.channel, "id", None) == message.id

    async def reject(text, delete_after=5):
        """인증으로 인정할 수 없을 때: 텍스트 채널은 게시물을 지우고 안내, 포럼은 게시물은 두고 댓글로만 안내"""
        if is_forum:
            await safe_send(message.channel, text + " (이 게시물은 인증으로 기록되지 않았어요)", delete_after=15)
        else:
            try:
                await message.delete()
            except discord.HTTPException as e:
                print(f"⚠️ 게시물을 지우지 못했어요(봇에게 '메시지 관리' 권한이 필요해요): {e}")
            await safe_send(message.channel, text, delete_after=delete_after)

    # 포럼 게시물 안의 '글만 있는 댓글'은 평범한 대화이므로 건드리지 않음 (게시물 본문은 사진이 꼭 필요)
    if kind == "text" or (is_forum and (message.attachments or is_starter)):
        # 사진(첨부파일) 확인
        if not message.attachments:
            await reject(f"⚠️ {message.author.mention}님, 이 채널에는 인증 사진이나 영상을 함께 올려주셔야 합니다!")
            return

        # 사진/GIF/영상이 아닌 파일(문서, 압축파일 등)이 하나라도 있으면 차단 (인증 횟수에도 반영 안 됨)
        if not all(is_allowed_attachment(a) for a in message.attachments):
            await reject(f"⚠️ {message.author.mention}님, 사진, GIF, 영상 파일만 올릴 수 있어요! (문서나 압축파일 등은 올릴 수 없어요)")
            return

        # 글이 같이 있는 게시물을 막고 싶을 때 (ALLOW_CAPTION = False)
        if not ALLOW_CAPTION and message.content.strip():
            await reject(f"⚠️ {message.author.mention}님, 이 채널에는 글 없이 사진이나 영상만 올려주세요!")
            return

        user_id = str(message.author.id)
        cycle = get_cycle_date()  # 오후 3시 기준 주기
        is_unlimited = message.author.id in UNLIMITED_IDS

        try:
            async with get_user_lock(user_id):
                record = await get_attendance(user_id)

                # 같은 주기(오후 3시~다음날 오후 3시)에서 지금까지 인증한 횟수 (새 주기면 0부터)
                today = record["today_count"] if record["last_date"] == cycle else 0

                if not is_unlimited and today >= DAILY_LIMIT:
                    await reject(f"❌ {message.author.mention}님, 오늘은 {DAILY_LIMIT}번 모두 인증하셨습니다! 오후 3시 이후에 다시 도전해 주세요 🔥", delete_after=8)
                    return

                # 인증 성공 처리 (저장에 실패하면 횟수를 올리지 않고 아래 except로 이동)
                new_count = record["count"] + 1
                new_today = today + 1
                await save_attendance(user_id, new_count, cycle, new_today)
        except DBError as e:
            print(f"❌ 저장소 오류: {e}")
            await safe_send(message.channel, f"⚠️ {message.author.mention}님, 저장소에 잠깐 문제가 생겨서 인증을 기록하지 못했어요. 잠시 후 다시 올려주세요!", delete_after=10)
            return

        # 사용자가 고른 캐릭터 불러오기 (실패해도 기본 캐릭터로 칭찬은 계속 진행)
        try:
            selected = await get_user_characters(user_id)
        except DBError as e:
            print(f"⚠️ 캐릭터 설정을 불러오지 못해 기본으로 진행: {e}")
            selected = ["default"]

        member = message.author

        # 고른 캐릭터 중 한 명을 뽑고, 그 캐릭터의 문구 중 하나를 랜덤으로 뽑기
        ch, praise = pick_praise(selected, member.mention, new_count)
        achievement = ACHIEVEMENT_MESSAGE.format(mention=member.mention, count=new_count)  # 캐릭터와 상관없이 항상 같이 나가는 문구
        gif_url = pick_gif(ch)
        if is_unlimited:
            last_line = f"오늘 인증 {new_today}회 (무제한)"
        else:
            last_line = f"오늘 인증 {new_today}/{DAILY_LIMIT}회"
        # 텍스트 채널은 일정 시간 뒤 칭찬 메시지를 지우고, 포럼은 댓글로 계속 남겨둠 (FORUM_DELETE_AFTER)
        if is_forum:
            delete_after = FORUM_DELETE_AFTER
        else:
            delete_after = DELETE_AFTER_WITH_GIF if gif_url else DELETE_AFTER_NO_GIF

        async def send_praise():
            text = f"**[{ch['name']}] {praise}**\n{achievement}\n{last_line}"
            if gif_url:
                try:
                    embed = discord.Embed()
                    embed.set_image(url=gif_url)
                    await message.channel.send(text, embed=embed, delete_after=delete_after)
                    return
                except discord.Forbidden:
                    print(f"⚠️ [{message.channel}] 메시지를 보낼 권한이 없어요. 포럼이라면 봇에게 '게시물에서 메시지 보내기' 권한을 주세요.")
                    return
                except discord.HTTPException as e:
                    print(f"⚠️ GIF를 붙이지 못해 글만 보냅니다 ({gif_url}): {e}")
            await safe_send(message.channel, text, delete_after=delete_after)

        await add_random_reaction(message)
        await send_praise()
        await notify_milestone(message.guild, member, new_count)

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


RETRY_WAIT_SECONDS = 900  # 디스코드 접속에 실패했을 때 다시 시도하기 전에 쉬는 시간(초). 15분


if __name__ == "__main__":
    # 백그라운드로 웹 서버 먼저 실행
    threading.Thread(target=run_server, daemon=True).start()

    # --- 봇 실행 (반드시 파일 맨 마지막) ---
    try:
        bot.run(TOKEN)
    except Exception as e:  # noqa
        # 접속에 실패하면 바로 죽고 다시 켜지는 일을 반복하면 디스코드가 더 오래 막으므로, 쉬었다가 종료(= Render가 다시 켬)
        # 쉬는 동안에도 위의 가짜 웹사이트는 계속 응답하므로 업타임로봇/Render는 정상으로 봄
        status = getattr(e, "status", "-")
        print(f"❌ 디스코드 접속에 실패했어요 (종류={type(e).__name__}, 상태={status}): {str(e)[:200]}")
        print("   -> 흔한 원인: Render 공용 IP가 디스코드(Cloudflare)에 일시 차단됨(429), 또는 토큰 오류(401)")
        print(f"⏳ {RETRY_WAIT_SECONDS}초 쉬었다가 다시 시작합니다")
        time.sleep(RETRY_WAIT_SECONDS)
        sys.exit(1)