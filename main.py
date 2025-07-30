import os
import json
import time
import hmac
import hashlib
import uuid
import requests

# إعداد المفاتيح من بيئة Railway
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")

BASE_URL = "https://api.bitvavo.com/v2"

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    message = f"{timestamp}{method}{path}{body_str}"
    signature = hmac.new(BITVAVO_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        'Bitvavo-Access-Key': BITVAVO_API_KEY,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }

    url = BASE_URL + path
    response = requests.request(method, url, headers=headers, data=body_str)
    return response.json()


# ✅ 1. قراءة الرصيد
print("🐷 الرصيد:")
balance = bitvavo_request("GET", "/balance")
print(balance)

# ✅ 2. شراء ADA بـ 10 يورو
print("\n🟢 شراء ADA:")
buy_order = {
    "market": "ADA-EUR",
    "side": "buy",
    "orderType": "market",
    "amountQuote": "10",
    "operatorId": str(uuid.uuid4())  # توليد operatorId صالح
}
buy_response = bitvavo_request("POST", "/order", buy_order)
print(buy_response)

# ✅ 3. محاولة بيع كل ADA إذا متوفرة
print("\n⚠️ محاولة بيع ADA:")
ada_balance = next((item for item in balance if item["symbol"] == "ADA"), None)
if ada_balance and float(ada_balance["available"]) > 0:
    sell_order = {
        "market": "ADA-EUR",
        "side": "sell",
        "orderType": "market",
        "amount": ada_balance["available"],
        "operatorId": str(uuid.uuid4())
    }
    sell_response = bitvavo_request("POST", "/order", sell_order)
    print(sell_response)
else:
    print("⚠️ لا توجد كمية ADA متاحة للبيع.")