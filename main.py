import os
import time
import threading
import redis
import requests
import json
from flask import Flask, request, jsonify
from market_scanner import pick_best_symbol
from memory import save_trade, is_in_trade, set_in_trade, clear_trade, adjust_rsi
from utils import BITVAVO

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
IS_RUNNING_KEY = "bot:is_running"
TRADE_HISTORY_KEY = "bot:history"

r.set(IS_RUNNING_KEY, 1)  # تشغيل افتراضي

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def fetch_price(symbol):
    try:
        data = BITVAVO.tickerPrice({"market": symbol})
        return float(data["price"])
    except:
        return None

def buy(symbol):
    price = fetch_price(symbol)
    if not price:
        return None, None

    amount = round(BUY_AMOUNT_EUR / price, 6)
    try:
        BITVAVO.placeOrder({
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""
        })
        send_message(f"شراء = \"{symbol}\" 🤖 {round(price, 4)}")
        return price, amount
    except Exception as e:
        print(f"❌ Buy Failed: {e}")
        return None, None

def sell(symbol, amount, entry_price):
    try:
        BITVAVO.placeOrder({
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""
        })
        final_price = fetch_price(symbol)
        change = ((final_price - entry_price) / entry_price) * 100
        send_message(f"بيع = \"{symbol}\" {change:+.2f}%")
        return change
    except Exception as e:
        print(f"❌ Sell Failed: {e}")
        return None

def log_trade(symbol, entry, exit, result, change):
    text = f"{symbol}: {result} {change:+.2f}%"
    r.lpush(TRADE_HISTORY_KEY, text)
    r.ltrim(TRADE_HISTORY_KEY, 0, 9)  # آخر 10 فقط

def run_loop():
    while True:
        if r.get(IS_RUNNING_KEY) != b"1":
            time.sleep(5)
            continue

        if is_in_trade():
            time.sleep(10)
            continue

        symbol, reason, score = pick_best_symbol()
        if not symbol:
            print("❌ لا توجد فرصة حالياً")
            time.sleep(10)
            continue

        price, amount = buy(symbol)
        if not price:
            time.sleep(10)
            continue

        set_in_trade(symbol, price, amount)

        while True:
            time.sleep(15)
            current = fetch_price(symbol)
            if not current:
                continue

            change = ((current - price) / price) * 100
            if abs(change) >= 1:
                result = "ربح ✅" if change > 0 else "خسارة ❌"
                done = sell(symbol, amount, price)
                if done is not None:
                    adjust_rsi(result)
                    log_trade(symbol, price, current, result, done)
                clear_trade()
                break

# 📩 Telegram Webhook
@app.route("/", methods=["POST"])
def telegram():
    data = request.json
    if not data or "message" not in data:
        return jsonify({"status": "no message"}), 200

    text = data["message"].get("text", "").strip().lower()

    if text == "stop":
        r.set(IS_RUNNING_KEY, 0)
        send_message("⛔ تم إيقاف البوت مؤقتاً.")
    elif text == "play":
        r.set(IS_RUNNING_KEY, 1)
        send_message("✅ تم تشغيل البوت.")
    elif text == "الملخص":
        trades = r.lrange(TRADE_HISTORY_KEY, 0, -1)
        if not trades:
            send_message("لا يوجد صفقات مسجلة بعد.")
        else:
            msg = "📊 آخر الصفقات:\n" + "\n".join(f"• {t.decode()}" for t in trades)
            send_message(msg)
    elif text == "شو عم تعمل":
        running = r.get(IS_RUNNING_KEY) == b"1"
        msg = "🤖 البوت يعمل حالياً ✅\n" if running else "⏸️ البوت متوقف حالياً.\n"
        if is_in_trade():
            trade = r.get("bot:current_trade")
            if trade:
                data = json.loads(trade)
                msg += f"صفقة حالياً على {data['symbol']}"
        else:
            msg += "لا يوجد صفقة حالياً."
        send_message(msg)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)