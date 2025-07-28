import os, json, time, redis, requests, threading
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
IN_TRADE_KEY = "nems:in_trade"
IS_RUNNING_KEY = "scanner:enabled"
SETTINGS_KEY = "nems:ai_settings"
TRADES_KEY = "nems:trades"

def send(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text})
    except: pass

def fetch_price(symbol):
    try:
        return float(BITVAVO.tickerPrice({"market": symbol})["price"])
    except: return None

def get_candles(symbol, interval="1m", limit=20):
    try:
        return BITVAVO.candles(symbol, interval, {"limit": limit})
    except: return []

def get_rsi(candles, period=14):
    if len(candles) < period + 1: return 50
    gains, losses = [], []
    for i in range(-period, -1):
        diff = float(candles[i][4]) - float(candles[i - 1][4])
        if diff > 0: gains.append(diff)
        else: losses.append(abs(diff))
    avg_gain = sum(gains) / period or 0.0001
    avg_loss = sum(losses) / period or 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_volume_spike(candles, multiplier):
    if len(candles) < 6: return False
    avg_vol = sum(float(c[5]) for c in candles[:-1]) / (len(candles) - 1)
    return float(candles[-1][5]) > avg_vol * multiplier

def get_bullish_candle(prev, curr, min_change):
    open_, close_ = float(curr[1]), float(curr[4])
    prev_close = float(prev[4])
    change = (close_ - open_) / open_ * 100
    return close_ > open_ and close_ > prev_close and change >= min_change

def buy(symbol):
    return BITVAVO.placeOrder(symbol, {
        "side": "buy",
        "orderType": "market",
        "amount": str(BUY_AMOUNT_EUR)
    })

def sell(symbol, amount):
    return BITVAVO.placeOrder(symbol, {
        "side": "sell",
        "orderType": "market",
        "amount": str(amount)
    })

def load_settings():
    default = {"rsi_limit": 50, "volume_multiplier": 1.2, "min_change": 0.3}
    return json.loads(r.get(SETTINGS_KEY)) if r.exists(SETTINGS_KEY) else default

def save_settings(settings):
    r.set(SETTINGS_KEY, json.dumps(settings))

def save_trade(result):
    trades = json.loads(r.get(TRADES_KEY) or "[]")
    trades.append(result)
    if len(trades) > 30: trades = trades[-30:]
    r.set(TRADES_KEY, json.dumps(trades))

def learn():
    settings = load_settings()
    trades = json.loads(r.get(TRADES_KEY) or "[]")
    if len(trades) < 5: return  # لازم بيانات كافية

    wins = [t for t in trades if t["result"] == "ربح"]
    losses = [t for t in trades if t["result"] == "خسارة"]

    # اذا خسارات أكثر → نزيد الشروط
    if len(losses) > len(wins):
        settings["rsi_limit"] -= 1
        settings["volume_multiplier"] += 0.1
        settings["min_change"] += 0.1
    else:
        settings["rsi_limit"] += 1
        settings["volume_multiplier"] -= 0.1
        settings["min_change"] -= 0.1

    settings["rsi_limit"] = max(30, min(70, settings["rsi_limit"]))
    settings["volume_multiplier"] = max(1.0, min(3.0, settings["volume_multiplier"]))
    settings["min_change"] = max(0.1, min(2.0, settings["min_change"]))

    save_settings(settings)

def watch(symbol, entry_price, reason):
    max_price = entry_price
    while True:
        price = fetch_price(symbol)
        if not price: time.sleep(1); continue
        max_price = max(max_price, price)
        change = (price - entry_price) / entry_price * 100

        if change >= 1.5:
            result, percent = "ربح", change
            break
        elif change <= -1:
            result, percent = "خسارة", change
            break
        time.sleep(1)

    base = symbol.split("-")[0]
    amount = float(BITVAVO.balance(base)[0].get("available", 0))
    if amount > 0: sell(symbol, round(amount, 6))

    save_trade({"symbol": symbol, "entry": entry_price, "exit": price,
                "reason": reason, "result": result, "percent": round(percent, 2)})
    r.delete(IN_TRADE_KEY)
    learn()

def run_loop():
    r.set(IS_RUNNING_KEY, 1)
    while True:
        if r.get(IS_RUNNING_KEY) != b"1": time.sleep(5); continue
        if r.get(IN_TRADE_KEY): time.sleep(3); continue

        settings = load_settings()
        markets = BITVAVO.markets()
        eur_markets = [m["market"] for m in markets if m["quote"] == "EUR"]

        for symbol in eur_markets:
            candles = get_candles(symbol)
            if len(candles) < 15: continue
            rsi = get_rsi(candles)
            if rsi > settings["rsi_limit"]: continue
            if not get_volume_spike(candles, settings["volume_multiplier"]): continue
            if not get_bullish_candle(candles[-2], candles[-1], settings["min_change"]): continue

            price = fetch_price(symbol)
            if not price: continue
            r.set(IN_TRADE_KEY, symbol)
            send(f"🚀 صفقة جديدة: {symbol} RSI={int(rsi)}")
            buy(symbol)
            watch(symbol, price, f"RSI={int(rsi)}")
            break
        time.sleep(15)

@app.route("/", methods=["POST"])
def telegram_webhook():
    data = request.json
    text = data.get("message", {}).get("text", "").strip().lower()
    if text == "stop":
        r.set(IS_RUNNING_KEY, 0)
        send("⛔ تم إيقاف النمس.")
    elif text == "play":
        r.set(IS_RUNNING_KEY, 1)
        send("✅ تم تشغيل النمس.")
    elif text == "شو عم تعمل":
        status = r.get(IS_RUNNING_KEY)
        msg = "🟢 النمس يعمل." if status == b"1" else "⏸️ النمس موقوف."
        send(msg)
    elif text == "الملخص":
        trades = json.loads(r.get(TRADES_KEY) or "[]")
        if not trades:
            send("لا يوجد صفقات حتى الآن.")
        else:
            wins = sum(1 for t in trades if t["result"] == "ربح")
            losses = len(trades) - wins
            total_profit = sum(t["percent"] for t in trades)
            msg = f"📊 إجمالي الصفقات: {len(trades)}\n✅ ربح: {wins} | ❌ خسارة: {losses}\n💰 مجموع الربح: {round(total_profit, 2)}٪"
            send(msg)
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)