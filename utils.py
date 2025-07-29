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
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    msg = f"{timestamp}{method}{path}{body_str}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

def bitvavo_request(method, path, body):
    api_key = os.getenv("BITVAVO_API_KEY")
    api_secret = os.getenv("BITVAVO_API_SECRET")
    timestamp = str(int(time.time() * 1000))
    signature = create_signature(timestamp, method, path, body, api_secret)
    headers = {
        "Bitvavo-Access-Key": api_key,
        "Bitvavo-Access-Timestamp": timestamp,
        "Bitvavo-Access-Signature": signature,
        "Content-Type": "application/json"
    }
    url = f"https://api.bitvavo.com/v2{path}"
    resp = requests.request(method, url, headers=headers, json=body)
    return resp.json()