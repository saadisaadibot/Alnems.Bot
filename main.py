import os
import redis
import requests
import json
import time
import hmac
import hashlib
from flask import Flask, request
from threading import Thread

# إعدادات أساسية
app = Flask(__name__)
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
REDIS_URL = os.getenv("REDIS_URL")
r = redis.from_url(REDIS_URL)

# إرسال رسالة تيليغرام
def send_message(text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})

# توقيع HMAC
def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

# طلب Bitvavo
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

# المراقبة التلقائية
def watch():
    while True:
        try:
            orders = r.hgetall("orders")
            for key, status in orders.items():
                symbol = key.decode()
                if "شراء" not in status.decode():
                    continue
                price = fetch_price(symbol)
                if price is None:
                    continue
                entry = float(r.hget("entry", symbol))
                peak = float(r.hget("peak", symbol) or entry)
                change = ((price - entry) / entry) * 100
                peak = max(peak, price)
                r.hset("peak", symbol, peak)
                drop_from_peak = ((price - peak) / peak) * 100

                if change >= 3:
                    send_message(f"🚀 {symbol} تجاوز +3%! يراقب الآن تراجع -1.5% من القمة.")
                if change <= -2:
                    send_message(f"🛑 Stop Loss مفعل لـ {symbol}")
                    sell(symbol)
                    r.hset("orders", symbol, "بيع - Stop Loss")
                elif change >= 3 and drop_from_peak <= -1.5:
                    send_message(f"📉 تراجع من القمة -1.5% تم البيع: {symbol}")
                    sell(symbol)
                    r.hset("orders", symbol, "بيع - Trail Stop")
        except Exception as e:
            print("❌ Error in watch loop:", str(e))
        time.sleep(5)

# جلب السعر الحالي
def fetch_price(symbol):
    try:
        url = f"https://api.bitvavo.com/v2/ticker/price?market={symbol}"
        res = requests.get(url)
        return float(res.json()["price"]) if res.status_code == 200 else None
    except:
        return None

# أمر بيع
def sell(symbol):
    coin = symbol.split("-")[0]
    balance = bitvavo_request("GET", "/balance")
    coin_balance = next((b['available'] for b in balance if b['symbol'] == coin), '0')
    if float(coin_balance) > 0:
        order_body = {
            "amount": coin_balance,
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "operatorId": ""
        }
        result = bitvavo_request("POST", "/order", order_body)
        if "error" not in result:
            send_message(f"✅ بيع {symbol} تم بنجاح")
        else:
            send_message(f"❌ فشل البيع: {result['error']}")
    else:
        send_message(f"⚠️ لا يوجد رصيد كافٍ لبيع {symbol}")

# نقطة البداية
@app.route("/")
def home():
    return "Toto Premium 🟢", 200

# استقبال Webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return '', 200

    text = data["message"].get("text", "").strip().lower()
    print("📩", text)

    if "الملخص" in text:
        orders = r.hgetall("orders")
        if not orders:
            send_message("📭 لا توجد عمليات.")
        else:
            summary = "\n".join(f"{k.decode()} → {v.decode()}" for k, v in orders.items())
            send_message(summary)

    elif "امسح الذاكرة" in text:
        r.flushall()
        send_message("🧹 تم مسح الذاكرة.")

    elif "الرصيد" in text:
        balance = bitvavo_request("GET", "/balance")
        try:
            eur = next((b['available'] for b in balance if b['symbol'] == 'EUR'), '0')
            send_message(f"💰 الرصيد المتاح: {eur} EUR")
        except:
            send_message("❌ فشل جلب الرصيد.")

    elif "اشتري" in text and "يا توتو" in text:
        try:
            parts = text.split()
            coin = parts[1].upper()
            symbol = coin + "-EUR"
            order_body = {
                "amountQuote": "10",
                "market": symbol,
                "side": "buy",
                "orderType": "market",
                "operatorId": ""
            }
            result = bitvavo_request("POST", "/order", order_body)
            if "error" not in result:
                r.hset("orders", symbol, "شراء")
                price = fetch_price(symbol)
                r.hset("entry", symbol, price)
                r.hset("peak", symbol, price)
                send_message(f"✅ تم شراء {symbol} بنجاح بسعر {price} EUR")
            else:
                send_message(f"❌ فشل الشراء: {result['error']}")
        except Exception as e:
            send_message(f"❌ خطأ في الشراء: {str(e)}")

    elif "بيع" in text and "يا توتو" in text:
        try:
            coin = text.split()[1].upper()
            symbol = coin + "-EUR"
            sell(symbol)
            r.hset("orders", symbol, "بيع يدوي")
        except Exception as e:
            send_message(f"❌ خطأ في البيع: {str(e)}")

    return '', 200

# تشغيل المراقبة
if __name__ == "__main__":
    send_message("🚀 Toto Premium بدأ العمل!")
    Thread(target=watch).start()
    app.run(host="0.0.0.0", port=8080)