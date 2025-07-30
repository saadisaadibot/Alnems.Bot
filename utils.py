import requests
import numpy as np
import time
import hmac
import hashlib
import json
import os

def get_candles(symbol, interval="15m", limit=20):
    url = f"https://api.bitvavo.com/v2/{symbol}/candles?interval={interval}&limit={limit}"
    try:
        response = requests.get(url)
        return response.json()
    except:
        return []

def calculate_rsi(candles, period=14):
    closes = [float(c[4]) for c in candles]
    if len(closes) < period + 1:
        return 50
    deltas = np.diff(closes)
    ups = deltas[deltas > 0].sum() / period
    downs = -deltas[deltas < 0].sum() / period
    rs = ups / downs if downs != 0 else 0
    return 100 - (100 / (1 + rs))

def create_signature(timestamp, method, path, body, secret):
    body_str = "" if body is None else json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

import hmac
import hashlib
import time
import json
import requests
import os

BITVAVO_API_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_API_SECRET = os.getenv("BITVAVO_API_SECRET")
BASE_URL = "https://api.bitvavo.com/v2"

def bitvavo_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(',', ':')) if body else ''
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