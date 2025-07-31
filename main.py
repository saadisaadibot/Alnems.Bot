import os
import time
import hmac
import json
import hashlib
import requests

# ضع المفاتيح مباشرة أو استخدم متغيرات بيئة
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY") or "حط_المفتاح_هون"
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET") or "حط_السر_هون"

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    signature = hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

    headers = {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000",
        "Content-Type": "application/json"
    }

    url = "https://api.bitvavo.com/v2" + path

    if method == "GET":
        response = requests.get(url, headers=headers)
    else:
        response = requests.post(url, headers=headers, data=body_str.encode("utf-8"))

    try:
        return response.json()
    except Exception as e:
        return {"error": f"Failed to decode JSON: {e}", "raw": response.text}

# 🧪 جرب الآن استعلام الرصيد
result = bitvavo_request("GET", "/balance")
print("✅ رد Bitvavo:\n", json.dumps(result, indent=2, ensure_ascii=False))