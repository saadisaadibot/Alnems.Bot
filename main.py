import os
import redis
import requests
import json
import time
import hmac
import hashlib
from flask import Flask, request
from threading import Thread

app = Flask(__name__)
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
REDIS_URL = os.getenv("REDIS_URL")
r = redis.from_url(REDIS_URL)
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 20))


def send_message(text):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})


def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()


def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, f"/v2{path}", body)
    headers = {
        'Bitvavo-Access-Key': BITVAVO_API_KEY,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Window': '10000'
    }
    try:
        response = requests.request(method, f"https://api.bitvavo.com/v2{path}", headers=headers, json=body or {})
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_price(symbol):
    try:
        url = f"https://api.bitvavo.com/v2/ticker/price?market={symbol}"
        res = requests.get(url)
        return float(res.json()["price"]) if res.status_code == 200 else None
    except:
        return None


def sell(symbol):
    if r.hexists("failed_sells", symbol):
        send_message(f"⚠️ تم تجاهل محاولة بيع مكررة لـ {symbol} بعد فشل سابق.")
        return

    coin = symbol.split("-")[0]
    balance = bitvavo_request("GET", "/balance")
    coin_balance = next((b['available'] for b in balance if b['symbol'] == coin), '0')
    if float(coin_balance) > 0:
        price = fetch_price(symbol)
        entry_raw = r.hget("entry", symbol)
        if not entry_raw or price is None:
            send_message(f"❌ لا يمكن حساب الربح لـ {symbol} (بيانات ناقصة)")
            return
        entry = float(entry_raw)
        amount = float(coin_balance)
        profit_eur = (price - entry) * amount
        percent = (price - entry) / entry * 100

        order_body = {
            "amount": str(amount),
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "operatorId": ""
        }
        result = bitvavo_request("POST", "/order", order_body)
        if "error" not in result:
            r.hset("orders", symbol, f"بيع | {round(profit_eur,2)} EUR | {round(percent,2)}%")
            r.hset("profits", symbol, json.dumps({
                "entry": entry,
                "exit": price,
                "profit": profit_eur,
                "percent": percent,
                "source": r.hget("source", symbol).decode() if r.hexists("source", symbol) else "manual"
            }))
            send_message(f"✅ بيع {symbol} تم بنجاح\n💰 ربح: {round(profit_eur,2)} EUR ({round(percent,2)}%)")
        else:
            send_message(f"❌ فشل البيع: {result['error']}")
            r.hset("failed_sells", symbol, "true")
    else:
        send_message(f"⚠️ لا يوجد رصيد كافٍ لبيع {symbol}")


def watch():
    while True:
        try:
            orders = r.hgetall("orders")
            for key, status in orders.items():
                symbol = key.decode()
                if "شراء" not in status.decode():
                    continue
                price = fetch_price(symbol)
                if price is None:
                    continue
                entry = r.hget("entry", symbol)
                if not entry:
                    continue
                entry = float(entry)
                peak = float(r.hget("peak", symbol) or entry)
                change = ((price - entry) / entry) * 100
                peak = max(peak, price)
                r.hset("peak", symbol, peak)
                drop = ((price - peak) / peak) * 100

                if change <= -2:
                    send_message(f"🛑 Stop Loss مفعل لـ {symbol}")
                    sell(symbol)

                elif change >= 3 and not r.hexists("alerts", f"{symbol}-peak"):
                    send_message(f"🚀 {symbol} تجاوز +3%! يراقب تراجع -1% من القمة.")
                    r.hset("alerts", f"{symbol}-peak", 1)

                elif change >= 3 and drop <= -1:
                    send_message(f"📉 تراجع -1% من القمة: {symbol}")
                    sell(symbol)
                    r.hdel("alerts", f"{symbol}-peak")

                elif change >= 3 and change < 1:
                    send_message(f"📉 تراجع من +3% إلى أقل من +1%: {symbol}")
                    sell(symbol)
                    r.hdel("alerts", f"{symbol}-peak")

        except Exception as e:
            print("❌ Error in watch:", str(e))
        time.sleep(1)


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return '', 200

    text = data["message"].get("text", "").strip().lower()

    if "الملخص" in text:
        records = r.hgetall("profits")
        total = 0
        sources = {}
        source_sums = {}
        for v in records.values():
            item = json.loads(v.decode())
            total += item["profit"]
            source = item.get("source", "manual")
            sources[source] = sources.get(source, 0) + 1
            source_sums[source] = source_sums.get(source, 0) + item["profit"]

        total_trades = sum(sources.values())
        percent_total = round((total / (BUY_AMOUNT_EUR * total_trades)) * 100, 2) if total_trades else 0
        msg = f"""📊 ملخص الأرباح:
إجمالي الربح: {round(total,2)} EUR ({percent_total}%)
""" + "\n".join([f"• {s.capitalize()}: {round(source_sums[s],2)} EUR من {sources[s]} صفقة" for s in sources])
        send_message(msg)

    elif "امسح الذاكرة" in text:
        r.flushall()
        send_message("🧹 تم مسح الذاكرة.")

    elif "الرصيد" in text:
        balance = bitvavo_request("GET", "/balance")
        try:
            eur = next((b['available'] for b in balance if b['symbol'] == 'EUR'), '0')
            send_message(f"💰 الرصيد المتاح: {eur} EUR")
        except:
            send_message("❌ فشل جلب الرصيد.")

    elif "اشتري" in text and "يا توتو" in text:
        try:
            parts = text.split()
            coin = parts[1].upper()
            symbol = coin + "-EUR"
            if r.hexists("entry", symbol):
                send_message(f"⚠️ تم شراء {symbol} مسبقًا، بانتظار البيع.")
                return '', 200

            if "ridder" in text:
                source = "ridder"
            elif "bottom" in text:
                source = "bottom"
            elif "sniper" in text:
                source = "sniper"
            else:
                source = "manual"

            balance = bitvavo_request("GET", "/balance")
            eur_balance = next((float(b['available']) for b in balance if b['symbol'] == 'EUR'), 0)

            if eur_balance < BUY_AMOUNT_EUR:
                send_message(f"🚫 لا يمكن شراء {symbol}، الرصيد غير كافٍ ({eur_balance:.2f} EUR).")
                return '', 200

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
                else:
                    send_message(f"❌ تم تنفيذ الشراء لكن لم نستطع تحديد السعر لـ {symbol}")
            else:
                send_message(f"❌ فشل الشراء: {result.get('error', 'غير معروف')}")
        except Exception as e:
            send_message(f"❌ خطأ في الشراء: {str(e)}")

    elif "بيع" in text and "يا توتو" in text:
        try:
            coin = text.split()[1].upper()
            symbol = coin + "-EUR"
            sell(symbol)
        except Exception as e:
            send_message(f"❌ خطأ في البيع: {str(e)}")

    return '', 200


@app.route("/")
def home():
    return "Toto Premium 🟢", 200


if __name__ == "__main__":
    send_message("🚀 Toto Premium بدأ العمل!")
    Thread(target=watch).start()
    app.run(host="0.0.0.0", port=8080)