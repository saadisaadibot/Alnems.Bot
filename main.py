import os, time, hmac, hashlib, json, requests
from flask import Flask, request

APIKEY = os.getenv("BITVAVO_API_KEY")
APISECRET = os.getenv("BITVAVO_API_SECRET")

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time()*1000))
    body_str = json.dumps(body, separators=(',',':')) if body else ''
    message = f"{timestamp}{method}{path}{body_str}"
    signature = hmac.new(APISECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    print("➡️ to sign:", message)
    print("🔑 signature:", signature)
    headers = {
        'Bitvavo-Access-Key': APIKEY,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }
    resp = requests.request(method, "https://api.bitvavo.com/v2"+path,
                             headers=headers, data=body_str or None)
    print("◀️ response:", resp.status_code, resp.text)
    return resp.json()

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    text = data.get("message",{}).get("text","")
    chat = data.get("message",{}).get("chat",{}).get("id")
    if not chat:
        return "",200
    if text == "/balance":
        result = bitvavo_request("GET", "/balance")
        requests.post(f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendMessage",
                      data={"chat_id": chat, "text": json.dumps(result)})
    elif text.startswith("buy"):
        # مثال شراء ADA-EUR
        body = {"market":"ADA-EUR","side":"buy","orderType":"market","amount":"10"}
        result = bitvavo_request("POST","/order", body)
        requests.post(f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendMessage",
                      data={"chat_id": chat, "text": json.dumps(result)})
    elif text.startswith("sell"):
        body = {"market":"ADA-EUR","side":"sell","orderType":"market","amount":"10"}
        result = bitvavo_request("POST","/order", body)
        requests.post(f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendMessage",
                      data={"chat_id": chat, "text": json.dumps(result)})
    return "",200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)