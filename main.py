import os
import time
import threading
import redis
import requests
from flask import Flask, request, jsonify
from bitvavo_client.bitvavo import Bitvavo

from market_scanner import pick_best_symbol
from memory import save_trade
from utils import get_rsi

# إعداد Flask و Redis
app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

# إعداد Bitvavo API
BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

# إعدادات عامة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

# مفاتيح Redis
IN_TRADE_KEY = "nems:in_trade"
IS_RUNNING_KEY = "scanner:enabled"
RSI_LEVEL_KEY = "nems:rsi_level"

# إرسال رسالة Telegram
def send_message(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# جلب السعر الحالي
def fetch_price(symbol):
    try:
        price = BITVAVO.tickerPrice({"market": symbol})
        return float(price["price"])
    except:
        return None

# تنفيذ أمر شراء
def buy(symbol):
    price = fetch_price(symbol)
    if not price:
        return None, None

    amount = round(BUY_AMOUNT_EUR / price, 6)
    try:
        order = BITVAVO.placeOrder({
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(amount)
        })
        filled = float(order.get("filledAmount", 0))
        executed_price = float(order.get("avgExecutionPrice", price))

        if filled == 0:
            return None, None

        coin = symbol.split("-")[0]
        send_message(f"{coin} 🤖 {round(executed_price, 4)}")
        return order, executed_price
    except:
        return None, None

# تنفيذ أمر بيع
def sell(symbol, amount, entry_price):
    try:
        BITVAVO.placeOrder({
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(amount)
        })
        price = fetch_price(symbol)
        change = (price - entry_price) / entry_price * 100
        coin = symbol.split("-")[0]
        send_message(f"{coin} {round(change, 2)}%")
        return change
    except:
        return None

# تعديل مستوى RSI حسب نتيجة الصفقة
def adjust_rsi(result):
    level = int(r.get(RSI_LEVEL_KEY) or 46)
    if result == "ربح ✅":
        level = max(level - 1, 30)
    else:
        level = min(level + 1, 70)
    r.set(RSI_LEVEL_KEY, level)

# مراقبة العملة بعد الشراء
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

    coin = symbol.split("-")[0]
    balances = BITVAVO.balance(coin)
    amount = float(balances[0].get("available", 0))

    if amount > 0:
        sell(symbol, round(amount, 6), entry_price)
        save_trade(symbol, entry_price, price, reason, result, percent)
        adjust_rsi(result)

    r.delete(IN_TRADE_KEY)

# الحلقة الرئيسية
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
            print("❌ لا توجد فرصة حالياً")
            time.sleep(30)
            continue

        order, price = buy(symbol)
        if not order:
            continue

        r.set(IN_TRADE_KEY, symbol)
        watch(symbol, price, reason)

# Telegram Webhook
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
        msg = "🤖 النمس يعمل ✅\n" if running else "⏸️ النمس موقوف.\n"
        msg += f"صفقة حالياً: {trade.decode()}" if trade else "لا يوجد صفقة حالياً."
        send_message(msg)
    elif text == "reset":
        r.delete(IN_TRADE_KEY)
        send_message("✅ تم مسح الصفقة العالقة.")
    elif text == "الملخص":
        trades = r.lrange("nems:trades", 0, -1)
        if not trades:
            send_message("لا توجد صفقات مسجلة.")
        else:
            msg = "📊 ملخص آخر الصفقات:\n"
            for t in trades[-10:][::-1]:
                msg += f"• {t.decode()}\n"
            send_message(msg)

    return jsonify({"status": "ok"}), 200

# تشغيل الخادم والبوت
if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)