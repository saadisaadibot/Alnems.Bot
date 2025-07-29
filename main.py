import os, time, json, requests, hmac, hashlib
import redis
from flask import Flask, request

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("BITVAVO_API_KEY")
API_SECRET = os.getenv("BITVAVO_API_SECRET")
BUY_AMOUNT = float(os.getenv("BUY_AMOUNT_EUR", 5))

def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("❌ فشل الإرسال:", e)

def create_signature(timestamp, method, path, body, secret):
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body else ""
    message = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, path, body or {}, API_SECRET)
    headers = {
        "Bitvavo-Access-Key": API_KEY,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Signature": signature,
        "Content-Type": "application/json"
    }
    url = f"https://api.bitvavo.com/v2{path}"
    response = requests.request(method, url, headers=headers, json=body or {})
    return response.json()

@app.route("/webhook", methods=["POST"])
def telegram():
    data = request.json
    msg = data.get("message", {}).get("text", "")
    if not msg:
        return "", 200

    if "/balance" in msg:
        balances = bitvavo_request("GET", "/balance")
        text = ""
        for b in balances:
            asset = b["symbol"] if "symbol" in b else b["currency"]
            available = float(b["available"])
            if available > 0:
                text += f"{asset}: {available}\n"
        send("💰 الرصيد:\n" + (text or "لا يوجد رصيد."))

    elif "/buy_ada" in msg:
        price_info = requests.get("https://api.bitvavo.com/v2/ticker/price?market=ADA-EUR").json()
        price = float(price_info.get("price", 0))
        amount = round(BUY_AMOUNT / price, 6)
        body = {
            "market": "ADA-EUR",
            "side": "buy",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""
        }
        res = bitvavo_request("POST", "/order", body)
        send(f"✅ أمر شراء ADA:\n{json.dumps(res, indent=2)}")

    elif "/sell_ada" in msg:
        balances = bitvavo_request("GET", "/balance")
        ada_balance = next((b["available"] for b in balances if b["symbol"] == "ADA"), "0")
        body = {
            "market": "ADA-EUR",
            "side": "sell",
            "orderType": "market",
            "amount": ada_balance,
            "operatorId": ""
        }
        res = bitvavo_request("POST", "/order", body)
        send(f"✅ أمر بيع ADA:\n{json.dumps(res, indent=2)}")

    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)