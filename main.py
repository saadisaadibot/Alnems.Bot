import os
import time
import redis
import json
from uuid import uuid4
import threading
import requests
from utils import bitvavo_request
from market_scanner import pick_best_symbol
from memory import save_trade, get_top_confident
from dotenv import load_dotenv

load_dotenv()
r = redis.from_url(os.getenv("REDIS_URL"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 20))

ACTIVE_TRADES_KEY = "nems:active_trades"
TRADE_KEY = "nems:trades"
TRAIL_KEY = "nems:trailing"

def send_message(text):
    print(">>", text)
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except:
        pass

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
    body = {
        "market": symbol,
        "side": "buy",
        "orderType": "market",
        "amountQuote": f"{BUY_AMOUNT_EUR:.2f}",
        "clientOrderId": str(uuid4()),
        "operatorId": ""
    }
    res = bitvavo_request("POST", "/order", body)

    if isinstance(res, dict) and res.get("status") == "filled":
        try:
            fills = res.get("fills", [])
if not fills or "price" not in fills[0]:
    send_message(f"❌ فشل الحصول على السعر بعد الشراء: {symbol}")
    return

price = float(fills[0]["price"])
amount = float(fills[0]["amount"])

if price == 0:
    send_message(f"❌ السعر يساوي صفر بعد الشراء: {symbol}")
    return
            r.hset(ACTIVE_TRADES_KEY, symbol, json.dumps({
                "symbol": symbol,
                "entry": price,
                "amount": amount,
                "trail": price,
                "trail_percent": 0.5,
                "max_profit": 0  # ⬅️ تم إضافتها هنا
            }))
            send_message(f"✅ شراء {symbol} بسعر {price:.4f}")
            return price, amount
        except Exception as e:
            send_message(f"⚠️ تم الشراء لكن فشل تحليل الرد: {e}")
    else:
        reason = res.get("error") or json.dumps(res, ensure_ascii=False)
        send_message(f"❌ فشل شراء {symbol}: {reason}")
        r.set(f"nems:freeze:{symbol}", "1", ex=300)

    return None, None

def sell(symbol, amount, entry):
    body = {
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "amount": str(amount),
        "clientOrderId": str(uuid4()),
        "operatorId": ""
    }
    res = bitvavo_request("POST", "/order", body)

    if isinstance(res, dict) and res.get("status") == "filled":
        try:
            fills = res.get("fills", [])
            price = float(fills[0]["price"]) if fills else float(entry)
            profit = (price - entry) / entry * 100
            result = "win" if profit >= 0 else "loss"
            save_trade(symbol, entry, price, "auto-sell", result, profit)
            send_message(f"💰 بيع {symbol} بسعر {price:.4f} | الربح: {profit:.2f}%")
            r.hdel(ACTIVE_TRADES_KEY, symbol)
            return True
        except Exception as e:
            send_message(f"⚠️ البيع تم لكن فشل تحليل البيانات: {e}")
            return True
    else:
        send_message(f"❌ فشل بيع {symbol}: {res}")
        return False

def monitor_trades():
    active = r.hgetall(ACTIVE_TRADES_KEY)
    for symbol_b, trade_json in active.items():
        try:
            trade = json.loads(trade_json)
            symbol = trade["symbol"]
            entry = trade["entry"]
            amount = trade["amount"]
            trail_percent = trade.get("trail_percent", 0.5)
            max_profit = trade.get("max_profit", 0)

            # السعر الحالي
            ticker = bitvavo_request("GET", f"/ticker/price?market={symbol}")
            price = float(ticker.get("price", 0))
            profit = (price - entry) / entry * 100

            # تحديث أعلى ربح تحقق
            if profit > max_profit:
                trade["max_profit"] = round(profit, 4)
                r.hset(ACTIVE_TRADES_KEY, symbol, json.dumps(trade))
                continue  # لا تبيع الآن، لأن السعر في ذروة جديدة

            # تحقق إذا هبط من الذروة بأكثر من trail_percent
            if max_profit > 0 and profit <= max_profit - trail_percent:
                sell(symbol, amount, entry)

        except Exception as e:
            print("Monitor error:", e)

def trader_loop():
    while True:
        active = r.hgetall(ACTIVE_TRADES_KEY)
        if len(active) < 2:
            symbol, reason, _ = pick_best_symbol()
            if symbol and symbol.encode() not in active:
                send_message(f"🚨 إشارة شراء: {reason}")
                buy(symbol)
            else:
                print("🔍 لا فرص أو العملة مكررة...")
        else:
            monitor_trades()
        time.sleep(2)

def get_summary():
    trades = [json.loads(x) for x in r.lrange(TRADE_KEY, 0, -1)]
    if not trades:
        return "📊 لا يوجد صفقات مسجلة بعد."

    total = len(trades)
    wins = sum(1 for t in trades if t["result"] == "win")
    losses = total - wins
    avg = sum(t["percent"] for t in trades) / total
    profit = sum(t["percent"] for t in trades)

    last_trades = "\n".join([f"{t['symbol']} | {t['result']} | {t['percent']}%" for t in trades[:3]])
    top_coins = get_top_confident()
    top_str = "\n".join([f"{s[0]}: {s[1]}" for s in top_coins])

    # 🔁 تحليل تغييرات الاستراتيجية
    adjustments = []
    if r.exists("nems:strategy:position"):
        pos = float(r.get("nems:strategy:position"))
        adjustments.append(f"📉 تم تخفيض شرط Position إلى {pos:.1f}% بعد تجارب ناجحة.")
    if r.exists("nems:strategy:slope"):
        slope = float(r.get("nems:strategy:slope"))
        adjustments.append(f"📈 تم رفع شرط Slope إلى {slope:.2f}% لتقليل الصفقات الخاسرة.")
    if r.exists("nems:strategy:wave"):
        wave = float(r.get("nems:strategy:wave"))
        adjustments.append(f"🌊 تم تعديل شرط Wave إلى {wave:.1f}% بناءً على الأداء.")

    strategy_notes = "\n".join(adjustments) or "⚙️ لا توجد تعديلات استراتيجية حالياً."

    # 🤖 تقييم الذكاء (بناءً على نسبة الفوز)
    intelligence = (wins / total) * 100 if total else 0
    ai_rating = "🔵 متوسط" if intelligence < 60 else "🟢 ذكي" if intelligence < 80 else "🟣 خارق"

    return f"""📈 ملخص التداول:
عدد الصفقات: {total}
✅ رابحة: {wins} | ❌ خاسرة: {losses}
💹 الربح التراكمي: {profit:.2f}%
📊 متوسط الصفقة: {avg:.2f}%
🤖 نسبة الذكاء: {intelligence:.1f}% ({ai_rating})

🏅 العملات الأعلى ثقة:
{top_str}

🛠️ تحديثات الاستراتيجية:
{strategy_notes}

🕵️ آخر 3 صفقات:
{last_trades}
"""

def handle_telegram_command(text):
    text = text.strip().lower()
    if "رصيد" in text:
        send_message(f"💰 الرصيد:\n{get_balance()}")
    elif "الملخص" in text:
        send_message(get_summary())
    elif text == "reset":
        r.delete(ACTIVE_TRADES_KEY)
        for k in r.scan_iter("nems:freeze:*"):
            r.delete(k)
        send_message("♻️ تم إعادة ضبط جميع الصفقات.")
    elif "شو عم تعمل" in text:
        active = r.hgetall(ACTIVE_TRADES_KEY)
        if not active:
            send_message("🤖 لا يوجد أي صفقة حالياً.")
        else:
            status = "\n".join([
                f"{json.loads(v)['symbol']} بسعر {json.loads(v)['entry']}" for v in active.values()
            ])
            send_message(f"🔄 الصفقات النشطة:\n{status}")
    elif "شو شايف" in text or "أقوى عملات" in text:
        from market_scanner import get_top_candidates
        top = get_top_candidates()
        msg = "👁️ العملات الأقوى حاليًا:\n"
        for i, (symbol, score, debug) in enumerate(top, 1):
            msg += f"{i}. {symbol} | نقاط={score} | {' | '.join(debug)}\n"
        send_message(msg.strip() or "❌ لا يوجد بيانات حالياً.")
def telegram_polling():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            if offset:
                url += f"?offset={offset}"

            response = requests.get(url)
            res = response.json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text")
                chat = message.get("chat", {})
                chat_id = str(chat.get("id"))

                if chat_id == CHAT_ID and text:
                    handle_telegram_command(text)

        except Exception as e:
            print("Telegram polling error:", e)
        time.sleep(2)

if __name__ == "__main__":
    send_message("🚀 النمس الذكي بدأ العمل - يدير صفقتين ويستخدم Trailing Stop.")
    threading.Thread(target=trader_loop).start()
    telegram_polling()