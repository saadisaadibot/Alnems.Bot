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
CHAT_ID = str(os.getenv("CHAT_ID"))
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
    total_value = 0.0
    summary = []

    for b in balances:
        try:
            symbol = b.get("symbol")
            available = float(b.get("available", 0))
            if available < 0.01:
                continue
            if symbol == "EUR":
                total_value += available
                summary.append(f"EUR: {available:.2f}€")
            else:
                ticker = bitvavo_request("GET", f"/ticker/price?market={symbol}-EUR")
                price = float(ticker.get("price", 0))
                value = price * available
                total_value += value
                summary.append(f"{symbol}: {available:.2f} ≈ {value:.2f}€")
        except:
            continue

    summary.append(f"\n📊 المجموع: {total_value:.2f}€")
    return "\n".join(summary) if summary else "لا يوجد رصيد كافٍ."

def buy(symbol):
    path = "/order"
    body = {
        "market": symbol,
        "side": "buy",
        "orderType": "market",
        "amountQuote": f"{BUY_AMOUNT_EUR:.2f}",
        "operatorId": ""  # ← حل مشكلة parameter is required
    }
    res = bitvavo_request("POST", path, body)

    if isinstance(res, dict) and res.get("status") == "filled":
        try:
            fills = res.get("fills", [])
            price = float(fills[0]["price"])
            amount = float(fills[0]["amount"])
            r.set(IS_TRADING_KEY, "1")
            r.set(LAST_TRADE_KEY, json.dumps({
                "symbol": symbol,
                "entry": price,
                "amount": amount
            }))
            send_message(f"✅ شراء {symbol} تم بنجاح بسعر {price:.4f}")
            return price, amount
        except Exception as e:
            send_message(f"⚠️ تم الشراء لكن تحليل الرد فشل: {e}")
    else:
        reason = res.get("error") or json.dumps(res, ensure_ascii=False)
        send_message(f"❌ فشل شراء {symbol}: {reason}")
        r.set(f"nems:freeze:{symbol}", "1", ex=300)

    return None, None


def sell(symbol, amount, entry):
    path = "/order"
    body = {
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "amount": str(amount),
        "operatorId": ""  # ← مبدئياً فارغ لتفادي الخطأ الإجباري
    }
    res = bitvavo_request("POST", path, body)

    # ✅ تحقق من نجاح الصفقة بناءً على status
    if isinstance(res, dict) and res.get("status") == "filled":
        try:
            fills = res.get("fills", [])
            price = float(fills[0]["price"]) if fills else float(entry)
            profit = (price - entry) / entry * 100
            result = "win" if profit >= 0 else "loss"
            save_trade(symbol, entry, price, "auto-sell", result, profit)
            send_message(f"💰 بيع {symbol} بسعر {price:.4f} | الربح: {profit:.2f}%")
            r.delete(IS_TRADING_KEY)
            r.delete(LAST_TRADE_KEY)
            return True
        except Exception as e:
            send_message(f"⚠️ البيع تم لكن فشل تحليل البيانات: {e}")
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

            response = requests.get(url)
            try:
                res = response.json()
            except Exception:
                print("⚠️ رد Telegram غير صالح:", response.text)
                time.sleep(3)
                continue

            if not isinstance(res, dict) or "result" not in res:
                print("⚠️ رد Telegram غير متوقع:", res)
                time.sleep(3)
                continue

            for update in res["result"]:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text")
                chat = message.get("chat", {})
                chat_id = str(chat.get("id"))

                if chat_id == CHAT_ID and text:
                    print(f"📨 أمر من Telegram: {text}")
                    handle_telegram_command(text)

        except Exception as e:
            print("❌ Telegram polling error:", e)

        time.sleep(2)

if __name__ == "__main__":
    send_message("🚀 النمس الذكي يعمل الآن! جاهز لاكتشاف الفرص.")
    threading.Thread(target=trader_loop).start()
    telegram_polling()