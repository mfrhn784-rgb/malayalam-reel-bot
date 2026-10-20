import os
import re
import time
import threading
from flask import Flask, request, Response
import telebot
import yt_dlp
from google import genai
from twilio.rest import Client

# API Keys from Render Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# Initialize Bots
tele_bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

app = Flask(__name__)

MALAYALAM_PROMPT = """
Analyze this video and reply in NATURAL CASUAL MALAYALAM (മലയാളം):
📌 സംഗ്രഹം & ഫാക്ട് ചെക്ക്:
• 2-3 പ്രധാന കാര്യങ്ങൾ.
• ചേരുവകൾ/സ്റ്റെപ്പുകൾ ഉണ്ടെങ്കിൽ അത് പറയുക, ഒപ്പം ഇത് ശരിയാണോ എന്ന് വ്യക്തമാക്കുക.

🔥 വൈറൽ കമന്റുകൾ (Top 3):
1. [ട്രോൾ]: കിടിലൻ വൺ-ലൈനർ ട്രോൾ കമന്റ്.
2. [റിലേറ്റബിൾ]: സാധാരണക്കാർക്ക് തോന്നുന്ന കമന്റ്.
3. [ചോദ്യം]: ലൈക്കും റിപ്ലൈയും കിട്ടുന്ന ചോദ്യം.
"""

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

def analyze_video(video_file, prompt):
    while video_file.state.name == "PROCESSING":
        time.sleep(2)
        video_file = ai_client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise Exception("Google failed to process video.")

    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        for _ in range(2):
            try:
                res = ai_client.models.generate_content(model=m, contents=[video_file, prompt])
                return res.text
            except Exception:
                time.sleep(2)
    raise Exception("AI is busy right now")

def process_video_and_get_reply(url):
    vid = download_video(url)
    vfile = ai_client.files.upload(file=vid)
    reply_text = analyze_video(vfile, MALAYALAM_PROMPT)
    ai_client.files.delete(name=vfile.name)
    if os.path.exists(vid):
        os.remove(vid)
    return reply_text

# ================= TELEGRAM HANDLERS =================
@tele_bot.message_handler(commands=['start'])
def tele_start(message):
    tele_bot.reply_to(message, "നമസ്കാരം! 👋 ഏതെങ്കിലും Instagram Reel അല്ലെങ്കിൽ YouTube Short ലിങ്ക് അയക്കൂ, ഞാൻ മലയാളത്തിൽ വിശദീകരിക്കാം!")

@tele_bot.message_handler(func=lambda msg: True)
def tele_on_message(message):
    url = extract_url(message.text)
    if not url:
        tele_bot.reply_to(message, "ദയവായി ഒരു Reel അല്ലെങ്കിൽ Short ലിങ്ക് അയക്കൂ! 🔗")
        return

    status = tele_bot.reply_to(message, "⏳ വീഡിയോ ഡൗൺലോഡ് ചെയ്തു വിശകലനം ചെയ്യുന്നു... (കാത്തിരിക്കൂ)")
    try:
        reply_text = process_video_and_get_reply(url)
        tele_bot.edit_message_text(reply_text, chat_id=message.chat.id, message_id=status.message_id)
    except Exception as e:
        print(f"Telegram Error: {e}")
        tele_bot.reply_to(message, f"⚠️ Error: {e}")

# ================= WHATSAPP HANDLERS =================
def process_whatsapp_async(from_number, to_number, url):
    """Processes video in background and sends WhatsApp message back"""
    try:
        reply_text = process_video_and_get_reply(url)
        twilio_client.messages.create(body=reply_text, from_=to_number, to=from_number)
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        twilio_client.messages.create(
            body=f"⚠️ ക്ഷമിക്കണം, വീഡിയോ പ്രോസസ്സ് ചെയ്യാൻ സാധിച്ചില്ല: {e}",
            from_=to_number,
            to=from_number
        )

@app.route("/", methods=["GET"])
def home():
    return "Bot is alive and running 24/7 for Telegram & WhatsApp!"

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    body = request.form.get("Body", "")
    from_number = request.form.get("From")
    to_number = request.form.get("To")

    url = extract_url(body)
    if not url:
        twilio_client.messages.create(
            body="നമസ്കാരം! 👋 ദയവായി ഒരു Instagram Reel അല്ലെങ്കിൽ YouTube Short ലിങ്ക് അയക്കൂ!",
            from_=to_number,
            to=from_number
        )
        return Response("OK", status=200)

    # Send quick acknowledgment
    twilio_client.messages.create(
        body="⏳ വീഡിയോ ഡൗൺലോഡ് ചെയ്തു വിശകലനം ചെയ്യുന്നു... (കുറച്ചു സെക്കൻഡ് കാത്തിരിക്കൂ)",
        from_=to_number,
        to=from_number
    )

    # Process in background thread so Twilio doesn't time out
    threading.Thread(target=process_whatsapp_async, args=(from_number, to_number, url), daemon=True).start()

    return Response("OK", status=200)

# Run Telegram Polling in Background Thread
def run_tele_bot():
    print("🚀 Telegram bot listening...")
    tele_bot.infinity_polling()

threading.Thread(target=run_tele_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
