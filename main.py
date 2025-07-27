import os, time, json, hmac, hashlib, requests
from flask import Flask, request
from threading import Thread

app = Flask(__name__)

# مفاتيح البيئة
API_KEY = os.getenv("SCALPER_API_KEY")
API_SECRET = os.getenv("SCALPER_API_SECRET")
BUY_AMOUNT_EUR = float(os.getenv("SCALPER_BUY_AMOUNT", 10))
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bitvavo_url = "https://api.bitvavo.com/v2"

# حالة التشغيل
is_running = True
symbol_in_position = None
entry_price = 0
position_active = False
profits = []

# توقيع الطلبات
def headers(t, method, path, body):
    msg = f"{t}{method}{path}{body}"
    return {
        "Bitvavo-Access-Key": API_KEY,
        "Bitvavo-Access-Timestamp": t,
        "Bitvavo-Access-Signature": hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest(),
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }

# إرسال طلب
def bitvavo_request(method, path, body=None):
    t = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    h = headers(t, method, path, body_str)
    r = requests.request(method, bitvavo_url + path, headers=h, data=body_str)
    return r.json()

# تيليغرام
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# بيع
def sell_order(symbol, amount):
    return bitvavo_request("POST", f"/order", {
        "market": symbol,
        "amount": str(amount),
        "side": "sell",
        "orderType": "market"
    })

# شراء
def buy_order(symbol):
    return bitvavo_request("POST", f"/order", {
        "market": symbol,
        "amountQuote": str(BUY_AMOUNT_EUR),
        "side": "buy",
        "orderType": "market"
    })

# الشموع
def get_candles(symbol, interval="1m", limit=4):
    return bitvavo_request("GET", f"/{symbol}/candles", {"interval": interval, "limit": limit})

# الأسواق
def get_markets():
    return [m["market"] for m in bitvavo_request("GET", "/markets") if m["quote"] == "EUR"]

# اختيار ودخول الصفقة
def analyze_and_buy():
    global symbol_in_position, entry_price, position_active, is_running
    while True:
        if position_active or not is_running:
            time.sleep(1)
            continue
        try:
            for symbol in get_markets():
                candles = get_candles(symbol)
                if len(candles) < 4:
                    continue
                prices = [float(c[4]) for c in candles]
                bodies = [abs(float(c[4]) - float(c[1])) for c in candles]
                ranges = [abs(float(c[2]) - float(c[3])) for c in candles]
                if prices[-1] > max(prices[:-1]) and bodies[-1] > 0.5 * ranges[-1]:
                    res = buy_order(symbol)
                    price = float(res.get("fills", [{}])[0].get("price", 0))
                    if price > 0:
                        symbol_in_position = symbol
                        entry_price = price
                        position_active = True
                        send_message(f"✅ النمس اشترى {symbol} بسعر {price} EUR")
                        Thread(target=monitor_position).start()
                        break
        except Exception as e:
            print("❌", e)
        time.sleep(1)

# مراقبة الصفقة
def monitor_position():
    global symbol_in_position, entry_price, position_active
    while position_active:
        try:
            book = bitvavo_request("GET", f"/{symbol_in_position}/book")
            price = float(book.get("asks", [[0]])[0][0])
            profit = (price - entry_price) / entry_price * 100
            if profit >= 1 or profit <= -0.5:
                coin = symbol_in_position.split("-")[0]
                amount = float(bitvavo_request("GET", f"/balance/{coin}")["available"])
                sell_order(symbol_in_position, amount)
                send_message(f"{'💰' if profit > 0 else '⚠️'} النمس باع {symbol_in_position} بربح {round(profit,2)}%")
                profits.append(round(profit, 2))
                symbol_in_position = None
                entry_price = 0
                position_active = False
                break
        except Exception as e:
            print("⚠️", e)
        time.sleep(0.5)

# أوامر تيليغرام
@app.route("/", methods=["POST"])
def webhook():
    global is_running
    data = request.json
    msg = data.get("message", {})
    text = msg.get("text", "")
    if not text:
        return "", 200
    if "stop" in text:
        is_running = False
        send_message("⛔ تم إيقاف الشراء مؤقتًا.")
    elif "play" in text:
        is_running = True
        send_message("▶️ تم تفعيل الشراء.")
    elif "الملخص" in text:
        if not profits:
            send_message("لا توجد صفقات بعد.")
        else:
            win = [p for p in profits if p > 0]
            loss = [p for p in profits if p <= 0]
            total = sum(profits)
            msg = f"""📊 ملخص Scalper النمس:
الصفقات: {len(profits)}
✅ أرباح: {len(win)} صفقة
❌ خسائر: {len(loss)} صفقة
📈 الربح الصافي: {round(total,2)}%
"""
            send_message(msg)
    return "", 200

# تشغيل
if __name__ == "__main__":
    send_message("🐾 النمس بدأ العمل!")
    Thread(target=analyze_and_buy).start()
    app.run(host="0.0.0.0", port=8080)