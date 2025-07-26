import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # ممكن تخليه اختياري

# لإرسال رسالة تيليغرام
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("فشل إرسال الرسالة:", e)

# استلام الأوامر من تيليغرام
@app.route('/', methods=['POST'])
def webhook():
    data = request.json
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if not chat_id or not text:
        return "no message"

    if "اشتري" in text:
        symbol = text.replace("اشتري", "").replace("يا نمس", "").strip().upper()
        send_message(f"🚀 جاري شراء {symbol}!")
    elif "بيع" in text:
        symbol = text.replace("بيع", "").replace("يا نمس", "").strip().upper()
        send_message(f"📤 جاري بيع {symbol}!")
    else:
        send_message("👋 أمر غير معروف!")

    return jsonify({"ok": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)