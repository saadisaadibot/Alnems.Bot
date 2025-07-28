import os
import time
import threading
import redis
import requests
from flask import Flask, request, jsonify
from bitvavo_client.bitvavo import Bitvavo
from market_scanner import pick_best_symbol
from memory import save_trade

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
IN_TRADE_KEY = "nems:in_trade"
IS_RUNNING_KEY = "scanner:enabled"
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def fetch_price(symbol):
    try:
        price = BITVAVO.tickerPrice({"market": symbol})
        return float(price["price"])
    except:
        return None

def buy(symbol, source="ai"):
    if r.hexists("entry", symbol):
        send_message(f"⚠️ تم شراء {symbol} مسبقًا، بانتظار البيع.")
        return False

    balance = bitvavo_request("GET", "/balance")
    eur_balance = next((float(b['available']) for b in balance if b['symbol'] == 'EUR'), 0)

    if eur_balance < BUY_AMOUNT_EUR:
        send_message(f"🚫 لا يمكن شراء {symbol}، الرصيد غير كافٍ ({eur_balance:.2f} EUR).")
        return False

    order_body = {
        "amountQuote": str(BUY_AMOUNT_EUR),
        "market": symbol,
        "side": "buy",
        "orderType": "market",
        "operatorId": ""
    }
    result = bitvavo_request("POST", "/order", order_body)

    if "orderId" in result:
        price = float(result.get("avgPrice", "0") or "0")
        if price == 0:
            price = fetch_price(symbol)
        if price:
            r.hset("orders", symbol, "شراء")
            r.hset("entry", symbol, price)
            r.hset("peak", symbol, price)
            r.hset("source", symbol, source)
            send_message(f"✅ تم شراء {symbol} بسعر {price} EUR")
            return price
        else:
            send_message(f"❌ تم تنفيذ الشراء لكن لم نستطع تحديد السعر لـ {symbol}")
    else:
        send_message(f"❌ فشل الشراء: {result.get('error', 'غير معروف')}")
    return False

def sell(symbol, amount):
    try:
        return BITVAVO.placeOrder({
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(amount)
        })
    except Exception as e:
        print("خطأ في البيع:", e)
        return None

def watch(symbol, entry_price, reason):
    max_price = entry_price
    while True:
        price = fetch_price(symbol)
        if not price:
            time.sleep(1)
            continue

        max_price = max(max_price, price)
        change = (price - entry_price) / entry_price * 100

        if change >= 1.5:
            result = "ربح ✅"
            percent = change
            break
        elif change <= -1:
            result = "خسارة ❌"
            percent = change
            break

        time.sleep(1)

    balances = BITVAVO.balance(symbol.split("-")[0])
    amount = float(balances[0].get("available", 0))
    if amount > 0:
        sell(symbol, round(amount, 6))

    save_trade(symbol, entry_price, price, reason, result, percent)
    r.delete(IN_TRADE_KEY)

def run_loop():
    r.set(IS_RUNNING_KEY, 1)
    while True:
        if r.get(IS_RUNNING_KEY) != b"1":
            time.sleep(5)
            continue

        if r.get(IN_TRADE_KEY):
            time.sleep(3)
            continue

        symbol, reason, score = pick_best_symbol()
        if not symbol:
            print("❌ لا توجد فرصة مناسبة حالياً.")
            time.sleep(30)
            continue

        print(f"✅ فرصة على {symbol} | {reason} | Score={score}")
        order, price = buy(symbol)
        if not order:
            continue  # تجاهل الصفقة إذا فشل الشراء

        r.set(IN_TRADE_KEY, symbol)
        watch(symbol, price, reason)

@app.route("/", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data or "message" not in data:
        return jsonify({"status": "no message"}), 200

    text = data["message"].get("text", "").strip().lower()
    
    if text == "stop":
        r.set(IS_RUNNING_KEY, 0)
        send_message("⛔ تم إيقاف النمس مؤقتاً.")
    elif text == "play":
        r.set(IS_RUNNING_KEY, 1)
        send_message("✅ تم تشغيل النمس.")
    elif text == "شو عم تعمل":
        running = r.get(IS_RUNNING_KEY) == b"1"
        trade = r.get(IN_TRADE_KEY)
        msg = "🤖 النمس يعمل حالياً ✅\n" if running else "⏸️ النمس موقوف حالياً.\n"
        if trade:
            msg += f"حالياً في صفقة على {trade.decode()}."
        else:
            msg += "لا يوجد صفقة حالياً."
        send_message(msg)
    elif text == "reset":
        r.delete(IN_TRADE_KEY)
        send_message("✅ تم مسح الصفقة العالقة.")

    elif text == "الملخص":
        trades = r.lrange("nems:trades", 0, -1)
        if not trades:
            send_message("لا توجد صفقات مسجلة بعد.")
        else:
            msg = "📊 ملخص الصفقات:\n"
            for t in trades[-10:][::-1]:
                msg += f"• {t.decode()}\n"
            send_message(msg)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)