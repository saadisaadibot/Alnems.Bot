import os
import json
import time
import hmac
import hashlib
import requests
import uuid

# إعداد المفاتيح من البيئة
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")

def create_signature(timestamp, method, path, body_str):
    message = f"{timestamp}{method}/v2{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    signature = create_signature(timestamp, method, path, body_str)

    headers = {
        'Bitvavo-Access-Key': BITVAVO_API_KEY,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }

    url = "https://api.bitvavo.com/v2" + path
    response = requests.request(method, url, headers=headers, data=body_str)
    try:
        return response.json()
    except:
        return {"error": "Invalid JSON", "text": response.text}

# اقرأ الرصيد
print("🐷 الرصيد:")
print(bitvavo_request("GET", "/balance"))

# اشتري ADA بقيمة 10 يورو
print("\n🟢 شراء ADA:")
operator_id = str(uuid.uuid4())[:12]
buy_response = bitvavo_request("POST", "/order", {
    "market": "ADA-EUR",
    "side": "buy",
    "orderType": "market",
    "amountQuote": "10",
    "operatorId": operator_id
})
print(buy_response)

# انتظر 5 ثواني
time.sleep(5)

# احصل على الكمية المشتراة
balance = bitvavo_request("GET", "/balance")
ada = next((item for item in balance if item["symbol"] == "ADA"), None)
ada_amount = ada["available"] if ada else "0"

# بيع ADA إذا وُجدت كمية
if float(ada_amount) > 0:
    print("\n🔴 بيع ADA:")
    operator_id = str(uuid.uuid4())[:12]
    sell_response = bitvavo_request("POST", "/order", {
        "market": "ADA-EUR",
        "side": "sell",
        "orderType": "market",
        "amount": ada_amount,
        "operatorId": operator_id
    })
    print(sell_response)
else:
    print("\n⚠️ لا توجد كمية ADA متاحة للبيع.")