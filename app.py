import os
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8596361967:AAGq8sDuFQK6Qk5EGCipKhcnRpbxDPzw0kk")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6604759949")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception as e:
        print(f"Telegram error: {e}")
        return None


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Instantly Telegram Bot is running"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json or {}
        print(f"Received webhook: {data}")

        event_type = data.get("event_type", "")

        # Handle reply received event
        if "reply" in event_type.lower() or event_type in ["email_reply", "reply_received"]:
            lead_email = data.get("lead_email") or data.get("contact") or data.get("email", "Unknown")
            first_name = data.get("first_name") or data.get("firstName") or ""
            last_name = data.get("last_name") or data.get("lastName") or ""
            full_name = f"{first_name} {last_name}".strip() or "Unknown"
            campaign_name = data.get("campaign_name") or data.get("campaign", "Milwaukee IOS Deal")
            subject = data.get("subject") or data.get("email_subject") or "(reply thread)"
            reply_text = data.get("reply_text") or data.get("body") or data.get("message") or "(no preview)"

            # Truncate reply preview
            if len(reply_text) > 300:
                reply_text = reply_text[:300] + "..."

            now = datetime.now().strftime("%b %d, %Y %I:%M %p")

            message = (
                f"🔔 <b>New Reply — {campaign_name}</b>\n\n"
                f"👤 <b>From:</b> {full_name} ({lead_email})\n"
                f"📧 <b>Subject:</b> {subject}\n"
                f"💬 <b>Message:</b>\n{reply_text}\n\n"
                f"🕐 {now}"
            )

            send_telegram(message)
            return jsonify({"status": "notification sent"}), 200

        # Handle any other event — log it silently
        return jsonify({"status": "event received", "event_type": event_type}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/test", methods=["GET"])
def test():
    """Test endpoint to verify Telegram connection"""
    result = send_telegram(
        "🧪 <b>Test Notification</b>\n\nYour Instantly Reply Alert bot is working correctly!"
    )
    return jsonify({"status": "test sent", "telegram_response": result}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
