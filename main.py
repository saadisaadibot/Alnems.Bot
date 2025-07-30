from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    print("✅ الصفحة الرئيسية شغالة")
    return "أهلا! السيرفر شغال."

@app.route("/webhook", methods=["POST"])
def webhook():
    print("📩 Webhook واصل!")
    data = request.json
    print("🧾 البيانات:", data)
    return "OK"

if __name__ == "__main__":
    print("🚀 Starting app...")
    app.run(host="0.0.0.0", port=8080)