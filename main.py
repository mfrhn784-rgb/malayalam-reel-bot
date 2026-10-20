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

# Store memory of the last video per user for follow-up questions
# Format: { chat_id: {"summary": "...", "name": "..."} }
user_sessions = {}

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
                return res.text
            except Exception:
                time.sleep(2)
    raise Exception("AI is busy right now")

def query_gemini_text(prompt):
    models = ['gemini-3.5-flash-lite', 'gemini-3.8-flash']
    for m in models:
        for _ in range(2):
            try:
                res = ai_client.models.generate_content(model=m, contents=prompt)
                return res.text
            except Exception:
                time.sleep(2)
    raise Exception("AI is busy right now")

@bot.message_handler(commands=['start'])
def start_cmd(message):
    name = message.from_user.first_name or "Machane"
    bot.reply_to(
        message, 
        f"Hey {name} bro! 🔥\n\nഏതെങ്കിലും Instagram Reel അല്ലെങ്കിൽ YouTube Short ലിങ്ക് ഇങ്ങോട്ട് അയച്ചോ. "
        "ഞാൻ കണ്ടിട്ട് സംഭവം എന്താണെന്നും, ഇത് നമുക്ക് എങ്ങനെ യൂസ് ചെയ്യാമെന്നും, ഇത് ഉള്ളതാണോ അതോ വെറും തള്ളാണോ (Fact-Check) എന്നും പറഞ്ഞു തരാം!\n\n"
        "വീഡിയോ കഴിഞ്ഞിട്ട് അതിനെ പറ്റി എന്തെങ്കിലും സംശയം ചോദിച്ചാലും ഞാൻ ക്ലിയർ ചെയ്തു തരാം! 🚀"
    )

@bot.message_handler(func=lambda msg: True)
def handle_incoming_message(message):
    chat_id = message.chat.id
    name = message.from_user.first_name or "Machane"
    url = extract_url(message.text)

    # CASE 1: USER SENT A NEW REEL / SHORT
    if url:
        status = bot.reply_to(message, f"Wait {name} bro... ഞാൻ വീഡിയോ മൊത്തത്തിൽ ഒന്ന് കണ്ടു നോക്കട്ടെ! 👀🍿")

        try:
            vid = download_video(url)
            vfile = ai_client.files.upload(file=vid)

            # Wait for processing
            while vfile.state.name == "PROCESSING":
                time.sleep(2)
                vfile = ai_client.files.get(name=vfile.name)

            prompt = f"""
            You are a super smart, witty, and fun AI buddy who speaks in vibrant MANGLISH (a natural blend of Malayalam and English, common among Kerala youth).
            User's name is: {name}.

            Analyze this video and provide an engaging, structured reply formatted as follows:

            👋 Hey {name} bro! ദാ സംഭവം ഞാൻ കണ്ടു:

            📌 WHAT'S THE SCENE? (Quick Breakdown)
            • Short, catchy summary of what happens in the video (2-3 punchy bullet points).

            💡 HOW TO UTILIZE THIS? (നമുക്ക് എങ്ങനെ യൂസ് ചെയ്യാം?)
            • Explain practical takeaways. If it's a tech tip/life hack/recipe/workout: give clear, actionable instructions on how {name} can actually use or apply this in daily life.

            🕵️‍♂️ FACT-CHECK & VERDICT (സത്യമോ അതോ വെറും തള്ളോ?)
            • Is this claim 100% real, safe, and practical? Or is it clickbait/exaggeration? Give your honest, unfiltered verdict.

            💬 NEXT MOVE:
            • Add a friendly closing line: tell {name} that if they have any doubts about this video (like ingredients, alternatives, price, or steps), just ask right now!
            """

            reply_text = query_gemini(vfile, prompt)
            
            # Save context for follow-up questions
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
            bot.reply_to(message, f"⚠️ {name} bro, ആ വീഡിയോ ലോഡ് ചെയ്യാൻ പറ്റിയില്ല. ലിങ്ക് പബ്ലിക് ആണോ എന്ന് നോക്കിയിട്ട് ഒന്നുകൂടി അയച്ചു നോക്ക്!")

    # CASE 2: USER IS ASKING A FOLLOW-UP QUESTION ABOUT THE LAST VIDEO
    else:
        if chat_id in user_sessions and user_sessions[chat_id].get("last_context"):
            session = user_sessions[chat_id]
            last_context = session["last_context"]
            user_question = message.text

            bot.send_chat_action(chat_id, 'typing')

            followup_prompt = f"""
            You are a friendly, witty AI companion talking to {name}.
            Here is the context of the video you both just analyzed:
            \"\"\"{last_context}\"\"\"

            {name} just asked this follow-up question:
            \"{user_question}\"

            Answer {name}'s question directly based on the video context. 
            Keep it natural, witty, and in MANGLISH (Malayalam + English mixed). Address them warmly by name ({name} bro / machane).
            """

            try:
                answer = query_gemini_text(followup_prompt)
                bot.reply_to(message, answer)
            except Exception as e:
                bot.reply_to(message, f"Oops {name} bro, ചെറിയൊരു എറർ വന്നു. ഒന്നുകൂടി ചോദിക്കാമോ?")
        else:
            bot.reply_to(
                message, 
                f"ഹലോ {name} bro! ആദ്യം ഏതെങ്കിലും ഒരു Reel അല്ലെങ്കിൽ Short ലിങ്ക് ഇങ്ങോട്ട് അയക്കൂ. "
                "എന്നിട്ട് അതിനെ പറ്റി എന്ത് വേണമെങ്കിലും ചോദിച്ചോ! 😉🎥"
            )

print("🚀 Smart Manglish Bot Running...")
bot.infinity_polling()
