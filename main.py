import os, json, hmac, hashlib, time, requests
from flask import Flask, request
from threading import Thread
from websocket import WebSocketApp

app = Flask(__name__)

# 🟢 مفاتيح البيئة
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
bitvavo_rest = "https://api.bitvavo.com/v2"
bitvavo_ws = "wss://ws.bitvavo.com/v2"

# 🔁 حالة البوت
is_running = True
symbol_in_position = None
entry_price = 0
profits = []
top_symbols = []
last_top_update = 0

# 📨 Telegram
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID, "text": text})
    except: pass

# 🔐 Headers
def headers(ts, method, path, body=""):
    msg = f"{ts}{method}{path}{body}"
    return {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Timestamp": ts,
        "Bitvavo-Access-Signature": hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest(),
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }

# 🌐 API Request
def bitvavo_request(method, path, body=None):
    ts = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    h = headers(ts, method, path, body_str)
    res = requests.request(method, bitvavo_rest + path, headers=h, data=body_str)
    try: return res.json()
    except: return {}

# 📊 الحصول على Top 30 عملة
def update_top_symbols():
    global top_symbols
    try:
        all = bitvavo_request("GET", "/markets")
        filtered = [m for m in all if m.get("quote") == "EUR" and float(m.get("volume", 0)) > 0]
        top_symbols = sorted(filtered, key=lambda x: float(x["volume"]), reverse=True)[:30]
    except: pass

# 🛒 شراء فوري
def buy_order(symbol):
    return bitvavo_request("POST", "/order", {
        "market": symbol,
        "amountQuote": str(BUY_AMOUNT_EUR),
        "side": "buy",
        "orderType": "market"
    })

# 💰 بيع فوري
def sell_order(symbol, amount):
    return bitvavo_request("POST", "/order", {
        "market": symbol,
        "amount": str(amount),
        "side": "sell",
        "orderType": "market"
    })

# 📈 بدء WebSocket على عملة
def start_socket(symbol):
    def on_message(ws, msg):
        global symbol_in_position, entry_price
        if not is_running or symbol_in_position: return
        try:
            data = json.loads(msg)
            price = float(data["c"])
            history.append(price)
            if len(history) > 20:
                history.pop(0)

            # 🔍 استراتيجية الشمعة المتأرجحة
            if len(history) >= 5:
                last = history[-1]
                prev = history[-2]
                pre_prev = history[-3]
                if last > prev * 1.004 and prev < pre_prev * 0.997:
                    res = buy_order(symbol)
                    fills = res.get("fills", [{}])
                    p = float(fills[0].get("price", 0))
                    if p > 0:
                        symbol_in_position = symbol
                        entry_price = p
                        send_message(f"✅ اشترى {symbol} بسعر {p}")
                        Thread(target=watch_trade).start()
                        ws.close()
        except: pass

    def on_error(ws, e): pass
    def on_close(ws): pass
    def on_open(ws): ws.send(json.dumps({
        "action": "subscribe",
        "channels": [{"name": "ticker", "markets": [symbol]}]
    }))

    history = []
    ws = WebSocketApp(f"{bitvavo_ws}", on_message=on_message, on_error=on_error, on_close=on_close, on_open=on_open)
    Thread(target=ws.run_forever).start()

# 👀 مراقبة الصفقة الحالية
def watch_trade():
    global symbol_in_position, entry_price
    peak = entry_price
    while True:
        try:
            book = bitvavo_request("GET", f"/{symbol_in_position}/book")
            price = float(book.get("asks", [[0]])[0][0])
            if price > peak: peak = price
            profit = (price - entry_price) / entry_price * 100
            if profit >= 1 or profit <= -0.5:
                coin = symbol_in_position.split("-")[0]
                bal = bitvavo_request("GET", f"/balance/{coin}")
                amt = float(bal.get("available", 0))
                sell_order(symbol_in_position, amt)
                profits.append(round(profit, 2))
                send_message(f"{'💰' if profit > 0 else '⚠️'} بيع {symbol_in_position} | {round(profit,2)}%")
                break
        except: pass
        time.sleep(0.5)
    reset_trade()

def reset_trade():
    global symbol_in_position, entry_price
    symbol_in_position, entry_price = None, 0

# 🔄 متابعة السوق
def scanner():
    global last_top_update
    while True:
        if not is_running or symbol_in_position:
            time.sleep(1)
            continue
        if time.time() - last_top_update > 30:
            update_top_symbols()
            last_top_update = time.time()
        for m in top_symbols:
            if not is_running or symbol_in_position:
                break
            symbol = m["market"]
            start_socket(symbol)
            time.sleep(1)

# 🎮 أوامر التليغرام
@app.route("/webhook", methods=["POST"])
def webhook():
    global is_running
    data = request.json
    txt = data.get("message", {}).get("text", "").lower()
    if "stop" in txt:
        is_running = False
        send_message("⛔ إيقاف الشراء.")
    elif "play" in txt:
        is_running = True
        send_message("▶️ تم تفعيل الشراء.")
    elif "الملخص" in txt:
        if not profits:
            send_message("لا صفقات بعد.")
        else:
            win = [p for p in profits if p > 0]
            loss = [p for p in profits if p <= 0]
            total = sum(profits)
            send_message(f"""📊 ملخص Scalper الشمعة المتأرجحة:
صفقات: {len(profits)}
✅ أرباح: {len(win)}
❌ خسائر: {len(loss)}
📈 الربح الصافي: {round(total,2)}%""")
    return "", 200

# 🚀 تشغيل
if __name__ == "__main__":
    send_message("🐾 النمس - الشمعة المتأرجحة بدأ!")
    Thread(target=scanner).start()
    app.run(host="0.0.0.0", port=8080)