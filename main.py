import os
import json
import time
import redis
import requests
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo

# إعداد التطبيق و Redis
app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

# إعداد المفاتيح الخاصة بالنمس
bitvavo = Bitvavo({
    'APIKEY': os.getenv("SCALPER_API_KEY"),
    'APISECRET': os.getenv("SCALPER_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = 10  # شراء دائمًا بـ 10 يورو

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("فشل إرسال الرسالة:", e)

@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    text = data.get("message", {}).get("text", "").strip()
    chat_id = data.get("message", {}).get("chat", {}).get("id")

    if text == "اشتري يا نمس":
        try:
            # شراء 10 يورو من BTC كمثال
            response = bitvavo.placeOrder("BTC-EUR", {
                "side": "buy",
                "orderType": "market",
                "amount": str(BUY_AMOUNT_EUR / get_price("BTC-EUR"))
            })
            send_message("✅ تم الشراء يا نمس")
        except Exception as e:
            send_message(f"❌ فشل الشراء: {e}")

    elif text == "بيع يا نمس":
        try:
            balance = bitvavo.balance("BTC")
            amount = float(balance.get("available", 0))
            if amount > 0:
                bitvavo.placeOrder("BTC-EUR", {
                    "side": "sell",
                    "orderType": "market",
                    "amount": str(amount)
                })
                send_message("✅ تم البيع يا نمس")
            else:
                send_message("🚫 لا يوجد BTC للبيع")
        except Exception as e:
            send_message(f"❌ فشل البيع: {e}")

    return "", 200

def get_price(symbol):
    try:
        ticker = bitvavo.tickerPrice(symbol)
        return float(ticker["price"])
    except:
        return 0

# لتشغيل Flask على Railway
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
