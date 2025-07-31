import os, json, time, hmac, hashlib, uuid, requests
from flask import Flask, request

app = Flask(__name__)

# مفاتيح البيئة
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # مثل: https://worker-production-d9d0.up.railway.app

# توليد توقيع
def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    signature = hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return signature, body_str

# إرسال الطلب
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

# إرسال رسالة تلغرام
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

# توليد معرف فريد لكل أمر
def generate_order_id():
    return "nems-" + uuid.uuid4().hex[:10]

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    msg = data.get("message", {}).get("text", "").strip()

    if not msg:
        return "No message", 200

    if "رصيد" in msg:
        balance = bitvavo_request("GET", "/balance")
        text = "📦 الرصيد:\n"
        for item in balance:
            symbol = item.get("symbol")
            available = item.get("available")
            if float(available) > 0:
                text += f"{symbol}: {available}\n"
        send_message(text or "📭 لا يوجد رصيد")

    elif "اشتري" in msg:
        price_info = bitvavo_request("GET", "/ticker/price?market=ADA-EUR")
        price = float(price_info.get("price", 0))
        if price == 0:
            send_message("❌ فشل جلب السعر")
            return "Error", 200

        eur_amount = 10
        ada_amount = round(eur_amount / price, 2)

        body = {
            "market": "ADA-EUR",
            "amount": str(ada_amount),
            "side": "buy",
            "orderType": "market",
            "clientOrderId": generate_order_id()
        }

        order = bitvavo_request("POST", "/order", body)
        if order.get("error"):
            send_message(f"❌ فشل الشراء:\n{order}")
        else:
            send_message(f"✅ تم الشراء:\n{order}")

    elif "بيع" in msg:
        balance = bitvavo_request("GET", "/balance")
        ada = next((x for x in balance if x["symbol"] == "ADA"), None)
        if not ada or float(ada["available"]) == 0:
            send_message("⚠️ لا يوجد ADA للبيع")
            return "No ADA", 200

        body = {
            "market": "ADA-EUR",
            "amount": ada["available"],
            "side": "sell",
            "orderType": "market",
            "clientOrderId": generate_order_id()
        }

        order = bitvavo_request("POST", "/order", body)
        if order.get("error"):
            send_message(f"❌ فشل البيع:\n{order}")
        else:
            send_message(f"✅ تم البيع:\n{order}")

    return "OK", 200

# تسجيل الويب هوك عند التشغيل
def register_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    requests.post(url, data={"url": f"{WEBHOOK_URL}/webhook"})

if __name__ == "__main__":
    register_webhook()
    app.run(host="0.0.0.0", port=8080)