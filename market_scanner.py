import time
import json
import redis
import os  # <–– هذا هو اللي ناقص
from bitvavo_client.bitvavo import Bitvavo
from indicators import get_rsi, get_volume_spike, get_bullish_candle

r = redis.from_url(os.getenv("REDIS_URL"))
bitvavo = Bitvavo({
    'APIKEY': 'YOUR_API_KEY',
    'APISECRET': 'YOUR_API_SECRET',
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

def get_symbols():
    try:
        raw = bitvavo.markets()
        markets = json.loads(raw) if isinstance(raw, str) else raw
        return [m['market'] for m in markets if isinstance(m, dict) and m.get('quote') == 'EUR']
    except Exception as e:
        print("❌ فشل جلب الرموز:", e)
        return []

def fetch_candles(symbol):
    try:
        candles = bitvavo.candles(symbol, '1m', {'limit': 20})
        return candles
    except:
        return []

def score_symbol(symbol, weights):
    candles = fetch_candles(symbol)
    if len(candles) < 6:
        return 0, "لا يكفي شموع"

    signals = []

    # شرط 1: شمعة انعكاسية صاعدة
    if get_bullish_candle(candles[-2], candles[-1]):
        signals.append("شمعة انعكاسية")

    # شرط 2: RSI منخفض
    rsi = get_rsi(candles)
    if rsi < 35:
        signals.append(f"RSI={int(rsi)}")

    # شرط 3: فوليوم مفاجئ
    if get_volume_spike(candles):
        signals.append("فوليوم مرتفع")

    score = sum(weights.get(s, 0) for s in signals)

    reason = " + ".join(signals) if signals else "لا إشارات"

    return score, reason

def pick_best_symbol():
    symbols = get_symbols()[:50]
    weights = json.loads(r.get("nems:weights") or "{}")

    best_symbol = None
    best_score = -999
    best_reason = ""

    for symbol in symbols:
        score, reason = score_symbol(symbol, weights)
        if score > best_score:
            best_score = score
            best_symbol = symbol
            best_reason = reason

    return best_symbol, best_reason, best_score
