import os, time, redis, threading, requests
from flask import Flask, request
from market_scanner import pick_best_symbol
from memory import save_trade
from utils import bitvavo_request

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
RSI_KEY = "nems:rsi_level"
IS_RUNNING = "nems:is_running"
IN_TRADE = "nems:is_in_trade"
LAST_TRADE = "nems:last_trade"
STATUS_KEY = "nems:status_message"

def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("📡 فشل إرسال التلغرام:", e)

def fetch_price(symbol):
    try:
        res = requests.get(f"https://api.bitvavo.com/v2/ticker/price?market={symbol}")
        return float(res.json().get("price"))
    except:
        return None
def buy(symbol):
    price = fetch_price(symbol)
    if not price:
        return None, None
    amount = round(BUY_AMOUNT_EUR / price, 6)
    body = {
        "market": symbol,
        "side": "buy",
        "orderType": "market",
        "amount": str(amount),
        "operatorId": ""
    }
    try:
        order = bitvavo_request("POST", "/order", body)
        filled = float(order.get("filledAmount", 0))
        executed_price = float(order.get("avgExecutionPrice", price))
        if filled == 0:
            print("⚠️ لم يتم تنفيذ الشراء. الرد الكامل:", order)
            return None, None
        return order, executed_price
    except Exception as e:
        print("❌ خطأ في الشراء:", e)
        return None, None

def sell(symbol, amount):
    body = {
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "amount": str(amount),
        "operatorId": ""
    }
    try:
        order = bitvavo_request("POST", "/order", body)
        return order
    except Exception as e:
        print("❌ خطأ في البيع:", e)
        return None

def trader():
    while True:
        if r.get(IS_RUNNING) != b"1":
            time.sleep(5)
            continue

        if r.get(IN_TRADE) == b"1":
            time.sleep(5)
            continue

        symbol, reason, rsi = pick_best_symbol()

        if not symbol and reason:
            r.set(STATUS_KEY, reason)
        elif symbol:
            r.set(STATUS_KEY, f"🚀 دخلت على {symbol}")

            order, entry_price = buy(symbol)
            if not order:
                continue

            r.set(IN_TRADE, "1")
            r.set(LAST_TRADE, f"{symbol}:{entry_price}")
            send(f"{symbol.split('-')[0]} 🤖")

            time.sleep(90)

            amount = order.get("filledAmount", "0")
            sell_order = sell(symbol, amount)
            if not sell_order:
                r.set(IN_TRADE, "0")
                continue

            exit_price = float(sell_order.get("avgExecutionPrice", entry_price))
            percent = ((exit_price - entry_price) / entry_price) * 100
            result = "ربح ✅" if percent >= 0 else "خسارة ❌"
            save_trade(symbol, entry_price, exit_price, reason, result, percent)
            send(f"{symbol.split('-')[0]} {percent:.2f}%")

            r.set(IN_TRADE, "0")

        time.sleep(15)

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    msg = data.get("message", {}).get("text", "")
    if not msg:
        return "", 200

    if "/play" in msg:
        r.set(IS_RUNNING, "1")
        send("✅ النمس بدأ التشغيل")

    elif "/stop" in msg:
        r.set(IS_RUNNING, "0")
        send("🛑 تم إيقاف النمس")

    elif "/reset" in msg:
        r.set(IN_TRADE, "0")
        r.delete(LAST_TRADE)
        send("🔄 تمت إعادة التهيئة")

    elif "/شو عم تعمل" in msg or "شو عم تعمل" in msg:
        is_running = r.get(IS_RUNNING)
        rsi = r.get(RSI_KEY)
        status = r.get(STATUS_KEY)
        msg = f"🔍 التشغيل: {'✅' if is_running == b'1' else '🛑'}\n"
        msg += f"🎯 RSI: {rsi.decode() if rsi else '؟'}\n"
        msg += f"📡 الحالة: {status.decode() if status else '🤐 لا يوجد إشعار'}"
        send(msg)

    elif "/الملخص" in msg:
        trades = r.lrange("nems:trades", 0, 9)
        text = "🧾 آخر 10 صفقات:\n\n" + "\n".join([t.decode() for t in trades])
        send(text)

    return "", 200

if __name__ == "__main__":
    threading.Thread(target=trader).start()
    app.run(host="0.0.0.0", port=8000)