import os
import json
import hmac
import hashlib
import time
import requests
import redis
from flask import Flask, request, jsonify

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BITVAVO_API_KEY")
API_SECRET = os.getenv("BITVAVO_API_SECRET")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Telegram Error:", e)

def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ''
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, path, body)
    headers = {
        'Bitvavo-Access-Key': API_KEY,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }
    url = f"https://api.bitvavo.com/v2{path}"
    response = requests.request(method, url, headers=headers, json=body)
    return response.json()

def buy(symbol):
    try:
        order = {
            "market": f"{symbol}-EUR",
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT_EUR),
            "amountQuote": True
        }
        result = bitvavo_request("POST", "/order", order)
        send_message(f"🚀 تم شراء {symbol} بقيمة {BUY_AMOUNT_EUR} يورو!")
        return result
    except Exception as e:
        send_message(f"❌ فشل الشراء: {str(e)}")

def sell(symbol):
    try:
        balance = bitvavo_request("GET", "/balance")
        amount = None
        for item in balance:
            if item['symbol'] == symbol:
                amount = item['available']
                break
        if not amount or float(amount) == 0:
            send_message(f"❌ لا يوجد رصيد كافٍ من {symbol} للبيع")
            return
        order = {
            "market": f"{symbol}-EUR",
            "side": "sell",
            "orderType": "market",
            "amount": amount
        }
        result = bitvavo_request("POST", "/order", order)
        send_message(f"📤 تم بيع كل رصيد {symbol}!")
        return result
    except Exception as e:
        send_message(f"❌ فشل البيع: {str(e)}")

@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    message = data.get("message", {})
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")

    if not chat_id or not text:
        return "no message"

    if "اشتري" in text:
        symbol = text.replace("اشتري", "").replace("يا نمس", "").strip().upper()
        buy(symbol)
    elif "بيع" in text:
        symbol = text.replace("بيع", "").replace("يا نمس", "").strip().upper()
        sell(symbol)
    else:
        send_message("👋 أمر غير معروف!")

    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)