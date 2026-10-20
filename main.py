import os
import re
import time
import threading
import requests
from flask import Flask, request, Response
import telebot
import yt_dlp
from google import genai

# API Keys from Render Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GREEN_API_ID = os.getenv("GREEN_API_ID", "710722774773")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")
GREEN_API_URL = "https://7107.api.greenapi.com"

# Initialize Bots
tele_bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
ai_client = genai.Client(api_key=GEMINI_API_KEY)

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

# ================= WHATSAPP (GREEN API) HELPERS =================
def send_whatsapp_message(chat_id, message_text):
    if not GREEN_API_TOKEN:
        return
    url = f"{GREEN_API_URL}/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"
    payload = {"chatId": chat_id, "message": message_text}
    headers = {"Content-Type": "application/json"}
    requests.post(url, json=payload, headers=headers)

def process_whatsapp_async(chat_id, url):
    try:
        reply = process_video_and_get_reply(url)
        send_whatsapp_message(chat_id, reply)
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        send_whatsapp_message(chat_id, f"⚠️ വീഡിയോ പ്രോസസ്സ് ചെയ്യാൻ സാധിച്ചില്ല: {e}")

# Automatically connects Green API to Render on startup!
def auto_setup_green_api():
    if GREEN_API_TOKEN:
        try:
            url = f"{GREEN_API_URL}/waInstance{GREEN_API_ID}/setSettings/{GREEN_API_TOKEN}"
            payload = {
                "webhookUrl": "https://malayalam-reel-bot.onrender.com/whatsapp",
                "incomingWebhook": "yes"
            }
            requests.post(url, json=payload, timeout=10)
            print("✅ Green API auto-configured!")
        except Exception as e:
            print(f"Green API config warning: {e}")

threading.Thread(target=auto_setup_green_api, daemon=True).start()

# ================= TELEGRAM HANDLERS =================
if tele_bot:
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
            tele_bot.reply_to(message, f"⚠️ Error: {e}")

    def run_tele_bot():
        print("🚀 Telegram bot listening...")
        tele_bot.infinity_polling()

    threading.Thread(target=run_tele_bot, daemon=True).start()

# ================= WEBHOOK ROUTES =================
@app.route("/", methods=["GET"])
def home():
    return "Bot is alive and running 24/7 for Telegram & WhatsApp!"

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    data = request.get_json(silent=True) or {}
    type_webhook = data.get("typeWebhook")

    if type_webhook == "incomingMessageReceived":
        sender_data = data.get("senderData", {})
        chat_id = sender_data.get("chatId")
        msg_data = data.get("messageData", {})

        # Extract text message
        text = (
            msg_data.get("textMessageData", {}).get("textMessage")
            or msg_data.get("extendedTextMessageData", {}).get("text")
            or ""
        )

        url = extract_url(text)
        if url:
            send_whatsapp_message(chat_id, "⏳ വീഡിയോ ഡൗൺലോഡ് ചെയ്തു വിശകലനം ചെയ്യുന്നു... (കുറച്ചു സെക്കൻഡ് കാത്തിരിക്കൂ)")
            threading.Thread(target=process_whatsapp_async, args=(chat_id, url), daemon=True).start()

    return Response("OK", status=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
