import os
import json
import time
import hmac
import hashlib
import requests
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BITVAVO_API_KEY = os.getenv("SCALPER_API_KEY")
BITVAVO_API_SECRET = os.getenv("SCALPER_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

BUY_AMOUNT_EUR = 10  # قيمة الشراء باليورو

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("فشل إرسال الرسالة:", e)

def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, f"/v2{path}", body)
    headers = {
        'Bitvavo-Access-Key': BITVAVO_API_KEY,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Window': '10000'
    }
    try:
        response = requests.request(method, f"https://api.bitvavo.com/v2{path}", headers=headers, json=body or {})
        return response.json()
    except Exception as e:
        return {"error": str(e)}

@app.route('/', methods=['POST'])
def webhook():
    data = request.json
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if not chat_id or not text:
        return "no message"

    text = text.lower()

    if "الرصيد" in text:
        balance = bitvavo_request("GET", "/balance")
        try:
            eur = next((b['available'] for b in balance if b['symbol'] == 'EUR'), '0')
            send_message(f"💰 الرصيد المتاح: {eur} EUR")
        except:
            send_message("❌ فشل جلب الرصيد.")
        return "ok"

    if "اشتري" in text and "يا نمس" in text:
        try:
            parts = text.split()
            coin = parts[1].upper()
            symbol = f"{coin}-EUR"

            order_body = {
                "amountQuote": str(BUY_AMOUNT_EUR),
                "market": symbol,
                "side": "buy",
                "orderType": "market",
                "operatorId": ""
            }
            result = bitvavo_request("POST", "/order", order_body)

            if "orderId" in result:
                send_message(f"✅ تم شراء {coin} بقيمة {BUY_AMOUNT_EUR} يورو! 🚀")
            else:
                send_message(f"❌ فشل الشراء: {result.get('error', 'غير معروف')}")
        except Exception as e:
            send_message(f"❌ فشل التنفيذ: {str(e)}")
        return "ok"

    send_message("👋 أمر غير معروف!")
    return "ok"

@app.route("/")
def home():
    return "Nems Scalper ✅", 200

if __name__ == '__main__':
    send_message("🚀 سكربت النمس بدأ العمل!")
    app.run(host='0.0.0.0', port=8080)