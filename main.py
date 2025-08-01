import os
import time
import redis
import json
import threading
import requests
from utils import bitvavo_request
from market_scanner import pick_best_symbol
from memory import save_trade
from dotenv import load_dotenv

load_dotenv()
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))  # 👈 تأكدنا إنها string
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

IS_TRADING_KEY = "nems:is_in_trade"
LAST_TRADE_KEY = "nems:last_trade"

def send_message(text):
    print(">>", text)
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except Exception as e:
        print("Telegram error:", e)

def get_balance():
    balances = bitvavo_request("GET", "/balance")
    output = []
    for b in balances:
        available = float(b.get("available", 0))
        if available > 0.01:
            output.append(f"{b['symbol']}: {available:.2f}")
    return "\n".join(output) if output else "لا يوجد رصيد كافٍ."

def buy(symbol):
    path = "/order"
    body = {
        "market": symbol,
        "side": "buy",
        "orderType": "market",
        "amountQuote": str(BUY_AMOUNT_EUR)
    }
    res = bitvavo_request("POST", path, body)
    if "id" in res:
        price = float(res["fills"][0]["price"])
        amount = float(res["fills"][0]["amount"])
        r.set(IS_TRADING_KEY, "1")
        r.set(LAST_TRADE_KEY, json.dumps({"symbol": symbol, "entry": price, "amount": amount}))
        send_message(f"✅ شراء {symbol} تم بنجاح بسعر {price:.4f}")
        return price, amount
    else:
        reason = res.get("error", res)
        send_message(f"❌ فشل شراء {symbol}: {reason}")
        r.set(f"nems:freeze:{symbol}", "1", ex=300)
        return None, None

def sell(symbol, amount, entry):
    path = "/order"
    body = {
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "amount": str(amount)
    }
    res = bitvavo_request("POST", path, body)
    if "id" in res:
        price = float(res["fills"][0]["price"])
        profit = (price - entry) / entry * 100
        result = "win" if profit >= 0 else "loss"
        save_trade(symbol, entry, price, "auto-sell", result, profit)
        send_message(f"💰 بيع {symbol} بسعر {price:.4f} | الربح: {profit:.2f}%")
        r.delete(IS_TRADING_KEY)
        r.delete(LAST_TRADE_KEY)
        return True
    else:
        send_message(f"❌ فشل بيع {symbol}: {res}")
        return False

def monitor_trade():
    if not r.get(IS_TRADING_KEY):
        return
    try:
        trade = json.loads(r.get(LAST_TRADE_KEY))
        symbol = trade["symbol"]
        entry = trade["entry"]
        amount = trade["amount"]

        ticker = bitvavo_request("GET", f"/ticker/price?market={symbol}")
        price = float(ticker.get("price", 0))

        change = (price - entry) / entry * 100
        if change >= 2 or change <= -2:
            sell(symbol, amount, entry)

    except Exception as e:
        print("Monitor error:", e)

def trader_loop():
    while True:
        if not r.get(IS_TRADING_KEY):
            symbol, reason, _ = pick_best_symbol()
            if symbol:
                send_message(f"🚨 إشارة شراء: {reason}")
                buy(symbol)
            else:
                print("🔍 لا فرص حالياً...")
        else:
            monitor_trade()
        time.sleep(60)

def handle_telegram_command(text):
    print("📩 أمر تلقاه:", text)
    text = text.strip().lower()
    if "رصيد" in text:
        msg = get_balance()
        send_message(f"💰 الرصيد:\n{msg}")
    elif text == "reset":
        r.delete(IS_TRADING_KEY)
        r.delete(LAST_TRADE_KEY)
        for k in r.scan_iter("nems:freeze:*"):
            r.delete(k)
        send_message("♻️ تم إعادة تشغيل البوت بدون حذف الذاكرة.")
    elif "شو عم تعمل" in text:
        if r.get(IS_TRADING_KEY):
            trade = json.loads(r.get(LAST_TRADE_KEY))
            send_message(f"🔄 داخل صفقة {trade['symbol']} بسعر {trade['entry']}")
        else:
            send_message("🤖 البوت حالياً لا يملك أي صفقة.")

def telegram_polling():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            if offset:
                url += f"?offset={offset}"
            res = requests.get(url).json()

            if not isinstance(res, dict) or "result" not in res:
                print("⚠️ Telegram response is not valid:", res)
                time.sleep(3)
                continue

            for update in res["result"]:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text")
                chat_id = str(message.get("chat", {}).get("id"))
                if chat_id == CHAT_ID and text:
                    handle_telegram_command(text)

        except Exception as e:
            print("Telegram polling error:", e)
        time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=trader_loop).start()
    telegram_polling()