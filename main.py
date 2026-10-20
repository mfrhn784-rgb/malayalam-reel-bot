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

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

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

def analyze_video(video_file, prompt):
    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        for _ in range(2):
            try:
                res = ai_client.models.generate_content(model=m, contents=[video_file, prompt])
                return res.text
            except Exception:
                time.sleep(2)
    raise Exception("AI is busy right now")

@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "നമസ്കാരം! 👋 ഏതെങ്കിലും Instagram Reel അല്ലെങ്കിൽ YouTube Short ലിങ്ക് അയക്കൂ, ഞാൻ മലയാളത്തിൽ വിശദീകരിക്കാം!")

@bot.message_handler(func=lambda msg: True)
def on_message(message):
    url = extract_url(message.text)
    if not url:
        bot.reply_to(message, "ദയവായി ഒരു Reel അല്ലെങ്കിൽ Short ലിങ്ക് അയക്കൂ! 🔗")
        return

    status = bot.reply_to(message, "⏳ വീഡിയോ വിശകലനം ചെയ്യുന്നു... (കാത്തിരിക്കൂ)")

    try:
        vid = download_video(url)
        vfile = ai_client.files.upload(file=vid)

        prompt = """
        Analyze this video and reply in NATURAL CASUAL MALAYALAM (മലയാളം):
        📌 സംഗ്രഹം & ഫാക്ട് ചെക്ക്:
        • 2-3 പ്രധാന കാര്യങ്ങൾ.
        • ചേരുവകൾ/സ്റ്റെപ്പുകൾ ഉണ്ടെങ്കിൽ അത് പറയുക, ഒപ്പം ഇത് ശരിയാണോ എന്ന് വ്യക്തമാക്കുക.

        🔥 വൈറൽ കമന്റുകൾ (Top 3):
        1. [ട്രോൾ]: കിടിലൻ വൺ-ലൈനർ ട്രോൾ കമന്റ്.
        2. [റിലേറ്റബിൾ]: സാധാരണക്കാർക്ക് തോന്നുന്ന കമന്റ്.
        3. [ചോദ്യം]: ലൈക്കും റിപ്ലൈയും കിട്ടുന്ന ചോദ്യം.
        """

        reply_text = analyze_video(vfile, prompt)
        ai_client.files.delete(name=vfile.name)
        if os.path.exists(vid):
            os.remove(vid)

        bot.edit_message_text(reply_text, chat_id=message.chat.id, message_id=status.message_id)
    except Exception as e:
        print(f"Error: {e}")
        bot.reply_to(message, "⚠️ വീഡിയോ പ്രോസസ്സ് ചെയ്യാൻ സാധിച്ചില്ല. ദയവായി വീണ്ടും ശ്രമിക്കുക.")

print("🚀 Bot running...")
bot.infinity_polling()
