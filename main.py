import os
import re
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import yt_dlp
from google import genai

# These will safely read the keys from Render's private settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 1. Health server so Render knows our bot is alive
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running 24/7!")

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

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

def generate_ai_analysis(video_file, prompt):
    models_to_try = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    last_err = None

    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=[video_file, prompt]
                )
                return response.text
            except Exception as e:
                last_err = e
                print("Model busy, retrying in 2 seconds...")
                time.sleep(2)

    raise last_err

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "WELCOME! 👋 ഏതെങ്കിലും Instagram Reel അല്ലെങ്കിൽ YouTube Short ലിങ്ക് അയക്കൂ!let me checkk")

@bot.message_handler(func=lambda msg: True)
def handle_video_link(message):
    url = extract_url(message.text)
    if not url:
        bot.reply_to(message, "ദയവായി ഒരു സാധുവായ Instagram Reel അല്ലെങ്കിൽ YouTube Short ലിങ്ക് അയക്കൂ! 🔗")
        return

    status_msg = bot.reply_to(checking (waitt10-15 സെക്കൻഡ്!)")

    try:
        # Download
        video_path = download_video(url)

        # Upload to Gemini
        video_file = ai_client.files.upload(file=video_path)

        prompt = """
        You are an expert social media assistant fluent in Malayalam.
        Watch and listen to this short-form video carefully.
        Respond COMPLETELY IN NATURAL, CASUAL MALAYALAM (മലയാളം) in this exact format:

        📌 സംഗ്രഹം & ഫാക്ട് ചെക്ക് (Summary & Fact-Check)
        • വീഡിയോയിലെ പ്രധാന കാര്യങ്ങൾ 2-3 പോയിന്റുകളിൽ ചുരുക്കി പറയുക.
        • ഇത് പാചകം/ടിപ്പ്/വർക്കൗട്ട്/ലൈഫ് ഹാക്ക് ആണെങ്കിൽ: പ്രധാന സ്റ്റെപ്പുകൾ/ചേരുവകൾ പറയുക, ഒപ്പം ഇത് സത്യമാണോ/സുരക്ഷിതമാണോ എന്ന് പരിശോധിച്ചു വ്യക്തമാക്കുക.

        🔥 വൈറൽ കമന്റുകൾ (Top 3 Viral Comments)
        1. [തമാശ / ട്രോൾ]: ആളുകളെ ചിരിപ്പിക്കുന്ന ഒരു കിടിലൻ മലയാളം/മംഗ്ലീഷ് വൺ-ലൈനർ ട്രോൾ കമന്റ്.
        2. [റിലേറ്റബിൾ]: വീഡിയോ കണ്ട സാധാരണക്കാർക്ക് തോന്നുന്ന തരത്തിലുള്ള ഒരു റിലേറ്റബിൾ കമന്റ്.
        3. [ചർച്ച / ചോദ്യം]: കൂടുതൽ കമന്റുകളും ലൈക്കുകളും നേടാൻ സഹായിക്കുന്ന തരത്തിലുള്ള ഒരു ചോദ്യം.
        """

        result_text = generate_ai_analysis(video_file, prompt)

        # Clean up
        ai_client.files.delete(name=video_file.name)
        if os.path.exists(video_path):
            os.remove(video_path)

        # Reply
        bot.edit_message_text(result_text, chat_id=message.chat.id, message_id=status_msg.message_id)