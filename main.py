import os
import re
import time
import sqlite3
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import yt_dlp
from google import genai

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = 8190105957  # Your Telegram ID

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

user_sessions = {}

# --- 1. SQLITE DATABASE FOR TRACKING USERS ---
db_lock = threading.Lock()
conn = sqlite3.connect('bot_users.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        requests_count INTEGER DEFAULT 0,
        last_seen TEXT
    )
''')
conn.commit()

def log_user_activity(user_id, first_name, username, is_video=False):
    with db_lock:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('SELECT requests_count FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        
        if row is None:
            # Brand new user!
            count = 1 if is_video else 0
            cursor.execute(
                'INSERT INTO users (user_id, first_name, username, requests_count, last_seen) VALUES (?, ?, ?, ?, ?)',
                (user_id, first_name, username, count, now)
            )
            conn.commit()
            # Notify Admin
            try:
                bot.send_message(
                    ADMIN_ID, 
                    f"🔔 *New User Alert!*\nName: {first_name}\nUsername: @{username or 'None'}\nID: `{user_id}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            # Existing user
            add_count = 1 if is_video else 0
            new_count = row[0] + add_count
            cursor.execute(
                'UPDATE users SET first_name = ?, username = ?, requests_count = ?, last_seen = ? WHERE user_id = ?',
                (first_name, username, new_count, now, user_id)
            )
            conn.commit()

# --- 2. KEEP-ALIVE SERVER FOR RENDER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# --- 3. ULTRA-FAST DOWNLOADER (360p/480p) ---
def extract_url(text):
    urls = re.findall(r'(https?://[^\s]+)', text)
    return urls[0] if urls else None

def download_video_fast(url, output_path="short.mp4"):
    if os.path.exists(output_path):
        os.remove(output_path)
        
    # Prioritize 360p/480p low-res for instant 2-second download
    ydl_opts = {
        'format': 'worst[ext=mp4]/best[height<=360][ext=mp4]/best[height<=480][ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'concurrent_fragment_downloads': 5,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

def query_gemini_fast(video_file, prompt):
    # Fast polling loop: checks every 0.7s instead of 2s
    while video_file.state.name == "PROCESSING":
        time.sleep(0.7)
        video_file = ai_client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise Exception("Google failed to process video.")

    # High-speed low-latency model first
    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        try:
            res = ai_client.models.generate_content(model=m, contents=[video_file, prompt])
            return res.text
        except Exception:
            time.sleep(1)
    raise Exception("AI is busy right now")

def query_gemini_text_fast(prompt):
    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        try:
            res = ai_client.models.generate_content(model=m, contents=prompt)
            return res.text
        except Exception:
            time.sleep(1)
    raise Exception("AI is busy right now")

# --- 4. ADMIN DASHBOARD COMMAND ---
@bot.message_handler(commands=['admin', 'stats'])
def admin_dashboard(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ You are not authorized to view this.")
        return

    with db_lock:
        cursor.execute('SELECT COUNT(*), SUM(requests_count) FROM users')
        total_users, total_requests = cursor.fetchone()
        total_requests = total_requests or 0

        cursor.execute('SELECT first_name, username, requests_count, last_seen, user_id FROM users ORDER BY requests_count DESC LIMIT 15')
        top_users = cursor.fetchall()

    dashboard = f"👑 *ADMIN OVERVIEW*\n\n"
    dashboard += f"👥 *Total Users:* `{total_users}`\n"
    dashboard += f"🎬 *Total Videos Analyzed:* `{total_requests}`\n\n"
    dashboard += "*Recent / Top Users:*\n"

    for i, u in enumerate(top_users, 1):
        name, uname, count, last_seen, uid = u
        handle = f"@{uname}" if uname else "No Username"
        dashboard += f"{i}. *{name}* ({handle})\n   📊 Videos: `{count}` | 🕒 `{last_seen}`\n   🆔 `{uid}`\n\n"

    bot.reply_to(message, dashboard, parse_mode="Markdown")

# --- 5. REGULAR USER HANDLERS ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    name = message.from_user.first_name or "Friend"
    log_user_activity(message.from_user.id, name, message.from_user.username, is_video=False)
    
    bot.reply_to(
        message, 
        f"Hey {name}! ⚡\n\n"
        "ഏതെങ്കിലും Reel അല്ലെങ്കിൽ Short ലിങ്ക് അയച്ചോ. സ്പീഡിൽ കണ്ടിട്ട് സീൻ എന്താണെന്നും, "
        "ഇത് ലൈഫിൽ എങ്ങനെ യൂസ് ചെയ്യാമെന്നും, റിയാലിറ്റി ചെക്കും തരാം!\n\n"
        "Send a link whenever you're ready! 🚀"
    )

@bot.message_handler(func=lambda msg: True)
def handle_incoming_message(message):
    chat_id = message.chat.id
    name = message.from_user.first_name or "Friend"
    username = message.from_user.username
    url = extract_url(message.text)

    # CASE 1: USER SENT A REEL / SHORT
    if url:
        log_user_activity(message.from_user.id, name, username, is_video=True)
        status = bot.reply_to(message, f"⚡ Analyzing reel for {name}... (just a few seconds!)")

        try:
            vid = download_video_fast(url)
            vfile = ai_client.files.upload(file=vid)

            prompt = f"""
            You are an ultra-sharp, observant, and brutally honest content analyst talking directly to {name}.
            
            YOUR VOICE & TONE:
            - Write in natural, fluid MANGLISH (Malayalam script heavily blended with everyday conversational English).
            - DO NOT use stiff, textbook Malayalam. Use real conversational phrases: "Scene ithaanu", "Actually...", "Main catch", "Pure marketing gimmick", "Oru kaaryam shradhicho".
            - Tone: Analytical, witty, realistic, zero cringe, no forced "bro/machane" repetition.
            - High-IQ: Notice subtle details (hidden text, visual cuts, affiliate selling, or genuine value).

            FORMAT YOUR RESPONSE LIKE THIS:

            🎬 SCENE BREAKDOWN (എന്താണ് യഥാർത്ഥത്തിൽ നടക്കുന്നത്?)
            • 2-3 sharp sentences explaining the real core concept without any filler.

            💡 HOW TO ACTUALLY USE THIS (നമുക്ക് എന്ത് പ്രയോജനം?)
            • How can {name} actually utilize or implement this in daily life? Real-world actionable steps.

            🔍 REALITY CHECK & VERDICT (തള്ളോ അതോ കാര്യമുണ്ടോ?)
            • Unfiltered critique: Is this 100% genuine and practical? Or clickbait? Spot the catch.

            💭 ONE QUICK QUESTION:
            • Ask {name} one sharp, intriguing question related to this video topic.
            """

            reply_text = query_gemini_fast(vfile, prompt)
            
            user_sessions[chat_id] = {
                "name": name,
                "last_context": reply_text
            }

            ai_client.files.delete(name=vfile.name)
            if os.path.exists(vid):
                os.remove(vid)

            bot.edit_message_text(reply_text, chat_id=chat_id, message_id=status.message_id)

        except Exception as e:
            print(f"Error: {e}")
            bot.reply_to(message, f"⚠️ {name}, ആ വീഡിയോ പ്രോസസ്സ് ചെയ്യാൻ പറ്റിയില്ല. ലിങ്ക് പബ്ലിക് ആണെന്ന് ഉറപ്പുവരുത്തി വീണ്ടും അയക്കൂ.")

    # CASE 2: FOLLOW-UP QUESTION
    else:
        log_user_activity(message.from_user.id, name, username, is_video=False)
        
        if chat_id in user_sessions and user_sessions[chat_id].get("last_context"):
            session = user_sessions[chat_id]
            last_context = session["last_context"]
            user_question = message.text

            bot.send_chat_action(chat_id, 'typing')

            followup_prompt = f"""
            You are a sharp, analytical AI companion talking to {name}.
            Context of the video analyzed previously:
            \"\"\"{last_context}\"\"\"

            {name} asked:
            \"{user_question}\"

            Provide an intelligent, direct, and insightful response in natural MANGLISH (Malayalam script blended with conversational English).
            """

            try:
                answer = query_gemini_text_fast(followup_prompt)
                bot.reply_to(message, answer)
            except Exception as e:
                bot.reply_to(message, "ചെറിയൊരു എറർ വന്നു. ഒന്നുകൂടി ചോദിക്കാമോ?")
        else:
            bot.reply_to(
                message, 
                f"ഹലോ {name}! ആദ്യം ഒരു Reel അല്ലെങ്കിൽ Short ലിങ്ക് അയക്കൂ, എന്നിട്ട് അതിനെ പറ്റി നമുക്ക് ഡിസ്കസ് ചെയ്യാം! 🎬"
            )

print("🚀 Supercharged High-Speed Bot Running...")
bot.infinity_polling()
