import os
import json
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# إعدادات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("SCALPER_API_KEY")
API_SECRET = os.getenv("SCALPER_API_SECRET")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", "10"))
BITVAVO_API_URL = "https://api.bitvavo.com/v2"

# إرسال رسالة تيليغرام
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("فشل إرسال الرسالة:", e)

# إنشاء توقيع للتوثيق مع Bitvavo
def create_signature(timestamp, method, path, body):
    msg = f"{timestamp}{method}{path}{body}"
    return hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

# تنفيذ أمر شراء
def place_order(symbol, amount_eur):
    path = f"/order"
    url = BITVAVO_API_URL + path
    timestamp = str(int(time.time() * 1000))

    body = {
        "market": f"{symbol}-EUR",
        "side": "buy",
        "orderType": "market",
        "amountQuote": str(amount_eur)
    }

    body_str = json.dumps(body, separators=(',', ':'))
    signature = create_signature(timestamp, "POST", path, body_str)

    headers = {
        "Bitvavo-Access-Key": API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, data=body_str)
    return response.json()

# جلب الرصيد
def get_balances():
    path = "/balance"
    url = BITVAVO_API_URL + path
    timestamp = str(int(time.time() * 1000))
    body = ""

    signature = create_signature(timestamp, "GET", path, body)

    headers = {
        "Bitvavo-Access-Key": API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000"
    }

    response = requests.get(url, headers=headers)
    result = response.json()
    return [{"symbol": b["symbol"], "available": b["available"], "inOrder": b["inOrder"]} for b in result]

# نقطة استقبال الأوامر من تيليغرام
@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    message = data.get("message", {})
    text = message.get("text", "").lower()
    chat_id = message.get("chat", {}).get("id")

    if not chat_id or not text:
        return "no message"

    if "اشتري" in text:
        symbol = text.replace("اشتري", "").replace("يا نمس", "").strip().upper()
        try:
            result = place_order(symbol, BUY_AMOUNT_EUR)
            if "orderId" in result:
                send_message(f"🚀 تم شراء {symbol} بقيمة {BUY_AMOUNT_EUR} يورو!")
            else:
                send_message(f"❌ فشل الشراء:\n{result}")
        except Exception as e:
            send_message(f"❌ فشل التنفيذ:\n{e}")

    elif "بيع" in text:
        send_message("🚫 البيع لم يتم تفعيله بعد.")

    elif "الرصيد" in text:
        try:
            balances = get_balances()
            message_lines = ["💰 رصيدك الحالي:"]
            for asset in balances:
                available = float(asset["available"])
                in_order = float(asset["inOrder"])
                if available > 0 or in_order > 0:
                    total = round(available + in_order, 4)
                    message_lines.append(f"- {asset['symbol']}: {total}")
            send_message("\n".join(message_lines))
        except Exception as e:
            send_message(f"❌ فشل جلب الرصيد:\n{e}")

    else:
        send_message("👋 أمر غير معروف!")

    return jsonify({"ok": True})

# تشغيل التطبيق
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)