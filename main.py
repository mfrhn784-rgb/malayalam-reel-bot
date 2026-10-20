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
    name = message.from_user.first_name or "Friend"
    bot.reply_to(
        message, 
        f"Hey {name}! ⚡\n\n"
        "ഏതെങ്കിലും Reel അല്ലെങ്കിൽ Short ലിങ്ക് ഇങ്ങോട്ട് അയച്ചോ. വെറുതെ കണ്ടത് അതുപോലെ പറയുന്ന ബോട്ട് അല്ല ഇത്.\n\n"
        "• ആ വീഡിയോയുടെ യഥാർത്ഥ സീൻ എന്താണെന്ന് ഡീറ്റെയിൽഡ് ആയി പറയും.\n"
        "• ഇത് നമ്മുടെ ലൈഫിൽ എങ്ങനെ പ്രാക്ടിക്കൽ ആയി ഉപയോഗിക്കാം എന്ന് പറഞ്ഞുതരും.\n"
        "• ക്ലിക്ക്ബെയ്റ്റോ തള്ളോ ഉണ്ടെങ്കിൽ അത് കയ്യോടെ പിടിക്കും (Reality Check).\n\n"
        "Send a link whenever you're ready!"
    )

@bot.message_handler(func=lambda msg: True)
def handle_incoming_message(message):
    chat_id = message.chat.id
    name = message.from_user.first_name or "Friend"
    url = extract_url(message.text)

    # CASE 1: USER SENT A REEL / SHORT
    if url:
        status = bot.reply_to(message, f"Got it {name}. വീഡിയോയും അതിലെ ഡീറ്റെയിൽസും ഒന്നു അനലൈസ് ചെയ്യട്ടെ... 🔍")

        try:
            vid = download_video(url)
            vfile = ai_client.files.upload(file=vid)

            while vfile.state.name == "PROCESSING":
                time.sleep(2)
                vfile = ai_client.files.get(name=vfile.name)

            prompt = f"""
            You are an ultra-sharp, observant, and brutally honest content analyst talking directly to {name}.
            
            YOUR VOICE & TONE:
            - Write in natural, fluid MANGLISH (Malayalam script heavily blended with everyday conversational English).
            - DO NOT use stiff, textbook Malayalam (avoid formal words like "ഉപയോഗപ്രദമായത്", "സ്ഥിരീകരണം", "സംഗ്രഹം").
            - Use real conversational phrases that smart Malayalis use: "Scene ithaanu", "Actually...", "Main catch", "Practical aano ennu chodichaal", "Pure marketing gimmick", "Oru kaaryam shradhicho".
            - Tone: Analytical, witty, realistic, zero cringe, no forced "bro/machane" repetition.
            - High-IQ: Notice subtle details (hidden text, visual cuts, whether the creator is staging it, affiliate selling, or genuine value).

            FORMAT YOUR RESPONSE LIKE THIS:

            🎬 SCENE BREAKDOWN (എന്താണ് യഥാർത്ഥത്തിൽ നടക്കുന്നത്?)
            • 2-3 sharp sentences explaining the real core concept without any filler. What is the creator trying to do or show?

            💡 HOW TO ACTUALLY USE THIS (നമുക്ക് എന്ത് പ്രയോജനം?)
            • Skip the obvious fluff. How can {name} actually utilize or implement this in daily life (tools, shortcuts, techniques)? If it's a recipe/workout/hack, give the actual actionable takeaway or a better alternative.

            🔍 REALITY CHECK & VERDICT (തള്ളോ അതോ കാര്യമുണ്ടോ?)
            • Unfiltered critique: Is this 100% genuine, safe, and practical? Or is it exaggerated for views/engagement? Spot the catch or missing context.

            💭 ONE QUICK QUESTION FOR YOU:
            • Ask {name} one sharp, intriguing question related to this video topic to spark a debate or follow-up discussion.
            """

            reply_text = query_gemini(vfile, prompt)
            
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

    # CASE 2: FOLLOW-UP QUESTIONS
    else:
        if chat_id in user_sessions and user_sessions[chat_id].get("last_context"):
            session = user_sessions[chat_id]
            last_context = session["last_context"]
            user_question = message.text

            bot.send_chat_action(chat_id, 'typing')

            followup_prompt = f"""
            You are a sharp, analytical AI conversing with {name}.
            Context of the video you analyzed previously:
            \"\"\"{last_context}\"\"\"

            {name} asked:
            \"{user_question}\"

            Provide an intelligent, direct, and insightful response in natural MANGLISH (Malayalam script blended with conversational English). 
            Do not give vague, generic answers. Be specific, realistic, and helpful.
            """

            try:
                answer = query_gemini_text(followup_prompt)
                bot.reply_to(message, answer)
            except Exception as e:
                bot.reply_to(message, "ചെറിയൊരു എറർ വന്നു. ഒന്നുകൂടി ചോദിക്കാമോ?")
        else:
            bot.reply_to(
                message, 
                f"ഹലോ {name}! ആദ്യം ഒരു Reel അല്ലെങ്കിൽ Short ലിങ്ക് അയക്കൂ, എന്നിട്ട് അതിനെ പറ്റി നമുക്ക് ഡിസ്കസ് ചെയ്യാം! 🎬"
            )

print("🚀 High-IQ Manglish Bot Running...")
bot.infinity_polling()
