import os, json, time, hmac, hashlib, requests
from flask import Flask, request

app = Flask(__name__)

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # لازم تسجلو بريلواي

def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest(), body_str

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    signature, body_str = create_signature(timestamp, method, path, body)
    headers = {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }
    url = "https://api.bitvavo.com/v2" + path
    response = requests.request(method, url, headers=headers, data=body_str)
    return response.json()

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    message = data.get("message", {}).get("text", "")
    
    if "رصيد" in message:
        balance = bitvavo_request("GET", "/balance")
        msg = "📦 الرصيد:\n"
        for item in balance:
            symbol = item.get("symbol")
            available = item.get("available")
            if float(available) > 0:
                msg += f"{symbol}: {available}\n"
        send_message(msg)

    elif "اشتري" in message:
        # شراء ADA بقيمة 10 يورو تقريباً (حسب السوق)
        price_info = bitvavo_request("GET", "/ticker/price?market=ADA-EUR")
        price = float(price_info.get("price", 0))
        eur_amount = 10
        ada_amount = round(eur_amount / price, 2)

        body = {
            "market": "ADA-EUR",
            "amount": str(ada_amount),
            "side": "buy",
            "orderType": "market",
            "operatorId": ""  # لتجاوز خطأ 203
        }
        result = bitvavo_request("POST", "/order", body)
        send_message(f"🟢 شراء ADA:\n{result}")

    elif "بيع" in message:
        balance = bitvavo_request("GET", "/balance")
        ada = next((b for b in balance if b["symbol"] == "ADA"), None)
        if ada and float(ada["available"]) > 0:
            body = {
                "market": "ADA-EUR",
                "amount": ada["available"],
                "side": "sell",
                "orderType": "market",
                "operatorId": ""  # لتجاوز خطأ 205
            }
            result = bitvavo_request("POST", "/order", body)
            send_message(f"🔴 بيع ADA:\n{result}")
        else:
            send_message("⚠️ لا يوجد ADA للبيع.")

    return "OK"

# لتسجيل Webhook عند أول تشغيل
def register_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    requests.post(url, data={"url": f"{WEBHOOK_URL}/webhook"})

if __name__ == "__main__":
    register_webhook()
    app.run(host="0.0.0.0", port=8080)