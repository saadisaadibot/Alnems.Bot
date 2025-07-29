import requests
import os
import redis
import numpy as np

BITVAVO_REST_URL = "https://api.bitvavo.com/v2"

def fetch_price(symbol):
    try:
        res = requests.get(f"{BITVAVO_REST_URL}/ticker/price?market={symbol}")
        return float(res.json()["price"])
    except:
        return None

def get_candles(symbol, interval="1m", limit=15):
    try:
        url = f"{BITVAVO_REST_URL}/{symbol}/candles?interval={interval}&limit={limit}"
        res = requests.get(url)
        return res.json()
    except:
        return []

def calculate_rsi(candles, period=14):
    closes = [float(c[4]) for c in candles]
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed > 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down else 0
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)