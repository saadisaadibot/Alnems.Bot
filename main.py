import os
import json
import time
import redis
import threading
import requests
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT = 10
IS_RUNNING_KEY = "scalper:running"
IS_IN_TRADE = "scalper:in_trade"
TRADE_HISTORY = "scalper:trades"

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except:
        pass

def get_price(symbol):
    try:
        res = BITVAVO.tickerPrice(symbol)
        if isinstance(res, str):
            res = json.loads(res)
        return float(res['price'])
    except:
        return None

def get_candles(symbol):
    try:
        url = f"https://api.bitvavo.com/v2/{symbol}/candles?interval=1m&limit=10"
        res = requests.get(url)
        if res.status_code != 200:
            return []
        return res.json()
    except:
        return []

def count_red_candles_from_end(candles):
    count = 0
    for c in reversed(candles):
        if float(c[4]) < float(c[1]):
            count += 1
        else:
            break
    return count

def get_top_1():
    try:
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)

        candidates = []
        for t in tickers:
            symbol = t.get("market", "")
            if not symbol.endswith("-EUR"):
                continue
            candles = get_candles(symbol)
            if len(candles) < 3:
                continue
            red_count = count_red_candles_from_end(candles)
            if red_count > 0:
                candidates.append((symbol, red_count))

        if not candidates:
            return None

        top = sorted(candidates, key=lambda x: x[1], reverse=True)[0]
        return top[0]
    except:
        return None

def analyze_and_buy():
    if r.get(IS_IN_TRADE) or r.get(IS_RUNNING_KEY) != b"1":
        return

    symbol = get_top_1()
    if not symbol:
        return

    try:
        base = symbol.split("-")[0]
        BITVAVO.placeOrder(symbol, "buy", "market", {
            "amount": str(BUY_AMOUNT)
        })
        r.set(IS_IN_TRADE, symbol, ex=300)
        send_message(f"✅ اشترينا {base} مباشرة بعد {symbol} (النمس 🐆)")
        threading.Thread(target=watch_sell, args=(symbol, get_price(symbol))).start()
    except Exception as e:
        print("❌ فشل في الشراء:", e)

def watch_sell(symbol, buy_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue

            change = (current - buy_price) / buy_price * 100
            if change >= 1.5 or change <= -0.5:
                break

        BITVAVO.placeOrder(symbol, "sell", "market", {
            "amount": str(BUY_AMOUNT)
        })
        r.delete(IS_IN_TRADE)
        base = symbol.split("-")[0]
        send_message(f"🚪 بيعنا {base} - النسبة: {round(change, 2)}%")
        save_trade_result(change)

        # فورًا نبدأ دورة جديدة
        time.sleep(1)
        analyze_and_buy()

    except Exception as e:
        print("❌ فشل في البيع:", e)
        r.delete(IS_IN_TRADE)

def save_trade_result(pct):
    try:
        result = {
            "pct": round(pct, 2),
            "eur": round(BUY_AMOUNT * pct / 100, 2),
            "ts": time.time()
        }
        r.rpush(TRADE_HISTORY, json.dumps(result))
    except:
        pass

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "").lower()
    if "stop" in msg:
        r.set(IS_RUNNING_KEY, "0")
        send_message("⛔ تم إيقاف عمليات الشراء.")
    elif "play" in msg:
        r.set(IS_RUNNING_KEY, "1")
        send_message("▶️ النمس بدأ - نسخة الأرجوحة السريعة!")
        analyze_and_buy()
    elif "الملخص" in msg:
        trades = r.lrange(TRADE_HISTORY, 0, -1)
        if not trades:
            send_message("لا توجد صفقات بعد.")
        else:
            total = 0
            summary = "📊 ملخص الصفقات:\n"
            for t in trades:
                data = json.loads(t.decode())
                pct = data["pct"]
                eur = data["eur"]
                total += eur
                emoji = "✅" if eur >= 0 else "❌"
                summary += f"{emoji} {pct}% ({eur} €)\n"
            summary += f"\n💰 الربح/الخسارة الكلي: {round(total,2)} €"
            send_message(summary)
    return "ok"

if __name__ == '__main__':
    r.set(IS_RUNNING_KEY, "1")
    analyze_and_buy()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))