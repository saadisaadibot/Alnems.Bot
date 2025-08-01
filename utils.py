import os
import requests
import time
import hmac
import hashlib
import json
import numpy as np

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BASE_URL = "https://api.bitvavo.com/v2"

# ✅ توقيع صحيح حسب Bitvavo
def create_signature(timestamp, method, path, body):
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body else ''
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(BITVAVO_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

# ✅ الطلب العام لـ Bitvavo
def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body else ''
    signature = create_signature(timestamp, method, path, body)

    headers = {
        'Bitvavo-Access-Key': BITVAVO_API_KEY,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }

    url = BASE_URL + path
    try:
        response = requests.request(method, url, headers=headers, data=body_str)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# ✅ جلب الشموع
def get_candles(symbol, interval="1m", limit=60):
    url = f"{BASE_URL}/{symbol}/candles?interval={interval}&limit={limit}"
    try:
        response = requests.get(url)
        return response.json()
    except:
        return []

# ✅ حساب RSI
def calculate_rsi(candles, period=14):
    closes = [float(c[4]) for c in candles]
    if len(closes) < period + 1:
        return 50
    deltas = np.diff(closes)
    ups = deltas[deltas > 0].sum() / period
    downs = -deltas[deltas < 0].sum() / period
    rs = ups / downs if downs != 0 else 0
    return 100 - (100 / (1 + rs))