import os
import json
import time
import hmac
import hashlib
import redis
import requests
from flask import Flask, request
from threading import Thread

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("❌ فشل إرسال التلغرام:", e)

def create_signature(timestamp, method, path, body):
    body_str = "" if body is None else json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, path, body)
    headers = {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Signature": signature,
        "Content-Type": "application/json"
    }
    url = f"https://api.bitvavo.com/v2{path}"
    response = requests.request(method, url, headers=headers, json=body)
    return response.json()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    msg = data.get("message", {}).get("text", "")

    if "/الرصيد" in msg:
        balances = bitvavo_request("GET", "/balance")
        text = "💰 رصيد الحساب:\n"
        for b in balances:
            asset = b.get("symbol") or b.get("currency") or "??"
            available = b.get("available")
            in_order = b.get("inOrder")
            try:
                if float(available or 0) > 0 or float(in_order or 0) > 0:
                    text += f"{asset}: متاح={available}, مجمّد={in_order}\n"
            except:
                continue
        send_message(text)

    elif "/اشتري" in msg:
        body = {
            "market": "ADA-EUR",
            "side": "buy",
            "orderType": "market",
            "amount": "10"
        }
        res = bitvavo_request("POST", "/order", body)
        send_message(f"📥 أمر شراء:\n{json.dumps(res, indent=2, ensure_ascii=False)}")

    elif "/بيع" in msg:
        body = {
            "market": "ADA-EUR",
            "side": "sell",
            "orderType": "market",
            "amount": "10"
        }
        res = bitvavo_request("POST", "/order", body)
        send_message(f"📤 أمر بيع:\n{json.dumps(res, indent=2, ensure_ascii=False)}")

    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)