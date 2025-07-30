import os
import json
import time
import hmac
import hashlib
import requests

# جلب المفاتيح من البيئة
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    message = timestamp + method + path + body_str
    signature = hmac.new(BITVAVO_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        'Bitvavo-Access-Key': BITVAVO_API_KEY,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }

    url = "https://api.bitvavo.com/v2" + path
    return requests.request(method, url, headers=headers, data=body_str).json()

# اختبار المفاتيح بطلب الرصيد
print("🔐 فحص المفاتيح ...")
response = bitvavo_request("GET", "/balance")

print("📦 الرد الكامل:")
print(json.dumps(response, indent=2))