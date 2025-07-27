import os
import redis
import requests
import json
import time
import hmac
import hashlib
from flask import Flask, request
from threading import Thread

app = Flask(__name__)
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
REDIS_URL = os.getenv("REDIS_URL")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
r = redis.from_url(REDIS_URL)

r.flushdb()

# ========== أدوات أساسية ==========
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

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

def fetch_price(symbol):
    try:
        res = requests.get(f"https://api.bitvavo.com/v2/ticker/price?market={symbol}")
        return float(res.json()["price"]) if res.status_code == 200 else None
    except:
        return None

def get_available_amount(symbol):
    base = symbol.split("-")[0]
    try:
        balances = bitvavo_request("GET", "/balance")
        for b in balances:
            if b["symbol"] == base:
                return float(b["available"])
    except:
        pass
    return 0.0

# ========== المراقبة بعد الشراء ==========
def watch(symbol, entry_price, source):
    while True:
        time.sleep(0.5)
        price = fetch_price(symbol)
        if not price:
            continue
        change = ((price - entry_price) / entry_price) * 100
        if change >= 1.5 or change <= -1:
            break

    amount = get_available_amount(symbol)
    if amount < 0.0001:
        send_message(f"⚠️ لا يوجد رصيد كافٍ للبيع لـ {symbol}")
        return

    order_body = {
        "amount": str(round(amount, 8)),
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "operatorId": ""
    }
    result = bitvavo_request("POST", "/order", order_body)

    if "orderId" in result:
        price = fetch_price(symbol)
        profit = (price - entry_price) * amount
        percent = ((price - entry_price) / entry_price) * 100

        r.hset("profits", symbol, json.dumps({
            "entry": entry_price,
            "exit": price,
            "profit": round(profit, 2),
            "percent": round(percent, 2),
            "source": source
        }))
        send_message(f"🚪 بيع {symbol} - النسبة: {round(percent,2)}% - المصدر: {source}")
    else:
        send_message(f"❌ فشل في البيع: {result}")

# ========== الشراء ==========
def execute_buy(symbol, source):
    price = fetch_price(symbol)
    if not price:
        send_message(f"❌ لم نتمكن من جلب سعر {symbol}")
        return

    order_body = {
        "amountQuote": str(BUY_AMOUNT_EUR),
        "market": symbol,
        "side": "buy",
        "orderType": "market",
        "operatorId": ""
    }
    result = bitvavo_request("POST", "/order", order_body)
    if "orderId" in result:
        entry = float(result.get("avgPrice", price))
        send_message(f"✅ اشترينا {symbol} بسعر {entry} EUR (المصدر: {source})")
        Thread(target=watch, args=(symbol, entry, source)).start()
    else:
        send_message(f"❌ فشل في الشراء: {result}")

# ========== التفاعل مع Telegram ==========
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    msg = data.get("message", {}).get("text", "").strip().lower()
    if not msg:
        return "", 200

    # أمر الشراء (كوكو أو يدوي)
    if msg.startswith("اشتري") and "يا نمس" in msg:
        coin = msg.split()[1].upper()
        symbol = coin + "-EUR"
        source = "كوكو" if "كوكو" in msg else "يدوي"
        execute_buy(symbol, source)
        return "", 200

    # أمر الملخص
    if "الملخص" in msg:
        data = r.hgetall("profits")
        if not data:
            send_message("لا يوجد صفقات بعد.")
            return "", 200

        total = 0
        count = 0
        sources = {"كوكو": {"sum": 0, "count": 0}, "يدوي": {"sum": 0, "count": 0}}
        summary = "📊 ملخص الأرباح:\n"
        for k, v in data.items():
            k = k.decode()
            v = json.loads(v)
            total += v["profit"]
            count += 1
            src = v.get("source", "يدوي")
            sources[src]["sum"] += v["profit"]
            sources[src]["count"] += 1
            summary += f"{k}: {v['profit']} EUR ({v['percent']}%) - {src}\n"

        summary += f"\n📈 الإجمالي: {round(total, 2)} EUR عبر {count} صفقة"
        for s, vals in sources.items():
            summary += f"\n- {s}: {round(vals['sum'],2)} EUR في {vals['count']} صفقة"
        send_message(summary)
        return "", 200

    return "", 200

@app.route("/")
def home():
    return "النمس 🐆 يعمل!", 200

# ========== بدء التشغيل ==========
if __name__ == "__main__":
    send_message("✅ النمس بدأ - يدوي وكوكو!")
    app.run(host="0.0.0.0", port=8080)