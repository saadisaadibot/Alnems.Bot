import os, json, time, hmac, hashlib, requests
from flask import Flask, request

app = Flask(__name__)

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # رابط Railway

# التوقيع
def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest(), body_str

# إرسال طلب إلى Bitvavo
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
    try:
        return requests.request(method, url, headers=headers, data=body_str).json()
    except Exception as e:
        return {"error": str(e)}

# إرسال رسالة إلى Telegram
def send_message(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("Send message error:", e)

# المسار الرئيسي للويب هوك
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if not data:
        return "No data", 400

    message_obj = data.get("message", {})
    message = message_obj.get("text", "").strip()
    if not message:
        return "No message", 200

    # أوامر تلغرام
    if "رصيد" in message:
        balance = bitvavo_request("GET", "/balance")
        msg = "🐷 الرصيد:\n"
        if isinstance(balance, list):
            for item in balance:
                symbol = item.get("symbol")
                available = item.get("available")
                if symbol and available and float(available) > 0:
                    msg += f"{symbol}: {available}\n"
        else:
            msg += "❌ خطأ في جلب الرصيد."
        send_message(msg)

    elif "اشتري" in message:
        price_info = bitvavo_request("GET", "/ticker/price?market=ADA-EUR")
        price = float(price_info.get("price", 0))
        eur_amount = 10
        ada_amount = round(eur_amount / price, 2)
        body = {
            "market": "ADA-EUR",
            "amount": str(ada_amount),
            "side": "buy",
            "orderType": "market",
            "operatorId": ""  # ضروري حسب بيتفافو
        }
        result = bitvavo_request("POST", "/order", body)
        send_message(f"🟢 شراء ADA:\n{result}")

    elif "بيع" in message:
        balance = bitvavo_request("GET", "/balance")
        ada = next((b for b in balance if b.get("symbol") == "ADA"), None)
        if ada and float(ada.get("available", 0)) > 0:
            body = {
                "market": "ADA-EUR",
                "amount": ada["available"],
                "side": "sell",
                "orderType": "market",
                "operatorId": ""
            }
            result = bitvavo_request("POST", "/order", body)
            send_message(f"🔴 بيع ADA:\n{result}")
        else:
            send_message("⚠️ لا يوجد ADA للبيع.")
    else:
        send_message("❓ أمر غير مفهوم، جرب: رصيد / اشتري / بيع")

    return "OK"

# تسجيل Webhook عند التشغيل
def register_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    requests.post(url, data={"url": f"{WEBHOOK_URL}/webhook"})

if __name__ == "__main__":
    register_webhook()
    app.run(host="0.0.0.0", port=8080)