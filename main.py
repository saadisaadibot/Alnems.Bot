import time
from market_scanner import pick_best_symbol
from memory import save_trade
from bitvavo_client.bitvavo import Bitvavo
import os
import redis

r = redis.from_url(os.getenv("REDIS_URL"))

bitvavo = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
IN_TRADE_KEY = "nems:in_trade"

def fetch_price(symbol):
    try:
        price = bitvavo.tickerPrice({"market": symbol})
        return float(price["price"])
    except:
        return None

def buy(symbol):
    response = bitvavo.placeOrder(symbol, {
        "side": "buy",
        "orderType": "market",
        "amount": str(BUY_AMOUNT_EUR)
    })
    return response

def sell(symbol, amount):
    response = bitvavo.placeOrder(symbol, {
        "side": "sell",
        "orderType": "market",
        "amount": str(amount)
    })
    return response

def watch(symbol, entry_price, reason):
    max_price = entry_price
    while True:
        price = fetch_price(symbol)
        if not price:
            time.sleep(1)
            continue

        max_price = max(max_price, price)
        change = (price - entry_price) / entry_price * 100

        if change >= 1.5:
            result = "ربح"
            percent = change
            break
        elif change <= -1:
            result = "خسارة"
            percent = change
            break

        time.sleep(1)

    # بيع العملة
    balances = bitvavo.balance(symbol.split("-")[0])
    amount = float(balances[0].get("available", 0))
    if amount > 0:
        sell(symbol, round(amount, 6))

    save_trade(symbol, entry_price, price, reason, result, percent)
    r.delete(IN_TRADE_KEY)

def run_loop():
    while True:
        if r.get(IN_TRADE_KEY):
            time.sleep(3)
            continue

        symbol, reason, score = pick_best_symbol()
        if score < 1:
            print("❌ لا يوجد فرصة قوية حالياً.")
            time.sleep(30)
            continue

        print(f"✅ فرصة على {symbol} | {reason} | Score={score}")
        price = fetch_price(symbol)
        if not price:
            time.sleep(5)
            continue

        r.set(IN_TRADE_KEY, symbol)
        buy(symbol)
        watch(symbol, price, reason)

if __name__ == "__main__":
    run_loop()