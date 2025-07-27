import os, time, json, hmac, hashlib, requests
from flask import Flask, request
from threading import Thread

app = Flask(__name__)

# 🟢 المفاتيح من البيئة
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bitvavo_url = "https://api.bitvavo.com/v2"

if not all([BITVAVO_API_KEY, BITVAVO_API_SECRET, BOT_TOKEN, CHAT_ID]):
    raise ValueError("❌ تأكد من إعداد جميع المفاتيح.")

# 🔄 الحالة العامة
is_running = True
symbol_in_position = None
entry_price = 0
position_active = False
profits = []
top_symbols = []
last_update = 0

# توليد الهيدر
def headers(t, method, path, body):
    msg = f"{t}{method}{path}{body}"
    return {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Timestamp": t,
        "Bitvavo-Access-Signature": hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest(),
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }

# طلب API
def bitvavo_request(method, path, body=None):
    t = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    h = headers(t, method, path, body_str)
    r = requests.request(method, bitvavo_url + path, headers=h, data=body_str)
    try:
        return r.json()
    except:
        print("⚠️ رد غير صالح:", r.text)
        return {}

# تيليغرام
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

# بيع وشراء
def sell_order(symbol, amount):
    return bitvavo_request("POST", "/order", {
        "market": symbol,
        "amount": str(amount),
        "side": "sell",
        "orderType": "market"
    })

def buy_order(symbol):
    return bitvavo_request("POST", "/order", {
        "market": symbol,
        "amountQuote": str(BUY_AMOUNT_EUR),
        "side": "buy",
        "orderType": "market"
    })

# بيانات السوق
def get_candles(symbol, interval="1m", limit=20):
    return bitvavo_request("GET", f"/{symbol}/candles", {"interval": interval, "limit": limit})

def get_markets():
    return bitvavo_request("GET", "/markets")

# تحديث قائمة Top 30 حسب الحجم
def update_top_symbols():
    global top_symbols
    try:
        markets = get_markets()
        filtered = [
            m for m in markets if isinstance(m, dict)
            and m.get("quote") == "EUR"
            and float(m.get("volume", 0)) > 0
        ]
        top_symbols = sorted(filtered, key=lambda x: float(x.get("volume", 0)), reverse=True)[:30]
    except Exception as e:
        print("❌ تحديث العملات النشيطة:", e)

# تحليل العملات والدخول
def analyze_and_buy():
    global symbol_in_position, entry_price, position_active, is_running, top_symbols, last_update

    while True:
        if not is_running or position_active:
            time.sleep(1)
            continue

        if time.time() - last_update > 30:
            update_top_symbols()
            last_update = time.time()

        try:
            for market in top_symbols:
                symbol = market["market"]
                candles = get_candles(symbol)
                if not isinstance(candles, list) or len(candles) < 20:
                    continue

                closes = [float(c[4]) for c in candles]
                ma = sum(closes) / len(closes)
                std = (sum([(p - ma) ** 2 for p in closes]) / len(closes)) ** 0.5
                upper = ma + 2 * std
                lower = ma - 2 * std
                current = closes[-1]

                # دخول مرن + شرط الشمعة الصاعدة
                if current <= lower * 1.02 and closes[-1] > closes[-2] * 1.003:
                    res = buy_order(symbol)
                    fills = res.get("fills", [{}])
                    price = float(fills[0].get("price", 0)) if fills else 0
                    if price > 0:
                        symbol_in_position = symbol
                        entry_price = price
                        position_active = True
                        send_message(f"✅ الأرجوحة السريعة: شراء {symbol} عند {price} EUR")
                        Thread(target=monitor_position_bollinger, args=(upper,)).start()
                        break
        except Exception as e:
            print("❌", e)
        time.sleep(3)  # فحص كل 3 ثواني فقط

# مراقبة الصفقة
def monitor_position_bollinger(upper_band):
    global symbol_in_position, entry_price, position_active
    while position_active:
        try:
            book = bitvavo_request("GET", f"/{symbol_in_position}/book")
            price = float(book.get("asks", [[0]])[0][0])
            profit = (price - entry_price) / entry_price * 100

            if price >= upper_band or profit >= 1 or profit <= -0.5:
                coin = symbol_in_position.split("-")[0]
                bal = bitvavo_request("GET", f"/balance/{coin}")
                amount = float(bal.get("available", 0))
                sell_order(symbol_in_position, amount)
                send_message(f"{'💰' if profit > 0 else '⚠️'} بيع {symbol_in_position} | ربح {round(profit,2)}%")
                profits.append(round(profit, 2))
                symbol_in_position = None
                entry_price = 0
                position_active = False
                break
        except Exception as e:
            print("⚠️", e)
        time.sleep(0.5)

# أوامر تيليغرام
@app.route("/webhook", methods=["POST"])
def webhook():
    global is_running
    data = request.json
    msg = data.get("message", {})
    text = msg.get("text", "").lower()
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
            msg = f"""📊 ملخص Scalper الأرجوحة السريعة:
الصفقات: {len(profits)}
✅ أرباح: {len(win)} صفقة
❌ خسائر: {len(loss)} صفقة
📈 الربح الصافي: {round(total,2)}%
"""
            send_message(msg)
    return "", 200

# تشغيل
if __name__ == "__main__":
    send_message("🐾 النمس بدأ - الأرجوحة السريعة!")
    Thread(target=analyze_and_buy).start()
    app.run(host="0.0.0.0", port=8080)