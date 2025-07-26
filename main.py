import os
import time
import hmac
import json
import hashlib
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

# إرسال رسالة تيليغرام
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("فشل إرسال الرسالة:", e)

# توقيع الطلبات لبيتفافو
def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

# تنفيذ طلب لبيتفافو
def bitvavo_request(method, path, body=None):
    url = "https://api.bitvavo.com/v2" + path
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, path, body)
    headers = {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }
    resp = requests.request(method, url, headers=headers, json=body)
    return resp.json()

# شراء عملة
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
        print("BUY RESPONSE:", result)
        if "orderId" in result:
            send_message(f"🚀 تم شراء {symbol.upper()} بقيمة {BUY_AMOUNT_EUR} يورو!")
        else:
            send_message(f"❌ فشل الشراء: {result}")
    except Exception as e:
        send_message(f"❌ فشل الشراء: {str(e)}")

# بيع كامل الرصيد
def sell(symbol):
    try:
        balance = bitvavo_request("GET", "/balance")
        if isinstance(balance, list):
            amount = None
            for item in balance:
                if item.get("symbol") == symbol:
                    amount = item.get("available")
                    break
            if not amount or float(amount) == 0:
                send_message(f"❌ لا يوجد رصيد كافٍ من {symbol} للبيع")
                return
        else:
            send_message(f"❌ فشل جلب الرصيد: {balance}")
            return

        order = {
            "market": f"{symbol}-EUR",
            "side": "sell",
            "orderType": "market",
            "amount": amount
        }
        result = bitvavo_request("POST", "/order", order)
        print("SELL RESPONSE:", result)
        if "orderId" in result:
            send_message(f"📤 تم بيع كل رصيد {symbol.upper()}!")
        else:
            send_message(f"❌ فشل البيع: {result}")
    except Exception as e:
        send_message(f"❌ فشل البيع: {str(e)}")

# استقبال أوامر تيليغرام
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
        buy(symbol)
    elif "بيع" in text:
        symbol = text.replace("بيع", "").replace("يا نمس", "").strip().upper()
        sell(symbol)
    else:
        send_message("👋 أمر غير معروف!")

    return jsonify({"ok": True})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)