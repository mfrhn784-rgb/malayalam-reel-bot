import os
import re
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import yt_dlp
from google import genai

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = 8190105957  # Your Admin Telegram ID

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Storage for memory and user analytics
user_sessions = {}
user_db = {}  # {user_id: {"name": str, "username": str, "count": int}}

# Keep-alive server for Render
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

def extract_url(text):
    urls = re.findall(r'(https?://[^\s]+)', text)
    return urls[0] if urls else None

def download_video(url, output_path="short.mp4"):
    if os.path.exists(output_path):
        os.remove(output_path)
    ydl_opts = {
        'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

def query_gemini(video_file, prompt):
    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        for _ in range(2):
            try:
                res = ai_client.models.generate_content(model=m, contents=[video_file, prompt])
                return res.text.strip()
            except Exception:
                time.sleep(2)
    raise Exception("AI busy")

def query_gemini_text(prompt):
    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        for _ in range(2):
            try:
                res = ai_client.models.generate_content(model=m, contents=prompt)
                return res.text.strip()
            except Exception:
                time.sleep(2)
    raise Exception("AI busy")

def track_user(user, is_reel=False):
    """Tracks users and alerts admin on new signups"""
    uid = user.id
    name = user.first_name or "Unknown"
    if user.last_name:
        name += f" {user.last_name}"
    username = user.username or ""

    is_new = uid not in user_db

    if is_new:
        user_db[uid] = {"name": name, "username": username, "count": 0}
        print(f"👤 NEW USER DETECTED: {name} (@{username}) [ID: {uid}]")
        # Send secret alert to your personal Telegram
        try:
            bot.send_message(
                ADMIN_ID, 
                f"🔔 *New User Alert!*\n\n• Name: {name}\n• Username: @{username if username else 'None'}\n• ID: `{uid}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Could not send alert to admin: {e}")

    if is_reel:
        user_db[uid]["count"] += 1
        print(f"🎬 Reel analyzed for {name} (Total: {user_db[uid]['count']})")

# ================= ADMIN / STATS COMMAND =================
@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return  # Ignore unauthorized users

    total_users = len(user_db)
    total_reels = sum(u["count"] for u in user_db.values())

    report = "📊 *SCROLLPARTNER OVERVIEW*\n\n"
    report += f"👥 *Total Users:* {total_users}\n"
    report += f"🎬 *Total Reels Analyzed:* {total_reels}\n\n"
    report += "━━━━━━━━━━━━━━━\n"
    report += "*Recent Users:*\n"

    if not user_db:
        report += "_No users tracked yet._"
    else:
        for uid, data in list(user_db.items())[-15:]:
            uname = f"@{data['username']}" if data['username'] else "No username"
            report += f"• *{data['name']}* ({uname})\n  └ Reels: {data['count']} | ID: `{uid}`\n"

    bot.reply_to(message, report, parse_mode="Markdown")

# ================= USER COMMANDS =================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    track_user(message.from_user, is_reel=False)
    bot.reply_to(message, "Send a Reel or Short link.")

@bot.message_handler(func=lambda msg: True)
def handle_incoming_message(message):
    chat_id = message.chat.id
    url = extract_url(message.text)

    # CASE 1: REEL / SHORT LINK
    if url:
        track_user(message.from_user, is_reel=True)
        status = bot.reply_to(message, "...")

        try:
            vid = download_video(url)
            vfile = ai_client.files.upload(file=vid)

            while vfile.state.name == "PROCESSING":
                time.sleep(2)
                vfile = ai_client.files.get(name=vfile.name)

            prompt = """
            You are ScrollPartner.
            Watch and listen to this short-form video carefully.
            Generate ONE ready-to-send, sharp, witty reaction/reply grounded strictly in what actually happens in the video.

            RULES:
            1. Length: Exactly 1 to 3 sentences. No more.
            2. Language: Natural conversational Malayalam-English mix (Manglish). Use Malayalam script naturally blended with everyday English words as real people speak.
            3. Tone: Real Malayali wit, observant, clever, and grounded. Sound like an actual person texting a comeback or insight, NOT an AI summary.
            4. ABSOLUTELY AVOID:
               - Cringe slang or filler ("bro", "machane", "mass", "pwoli").
               - Any headings, bullet points, intros, or sign-offs.
               - Excessive emojis (0 to 1 maximum).
               - Assuming gender or personal relationships.
               - Generic motivational advice or obvious summaries.
            5. Deliver ONLY the final text.
            """

            reply_text = query_gemini(vfile, prompt)

            user_sessions[chat_id] = {
                "last_context": reply_text
            }

            ai_client.files.delete(name=vfile.name)
            if os.path.exists(vid):
                os.remove(vid)

            bot.edit_message_text(reply_text, chat_id=chat_id, message_id=status.message_id)

        except Exception as e:
            print(f"Error: {e}")
            bot.reply_to(message, "Link open aavanilla, vere try cheyy.")

    # CASE 2: FOLLOW-UP QUESTION
    else:
        track_user(message.from_user, is_reel=False)
        if chat_id in user_sessions and user_sessions[chat_id].get("last_context"):
            last_context = user_sessions[chat_id]["last_context"]
            user_question = message.text

            bot.send_chat_action(chat_id, 'typing')

            followup_prompt = f"""
            You are ScrollPartner.
            Previous context of the reel: \"\"\"{last_context}\"\"\"
            User just sent: \"\"\"{user_question}\"\"\"

            Respond in 1-2 sharp, natural sentences in conversational Manglish. 
            Zero robotic fluff, zero cringe slang, strictly context-driven. Deliver ONLY the reply.
            """

            try:
                answer = query_gemini_text(followup_prompt)
                bot.reply_to(message, answer)
            except Exception:
                bot.reply_to(message, "Onnude parayamo, manasilayilla.")
        else:
            bot.reply_to(message, "Aadya oru reel link ayakk.")

print("🚀 ScrollPartner with Admin Analytics Running...")
bot.infinity_polling()
