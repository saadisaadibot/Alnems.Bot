import os, json, time, redis, requests
from flask import Flask, request
from threading import Thread
from datetime import datetime
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

bitvavo = Bitvavo({
    'APIKEY': BITVAVO_API_KEY,
    'APISECRET': BITVAVO_API_SECRET,
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

# ========== أدوات أساسية ==========
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except Exception as e:
        print(f"[Telegram Error] {e}")

def fetch_price(symbol):
    try:
        data = bitvavo.tickerPrice({'market': symbol})
        return float(data['price'])
    except:
        return None

def bitvavo_request(method, path, body=None):
    try:
        return bitvavo._Bitvavo__makeRequest(method, path, body or {})
    except Exception as e:
        print(f"[Bitvavo Error] {e}")
        return {}

# ========== المراقبة بعد الشراء ==========
def watch(symbol, entry_price, source):
    while True:
        time.sleep(0.5)
        price = fetch_price(symbol)
        if not price:
            continue
        change = ((price - entry_price) / entry_price) * 100
        if change >= 1.5 or change <= -0.5:
            break

    amount = BUY_AMOUNT_EUR / entry_price
    order_body = {
        "amount": str(round(amount, 8)),
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "operatorId": ""
    }
    result = bitvavo_request("POST", "/order", order_body)

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

# ========== Webhook رئيسي ==========
@app.route("/", methods=["POST"])
def webhook():
    data = request.json
    msg = data.get("message", {}).get("text", "").lower()
    chat_id = str(data.get("message", {}).get("chat", {}).get("id", ""))
    if chat_id != str(CHAT_ID):
        return "ok"

    if msg.startswith("اشتري") and "يا نمس" in msg:
        coin = msg.split()[1].upper()
        symbol = coin + "-EUR"
        source = "كوكو" if "يا نمس" in msg else "يدوي"
        execute_buy(symbol, source)

    elif "الملخص" in msg:
        data = r.hgetall("profits")
        if not data:
            send_message("لا يوجد صفقات بعد.")
            return "ok"

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

    return "ok"

# ========== تشغيل السيرفر ==========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))