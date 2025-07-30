import os, time, redis, threading, requests, json, hmac, hashlib
from flask import Flask, request
from market_scanner import pick_best_symbol
from memory import save_trade, r
from utils import create_signature

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
RSI_KEY = "nems:rsi_level"
TRADE_STATUS_KEY = "nems:is_in_trade"
STATUS_MESSAGE_KEY = "nems:status_message"
LOCK_KEY = "nems:lock"

# ------------------ Telegram Message ------------------
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except:
        pass

# ------------------ Bitvavo Request ------------------
def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    message = f"{timestamp}{method}{path}{body_str}"
    signature = hmac.new(BITVAVO_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }
    url = f"https://api.bitvavo.com/v2{path}"
    response = requests.request(method, url, headers=headers, json=body)
    return response.json()

# ------------------ BUY ------------------
def buy(symbol):
    try:
        resp = bitvavo_request("POST", "/order", {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT_EUR),
            "operatorId": "nems_pro"
        })
        if "id" in resp:
            return resp
        else:
            send_message(f"🚫 فشل الشراء: {resp}")
            r.setex(f"{LOCK_KEY}:{symbol}", 1800, "1")  # حظر العملة 30 دقيقة
            return None
    except Exception as e:
        send_message(f"🚫 خطأ أثناء الشراء: {e}")
        return None

# ------------------ SELL ------------------
def sell(symbol, amount):
    try:
        resp = bitvavo_request("POST", "/order", {
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": "nems_pro"
        })
        return resp
    except Exception as e:
        send_message(f"🚫 خطأ أثناء البيع: {e}")
        return None

# ------------------ BALANCE ------------------
def get_balance(symbol):
    try:
        data = bitvavo_request("GET", "/balance", None)
        for item in data:
            if item["symbol"] == symbol.replace("-EUR", ""):
                return float(item["available"])
        return 0
    except:
        return 0

# ------------------ TRADER LOGIC ------------------
def trader():
    while True:
        if r.get("nems:running") != b"1":
            r.set(STATUS_MESSAGE_KEY, "⏸️ البوت متوقف حاليًا")
            time.sleep(5)
            continue

        if r.get(TRADE_STATUS_KEY) == b"1":
            r.set(STATUS_MESSAGE_KEY, "💼 في صفقة حالياً")
            time.sleep(5)
            continue

        symbol, reason, rsi = pick_best_symbol()
        if not symbol:
            r.set(STATUS_MESSAGE_KEY, "🔍 لا يوجد فرص حالياً")
            time.sleep(5)
            continue

        if r.get(f"{LOCK_KEY}:{symbol}"):
            r.set(STATUS_MESSAGE_KEY, f"🚫 {symbol} محظورة مؤقتاً")
            time.sleep(5)
            continue

        r.set(STATUS_MESSAGE_KEY, f"🟢 شراء {symbol} بسبب {reason}")
        buy_result = buy(symbol)
        if not buy_result:
            continue

        entry_price = float(buy_result.get("fills", [{}])[0].get("price", 0))
        r.set(TRADE_STATUS_KEY, "1")
        send_message(f"📈 تم شراء {symbol} بسعر {entry_price:.4f}€\nسبب الدخول: {reason}")

        time.sleep(30)  # الانتظار قبل البيع

        amount = get_balance(symbol)
        sell_result = sell(symbol, amount)
        exit_price = float(sell_result.get("fills", [{}])[0].get("price", 0))

        percent = ((exit_price - entry_price) / entry_price) * 100
        result = "✅" if percent >= 0 else "❌"
        save_trade(symbol, entry_price, exit_price, reason, result, percent)

        r.set(TRADE_STATUS_KEY, "0")
        send_message(f"{result} تم بيع {symbol} بسعر {exit_price:.4f}€\nالربح: {percent:.2f}%")
        time.sleep(5)

# ------------------ TELEGRAM ------------------
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.json
    if "message" not in data: return "ok"
    text = data["message"].get("text", "")
    user_id = str(data["message"]["chat"]["id"])
    if user_id != CHAT_ID: return "unauthorized"

    if text == "/start" or text == "/play":
        r.set("nems:running", "1")
        send_message("✅ تم تشغيل النمس.")
    elif text == "/stop":
        r.set("nems:running", "0")
        send_message("⛔ تم إيقاف النمس.")
    elif text == "/reset":
        r.set(TRADE_STATUS_KEY, "0")
        send_message("🔄 تم تصفير حالة الصفقة.")
    elif text == "/شو_عم_تعمل":
        msg = r.get(STATUS_MESSAGE_KEY)
        if msg:
            send_message(f"🤖 الحالة: {msg.decode()}")
        else:
            send_message("🤖 الحالة: غير معروف")
    elif text == "/trades":
        trades = r.lrange("nems:trades", 0, 9)
        if not trades:
            send_message("لا يوجد صفقات بعد.")
        else:
            msg = "آخر الصفقات:\n\n"
            for t in trades:
                trade = json.loads(t)
                msg += f"{trade['symbol']} | {trade['result']} | {trade['percent']}%\n"
            send_message(msg)
    elif text == "/الملخص":
        level = r.get(RSI_KEY) or b"45"
        count = r.llen("nems:trades")
        send_message(f"📊 RSI الحالي: {level.decode()}\n📁 عدد الصفقات: {count}")
    return "ok"

# ------------------ RUN ------------------
if __name__ == "__main__":
    threading.Thread(target=trader).start()
    app.run(host="0.0.0.0", port=10000)