import os
import time
import hmac
import hashlib
import json
import requests

# تحميل المفاتيح من environment
BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BASE_URL = "https://api.bitvavo.com/v2"

def bitvavo_signed_get(path):
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    body = ""
    message = f"{timestamp}{method}{path}{body}"
    signature = hmac.new(BITVAVO_API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        "Bitvavo-Access-Key": BITVAVO_API_KEY,
        "Bitvavo-Access-Signature": signature,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Window": "10000"
    }

    url = BASE_URL + path
    response = requests.get(url, headers=headers)
    return response.status_code, response.json()

if __name__ == "__main__":
    print("🧪 فحص المفاتيح ...")
    print("🔑 KEY:", BITVAVO_API_KEY[:6], "...")

    status, result = bitvavo_signed_get("/account")

    print(f"\n📡 Status Code: {status}")
    print("📦 الرد الكامل:\n", json.dumps(result, indent=2, ensure_ascii=False))