import os, time, threading
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo
import requests

# 🟢 إعداد البيئة
app = Flask(__name__)
BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT = float(os.getenv("BUY_AMOUNT_EUR", 10))

# 🔁 الحالة
is_running = True
symbol_in_position = None
entry_price = 0
profits = []
monitored_symbols = []  # 🟡 العملات التي تتم مراقبتها

# 📨 تيليغرام
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID, "text": text
        })
    except:
        pass

# 📦 بيع وشراء
def buy(symbol):
    return BITVAVO.placeOrder({
        'market': symbol,
        'side': 'buy',
        'orderType': 'market',
        'amountQuote': str(BUY_AMOUNT)
    })

def sell(symbol, amount):
    return BITVAVO.placeOrder({
        'market': symbol,
        'side': 'sell',
        'orderType': 'market',
        'amount': str(amount)
    })

# 📊 الشمعة المتأرجحة
def watch_symbols():
    def analyze(symbol):
        global symbol_in_position, entry_price

        def callback(msg):
            nonlocal symbol
            if not is_running or symbol_in_position:
                return

            try:
                price = float(msg['price'])
                candles = BITVAVO.candles(symbol, {'interval': '1m', 'limit': 3})
                if len(candles) < 3: return
                c1, c2, c3 = [float(c[4]) for c in candles[-3:]]

                # استراتيجية الشمعة المتأرجحة:
                if c3 > c2 and c2 < c1 and price <= c2 * 1.01:
                    res = buy(symbol)
                    filled_price = float(res.get("fills", [{}])[0].get("price", 0))
                    if filled_price:
                        symbol_in_position = symbol
                        entry_price = filled_price
                        send_message(f"✅ النمس دخل {symbol} بسعر {filled_price} EUR")
                        threading.Thread(target=track_sell, args=(symbol,)).start()
            except Exception as e:
                print("❌ تحليل:", e)

        try:
            monitored_symbols.append(symbol)
            BITVAVO.websocket.ticker(symbol, callback)
        except Exception as e:
            print(f"❌ WebSocket فشل {symbol}:", e)

    markets = BITVAVO.markets()
    top = sorted(
        [m for m in markets if m['quote'] == 'EUR'],
        key=lambda x: float(x.get("volume", 0)),
        reverse=True
    )[:30]

    for m in top:
        threading.Thread(target=analyze, args=(m['market'],)).start()

# 💰 تتبع البيع
def track_sell(symbol):
    global symbol_in_position, entry_price
    try:
        while True:
            book = BITVAVO.book(symbol)
            price = float(book["asks"][0][0])
            profit = (price - entry_price) / entry_price * 100

            if profit >= 1 or profit <= -0.5:
                coin = symbol.split("-")[0]
                balance = BITVAVO.balance(coin)
                amount = float(balance["available"])
                sell(symbol, amount)
                send_message(f"{'💰' if profit > 0 else '⚠️'} بيع {symbol} بنسبة {round(profit, 2)}%")
                profits.append(round(profit, 2))
                symbol_in_position = None
                entry_price = 0
                break
            time.sleep(0.5)
    except Exception as e:
        print("⚠️ تتبع البيع:", e)

# 🧠 الأوامر
@app.route("/webhook", methods=["POST"])
def webhook():
    global is_running
    data = request.json
    text = data.get("message", {}).get("text", "").lower()

    if "play" in text:
        is_running = True
        send_message("▶️ تم تفعيل النمس.")
    elif "stop" in text:
        is_running = False
        send_message("⛔ تم إيقاف النمس مؤقتًا.")
    elif "الملخص" in text:
        if not profits:
            send_message("لا توجد صفقات بعد.")
        else:
            win = [p for p in profits if p > 0]
            loss = [p for p in profits if p <= 0]
            total = sum(profits)
            msg = f"""📊 ملخص النمس:
صفقات: {len(profits)}
✅ أرباح: {len(win)}
❌ خسائر: {len(loss)}
📈 صافي الربح: {round(total, 2)}%
"""
            send_message(msg)
    elif "شو عم تعمل" in text:
        msg = "📡 العملات قيد المراقبة:\n"
        if symbol_in_position:
            msg += f"🟢 دخول حالي: {symbol_in_position} بسعر {entry_price}\n"
        if not monitored_symbols:
            msg += "لا توجد عملات تحت المراقبة حالياً."
        else:
            msg += "\n".join([f"🔸 {s}" for s in monitored_symbols])
        send_message(msg)

    return "", 200

# 🚀 بدء
if __name__ == "__main__":
    send_message("🐾 النمس بدأ - الشمعة المتأرجحة™")
    threading.Thread(target=watch_symbols).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)