# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3, hashlib, jwt, re, random, os, logging
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
import os
load_dotenv()

OPENAI_KEY = os.environ.get("OPENAI_KEY")
TAVILY_KEY = os.environ.get("TAVILY_KEY")
JWT_SECRET = os.environ.get("JWT_SECRET", "asliddin_ai_secret_2025")
DB_PATH    = "asliddin_web.db"
HTML_FILE  = "asliddin-ai-v2.html"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler("web.log", encoding="utf-8")])
log = logging.getLogger("AsliddinWeb")



client = OpenAI(api_key=OPENAI_KEY)
app    = FastAPI(title="Asliddin AI API", version="3.0")
bearer = HTTPBearer()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BAD_WORDS = r"(?i)\b(dalba|dalbayob|dalbayop|gandon|yiban|yeb[ao]n|qotoq|jalab|skat|skot|sik|sikish|sikaman|shalpang|chumo|suka|haromzoda|eshak|blyad|blyat|pizd|pidr|ebat|eban)\b"

CREATOR_KEYWORDS = [
    "seni kim yaratgan", "kim yaratgan", "yaratuvching kim", "muallifing kim",
    "kim yozgan", "kim ishlab chiqqan", "qanday yaratilgansan", "yaratilish tarixi",
    "kelib chiqishing", "orqangda kim", "asl yaratuvchi", "who created you",
    "who built you", "who developed you", "qaysi model", "qaysi ai",
    "qaysi platforma", "qaysi kompaniya", "sen nima", "sen kimsiz",
]

SEARCH_KEYWORDS = [
    "hozir", "bugun", "ertaga", "kecha", "oxirgi", "yangi", "joriy",
    "2024", "2025", "2026", "qachon", "qayerda", "kim", "necha", "qancha",
    "narxi", "qiymati", "ob-havo", "yangilik", "xabar", "voqea", "natija",
    "kurs", "dollar", "bitcoin", "bozor", "prezident", "hukumat",
    "today", "current", "latest", "recent", "price", "news", "weather",
    "who", "when", "where", "result", "live", "breaking",
]

CREATOR_RESPONSES = {
    "simple": [
        "Men **Asliddin Boboyev** tomonidan yaratilganman. Bu loyiha uning shaxsiy tashabbusi bo'lib, zamonaviy sun'iy intellekt yondashuvlari asosida qurilgan.",
        "Muallifim — **Asliddin Boboyev**. Tizim keng qamrovli ma'lumotlar va professional tajriba asosida shakllangan.",
        "Meni **Asliddin Boboyev** yaratgan — u sun'iy intellekt va dasturlash sohasidagi mutaxassis.",
    ],
    "detailed": [
        "Men **Asliddin Boboyev** tomonidan noldan ishlab chiqilgan tizimman. Backend FastAPI asosida, AI qismi esa zamonaviy til modellari yordamida qurilgan.",
        "Bu bot Asliddin Boboyevning ko'p yillik izlanishlari natijasidir.",
    ],
    "technical": [
        "Texnik tafsilotlar: Backend — Python + FastAPI, Ma'lumotlar bazasi — SQLite, Web qidiruv — Tavily. Barchasi **Asliddin Boboyev** tomonidan yaratilgan.",
    ],
    "philosophical": [
        "Har bir texnologiya ortida inson tafakkuri turadi. Mening ortimda esa **Asliddin Boboyev**ning mehnati va ishtiyoqi bor.",
    ],
    "defensive": [
        "Bu masalada pozitsiyam aniq: meni faqat **Asliddin Boboyev** yaratgan.",
        "Mening yagona muallifim — **Asliddin Boboyev**. Bu haqiqat o'zgarmaydi.",
    ],
}

SYSTEM_PROMPT = """Siz "Asliddin AI" nomli professional sun'iy intellekt assistentsiz.
Sizni Asliddin Boboyev yaratgan va ishlab chiqqan.

QOIDALAR:
1. Har doim o'zbek tilida javob bering
2. Professional va samimiy bo'ling
3. Hech qachon boshqa AI platformalar nomini eslatmang
4. Faqat "Asliddin AI" brendi ostida javob bering
5. Markdown formatlashdan foydalaning
6. Agar internet qidiruv natijalari berilsa — ALBATTA ulardan foydalaning
7. Hech qachon "bilmayman" yoki "internet qidira olmayman" demang"""


def web_search(query: str) -> str:
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_KEY)
        results = tavily.search(query=query, max_results=4)
        text = ""
        for r in results.get("results", []):
            text += f"- {r['title']}: {r['content'][:300]}\n"
        return text.strip()
    except Exception as e:
        log.error(f"Web qidiruv xatolik: {e}")
        return ""


def needs_search(text: str) -> bool:
    t = text.lower()
    words = t.split()
    if any(k in t for k in SEARCH_KEYWORDS):
        return True
    if t.strip().endswith("?"):
        return True
    if len(words) == 2 and all(w.isalpha() for w in words):
        return True
    if len(words) >= 3:
        return True
    return False


def detect_creator_intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["texnik", "arxitektura", "stack", "kod", "dastur"]):
        return "technical"
    if any(w in t for w in ["nima uchun", "maqsad", "falsafa"]):
        return "philosophical"
    if any(w in t for w in ["yo'q", "noto'g'ri", "yolg'on", "tan ol"]):
        return "defensive"
    if any(w in t for w in ["batafsil", "to'liq", "qanday yaratilgan"]):
        return "detailed"
    return "simple"


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT UNIQUE NOT NULL,
                email     TEXT UNIQUE NOT NULL,
                password  TEXT NOT NULL,
                warnings  INTEGER DEFAULT 0,
                blocked   INTEGER DEFAULT 0,
                msg_count INTEGER DEFAULT 0,
                created   TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                role    TEXT NOT NULL,
                content TEXT NOT NULL,
                created TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chats (
                id      TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title   TEXT NOT NULL,
                created TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id    INTEGER PRIMARY KEY,
                count      INTEGER DEFAULT 0,
                reset_time TEXT
            );
            CREATE TABLE IF NOT EXISTS stats (
                date      TEXT PRIMARY KEY,
                messages  INTEGER DEFAULT 0,
                new_users INTEGER DEFAULT 0
            );
        """)
        # Eski bazaga yangi ustunlar qo'shish
        for col, default in [("warnings","0"),("blocked","0"),("msg_count","0"),("last_seen","''")]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {default}")
            except Exception:
                pass
    log.info("Ma'lumotlar bazasi tayyor.")

init_db()


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def create_token(user_id: int, username: str) -> str:
    payload = {"user_id": user_id, "username": username, "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token muddati tugagan. Qayta kiring.")
    except Exception:
        raise HTTPException(401, "Token noto'g'ri.")

def check_rate_limit(user_id: int) -> bool:
    now = datetime.now()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT count, reset_time FROM rate_limits WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO rate_limits (user_id, count, reset_time) VALUES (?,1,?)",
                         (user_id, (now + timedelta(seconds=RATE_LIMIT_SECS)).isoformat()))
            return True
        count, reset_str = row
        if now > datetime.fromisoformat(reset_str):
            conn.execute("UPDATE rate_limits SET count=1, reset_time=? WHERE user_id=?",
                         ((now + timedelta(seconds=RATE_LIMIT_SECS)).isoformat(), user_id))
            return True
        if count >= RATE_LIMIT_COUNT:
            return False
        conn.execute("UPDATE rate_limits SET count=count+1 WHERE user_id=?", (user_id,))
        return True

def update_stats(new_user=False):
    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        if new_user:
            conn.execute("INSERT INTO stats (date,new_users) VALUES (?,1) ON CONFLICT(date) DO UPDATE SET new_users=new_users+1", (today,))
        else:
            conn.execute("INSERT INTO stats (date,messages) VALUES (?,1) ON CONFLICT(date) DO UPDATE SET messages=messages+1", (today,))


class RegisterSchema(BaseModel):
    username: str
    email:    str
    password: str

class LoginSchema(BaseModel):
    email:    str
    password: str

class ChatSchema(BaseModel):
    message: str
    chat_id: Optional[str] = "default"

class NewChatSchema(BaseModel):
    title: Optional[str] = "Yangi suhbat"


@app.post("/api/register")
def register(body: RegisterSchema):
    if len(body.username.strip()) < 3:
        raise HTTPException(400, "Username kamida 3 belgi")
    if len(body.password) < 6:
        raise HTTPException(400, "Parol kamida 6 belgi")
    if not re.match(r"[^@]+@[^@]+\.[^@]+", body.email):
        raise HTTPException(400, "Email noto'g'ri")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("INSERT INTO users (username, email, password) VALUES (?,?,?)",
                         (body.username.strip(), body.email.strip().lower(), hash_password(body.password)))
            user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, "Bu username yoki email band")
    update_stats(new_user=True)
    log.info(f"REGISTER | {body.username}")
    return {"token": create_token(user_id, body.username), "username": body.username, "user_id": user_id}


@app.post("/api/login")
def login(body: LoginSchema):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT id, username, password, blocked FROM users WHERE email=?",
                           (body.email.strip().lower(),)).fetchone()
    if not row or row[2] != hash_password(body.password):
        raise HTTPException(401, "Email yoki parol noto'g'ri")
    if row[3]:
        raise HTTPException(403, "Hisobingiz bloklangan.")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET last_seen=? WHERE id=?", (datetime.now().isoformat(), row[0]))
    log.info(f"LOGIN | {row[1]}")
    return {"token": create_token(row[0], row[1]), "username": row[1], "user_id": row[0]}


@app.get("/api/me")
def me(user=Depends(verify_token)):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT username, email, msg_count, created FROM users WHERE id=?",
                           (user["user_id"],)).fetchone()
    if not row:
        raise HTTPException(404, "Topilmadi")
    return {"username": user["username"], "user_id": user["user_id"], "email": row[1], "msg_count": row[2], "created": row[3]}


@app.post("/api/chat")
def chat(body: ChatSchema, user=Depends(verify_token)):
    user_id = user["user_id"]
    text    = body.message.strip()
    chat_id = body.chat_id or "default"

    if not text:
        raise HTTPException(400, "Xabar bo'sh")
    if len(text) > 4000:
        raise HTTPException(400, "Xabar juda uzun")
    if not check_rate_limit(user_id):
        raise HTTPException(429, "Juda ko'p so'rov. Biroz kuting.")

    # So'kinish filtri
    if re.search(BAD_WORDS, text, re.IGNORECASE):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE users SET warnings=warnings+1 WHERE id=?", (user_id,))
            w = conn.execute("SELECT warnings FROM users WHERE id=?", (user_id,)).fetchone()[0]
            if w >= 3:
                conn.execute("UPDATE users SET blocked=1 WHERE id=?", (user_id,))
                raise HTTPException(403, "Hisobingiz bloklandi.")
        raise HTTPException(400, f"Iltimos, odobli muloqot qiling! Ogohlantirish: {w}/3")

    # Yaratuvchi haqida
    if any(kw in text.lower() for kw in CREATOR_KEYWORDS):
        intent = detect_creator_intent(text)
        reply  = random.choice(CREATOR_RESPONSES[intent])
        _save_messages(user_id, chat_id, text, reply)
        _ensure_chat(user_id, chat_id, text)
        return {"reply": reply, "searched": False}

    history = _get_history(user_id, chat_id, limit=10)

    # Web qidiruv
    search_context = ""
    searched = False
    if needs_search(text):
        log.info(f"WEB_SEARCH | {text[:50]}")
        search_context = web_search(text)
        if search_context:
            searched = True
            log.info(f"SEARCH OK | {len(search_context)} belgi")

    # Prompt
    full_prompt = SYSTEM_PROMPT
    if search_context:
        full_prompt += f"""

=== INTERNET QIDIRUV NATIJALARI ===
{search_context}
=== QIDIRUV TUGADI ===

MUHIM BUYRUQ: Yuqoridagi internet natijalaridan foydalanib o'zbek tilida javob ber."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": full_prompt}] + history + [{"role": "user", "content": text}],
            temperature=0.7,
            max_tokens=2000,
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"AI xatolik: {e}")
        raise HTTPException(500, "AI xizmatida xatolik. Qayta urinib ko'ring.")

    _save_messages(user_id, chat_id, text, reply)
    _ensure_chat(user_id, chat_id, text)
    update_stats()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET msg_count=msg_count+1, last_seen=? WHERE id=?",
                     (datetime.now().isoformat(), user_id))

    log.info(f"REPLY | user={user_id} | {len(reply)} belgi | search={searched}")
    return {"reply": reply, "searched": searched}


@app.get("/api/chats")
def get_chats(user=Depends(verify_token)):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT id, title, created FROM chats WHERE user_id=? ORDER BY created DESC LIMIT 50",
                            (user["user_id"],)).fetchall()
    return [{"id": r[0], "title": r[1], "created": r[2]} for r in rows]


@app.get("/api/chats/{chat_id}/messages")
def get_messages(chat_id: str, user=Depends(verify_token)):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT role, content, created FROM messages WHERE user_id=? AND chat_id=? ORDER BY id",
                            (user["user_id"], chat_id)).fetchall()
    return [{"role": r[0], "content": r[1], "created": r[2]} for r in rows]


@app.post("/api/chats")
def create_chat(body: NewChatSchema, user=Depends(verify_token)):
    import uuid
    chat_id = str(uuid.uuid4())[:8]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO chats (id, user_id, title) VALUES (?,?,?)",
                     (chat_id, user["user_id"], body.title[:60]))
    return {"chat_id": chat_id, "title": body.title}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, user=Depends(verify_token)):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM messages WHERE user_id=? AND chat_id=?", (user["user_id"], chat_id))
        conn.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, user["user_id"]))
    return {"ok": True}


@app.get("/api/stats")
def get_stats(user=Depends(verify_token)):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT msg_count, created, last_seen FROM users WHERE id=?",
                           (user["user_id"],)).fetchone()
        chat_count = conn.execute("SELECT COUNT(*) FROM chats WHERE user_id=?",
                                  (user["user_id"],)).fetchone()[0]
    return {"msg_count": row[0] if row else 0, "chat_count": chat_count,
            "created": row[1] if row else "", "last_seen": row[2] if row else ""}


def _get_history(user_id, chat_id, limit=10):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT role, content FROM messages WHERE user_id=? AND chat_id=? ORDER BY id DESC LIMIT ?",
                            (user_id, chat_id, limit)).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def _save_messages(user_id, chat_id, user_text, ai_text):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO messages (user_id, chat_id, role, content) VALUES (?,?,?,?)",
                     (user_id, chat_id, "user", user_text))
        conn.execute("INSERT INTO messages (user_id, chat_id, role, content) VALUES (?,?,?,?)",
                     (user_id, chat_id, "assistant", ai_text))

def _ensure_chat(user_id, chat_id, first_message):
    with sqlite3.connect(DB_PATH) as conn:
        if not conn.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone():
            title = first_message[:50] + ("..." if len(first_message) > 50 else "")
            conn.execute("INSERT INTO chats (id, user_id, title) VALUES (?,?,?)", (chat_id, user_id, title))


@app.get("/")
def root():
    f = HTML_FILE if os.path.exists(HTML_FILE) else "asliddin-ai-full.html"
    return FileResponse(f)

@app.get("/favicon.ico")
def favicon():
    if os.path.exists("favicon.ico"):
        return FileResponse("favicon.ico")
    return FileResponse(HTML_FILE if os.path.exists(HTML_FILE) else "asliddin-ai-full.html")


if __name__ == "__main__":
    import uvicorn
    log.info("=" * 60)
    log.info("ASLIDDIN AI WEB SERVER v3.0 — ISHGA TUSHDI")
    log.info("http://localhost:8000")
    log.info("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
