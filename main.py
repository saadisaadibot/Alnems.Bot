import os
import json
import redis
import requests
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")

bitvavo = Bitvavo({
    'APIKEY': BITVAVO_API_KEY,
    'APISECRET': BITVAVO_API_SECRET,
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

SYMBOL = "ADA-EUR"  # يمكن تغييره لاحقاً
POSITION_KEY = "nems_position"

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except:
        pass

@app.route('/', methods=['POST'])
def webhook():
    data = request.json
    text = data.get("message", {}).get("text", "").strip()

    if "اشتري يا نمس" in text:
        return buy()

    elif "بيع يا نمس" in text:
        return sell()

    return "ok"

def buy():
    if r.get(POSITION_KEY):
        send_message("🚫 في صفقة مفتوحة حالياً.")
        return "already open", 200

    try:
        price = float(bitvavo.tickerPrice({ 'market': SYMBOL })['price'])
        quantity = round(BUY_AMOUNT_EUR / price, 2)

        response = bitvavo.placeOrder(SYMBOL, {
            'side': 'buy',
            'orderType': 'market',
            'amount': str(quantity)
        })

        r.set(POSITION_KEY, json.dumps({
            "symbol": SYMBOL,
            "buy_price": price
        }))

        send_message(f"✅ اشترى النمس {SYMBOL.split('-')[0]} بسعر {price:.4f}")
        return "bought", 200

    except Exception as e:
        send_message(f"❌ فشل الشراء: {e}")
        return "error", 500

def sell():
    position = r.get(POSITION_KEY)
    if not position:
        send_message("🚫 لا يوجد صفقة مفتوحة حالياً.")
        return "no open trade", 200

    try:
        position = json.loads(position)
        symbol = position["symbol"]

        balance = bitvavo.balance(symbol.split("-")[0])
        quantity = float(balance[0].get("available", 0))
        if quantity == 0:
            send_message("🚫 لا يوجد رصيد للبيع.")
            return "no balance", 200

        response = bitvavo.placeOrder(symbol, {
            'side': 'sell',
            'orderType': 'market',
            'amount': str(quantity)
        })

        r.delete(POSITION_KEY)
        send_message(f"✅ باع النمس {symbol.split('-')[0]} بنجاح.")
        return "sold", 200

    except Exception as e:
        send_message(f"❌ فشل البيع: {e}")
        return "error", 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)