import os
import json
import requests
import threading
import time
import tempfile
from flask import Flask, request, jsonify
from datetime import datetime
import httpx
from openai import OpenAI

app = Flask(__name__)

# Config
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8596361967:AAGq8sDuFQK6Qk5EGCipKhcnRpbxDPzw0kk")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6604759949")
INSTANTLY_API_KEY_V1 = os.environ.get("INSTANTLY_API_KEY_V1", "AGE-3Lo503KHSt0mb1FKfYaPMMqNM")
INSTANTLY_API_KEY_V2 = os.environ.get("INSTANTLY_API_KEY_V2", "YmFlNjk3MTAtYmQ2Zi00NGY2LTgyM2YtODNmNDUwNTk0YWU5OlpCY1VxQk9jbVlCbA==")
MILWAUKEE_CAMPAIGN_ID = os.environ.get("MILWAUKEE_CAMPAIGN_ID", "b6758280-a3f4-416f-b38f-539a85399cd1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://openai.manusai.io/v1")

openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    http_client=httpx.Client()
)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# ─── Telegram Helpers ────────────────────────────────────────────────────────

def send_telegram(text, chat_id=None):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }, timeout=10)


def send_typing(chat_id=None):
    chat_id = chat_id or TELEGRAM_CHAT_ID
    requests.post(f"{TELEGRAM_API}/sendChatAction", json={
        "chat_id": chat_id,
        "action": "typing"
    }, timeout=5)


# ─── Instantly API Helpers ───────────────────────────────────────────────────

def get_campaign_status():
    r = requests.get(
        f"https://api.instantly.ai/api/v2/campaigns/{MILWAUKEE_CAMPAIGN_ID}",
        headers={"Authorization": f"Bearer {INSTANTLY_API_KEY_V2}"},
        timeout=10
    )
    return r.json()


def get_campaign_analytics():
    r = requests.get(
        f"https://api.instantly.ai/api/v2/campaigns/{MILWAUKEE_CAMPAIGN_ID}/analytics",
        headers={"Authorization": f"Bearer {INSTANTLY_API_KEY_V2}"},
        timeout=10
    )
    return r.json()


def pause_campaign():
    r = requests.post(
        f"https://api.instantly.ai/api/v2/campaigns/{MILWAUKEE_CAMPAIGN_ID}/pause",
        headers={"Authorization": f"Bearer {INSTANTLY_API_KEY_V2}"},
        timeout=10
    )
    return r.json()


def resume_campaign():
    r = requests.post(
        f"https://api.instantly.ai/api/v2/campaigns/{MILWAUKEE_CAMPAIGN_ID}/activate",
        headers={"Authorization": f"Bearer {INSTANTLY_API_KEY_V2}"},
        timeout=10
    )
    return r.json()


def get_recent_replies(limit=5):
    r = requests.post(
        "https://api.instantly.ai/api/v1/lead/list",
        json={
            "api_key": INSTANTLY_API_KEY_V1,
            "campaign_id": MILWAUKEE_CAMPAIGN_ID,
            "limit": 100,
            "skip": 0
        },
        timeout=10
    )
    data = r.json()
    leads = data.get("leads", []) if isinstance(data, dict) else data
    replied = [l for l in leads if l.get("email_replied") or l.get("email_reply_count", 0) > 0]
    return replied[:limit]


def get_lead_count():
    r = requests.post(
        "https://api.instantly.ai/api/v1/lead/list",
        json={
            "api_key": INSTANTLY_API_KEY_V1,
            "campaign_id": MILWAUKEE_CAMPAIGN_ID,
            "limit": 100,
            "skip": 0
        },
        timeout=10
    )
    data = r.json()
    leads = data.get("leads", []) if isinstance(data, dict) else data
    total = len(leads)
    contacted = len([l for l in leads if l.get("timestamp_last_contact")])
    replied = len([l for l in leads if l.get("email_reply_count", 0) > 0])
    return total, contacted, replied


# ─── AI Brain ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an AI assistant managing a cold email campaign called "Milwaukee IOS Deal - Investor Outreach" via the Instantly platform. You help Saul Zenkevicius manage his campaign through natural conversation.

You have access to these actions:
- get_status: Get campaign status (active/paused)
- get_analytics: Get campaign analytics (opens, replies, etc.)
- pause_campaign: Pause the campaign
- resume_campaign: Resume/activate the campaign
- get_replies: Get recent lead replies
- get_lead_count: Get total leads, contacted, and replied counts

Based on the user's message, decide which action(s) to take and respond naturally.
Always respond in a friendly, concise, professional tone.
Format numbers clearly. Use emojis sparingly but effectively.

Return a JSON object with:
{
  "actions": ["action1", "action2"],  // list of actions to execute (can be empty)
  "response_template": "Your response text here with {placeholders} for data"
}
"""


def ai_decide_and_respond(user_message, action_results=None):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]

    if action_results:
        messages.append({
            "role": "user",
            "content": f"Here is the data from the API calls: {json.dumps(action_results)}\n\nNow generate a natural, helpful response to the original question."
        })

    response = openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=500
    )
    return response.choices[0].message.content


def parse_actions(ai_response):
    try:
        # Try to extract JSON from response
        if "{" in ai_response:
            start = ai_response.index("{")
            end = ai_response.rindex("}") + 1
            data = json.loads(ai_response[start:end])
            return data.get("actions", [])
    except Exception:
        pass
    return []


def execute_actions(actions):
    results = {}
    for action in actions:
        try:
            if action == "get_status":
                data = get_campaign_status()
                status_map = {0: "Draft", 1: "Active/Running", 2: "Paused", 3: "Completed", 4: "Stopped"}
                results["status"] = {
                    "name": data.get("name"),
                    "status": status_map.get(data.get("status"), "Unknown"),
                    "daily_limit": data.get("daily_limit"),
                    "stop_on_reply": data.get("stop_on_reply")
                }
            elif action == "get_analytics":
                data = get_campaign_analytics()
                results["analytics"] = data
            elif action == "pause_campaign":
                data = pause_campaign()
                results["pause"] = data
            elif action == "resume_campaign":
                data = resume_campaign()
                results["resume"] = data
            elif action == "get_replies":
                replied = get_recent_replies()
                results["replies"] = [
                    {
                        "email": l.get("contact") or l.get("email", ""),
                        "name": f"{l.get('payload', {}).get('firstName', '')} {l.get('payload', {}).get('lastName', '')}".strip(),
                        "last_contact": l.get("timestamp_last_contact", "")
                    }
                    for l in replied
                ]
            elif action == "get_lead_count":
                total, contacted, replied = get_lead_count()
                results["lead_count"] = {
                    "total": total,
                    "contacted": contacted,
                    "replied": replied,
                    "pending": total - contacted
                }
        except Exception as e:
            results[action] = {"error": str(e)}
    return results


def transcribe_voice(file_id):
    # Download the voice file from Telegram
    file_info = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}").json()
    file_path = file_info["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

    audio_data = requests.get(file_url).content
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_data)
        tmp_path = f.name

    with open(tmp_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    os.unlink(tmp_path)
    return transcript.text


def handle_message(message):
    chat_id = str(message["chat"]["id"])

    # Only respond to authorized user
    if chat_id != TELEGRAM_CHAT_ID:
        return

    send_typing(chat_id)

    # Handle voice message
    if "voice" in message:
        try:
            file_id = message["voice"]["file_id"]
            send_telegram("🎙️ Transcribing your voice message...", chat_id)
            user_text = transcribe_voice(file_id)
            send_telegram(f"📝 You said: <i>{user_text}</i>", chat_id)
        except Exception as e:
            send_telegram(f"Sorry, I couldn't transcribe the voice message: {str(e)}", chat_id)
            return
    elif "text" in message:
        user_text = message["text"]
    else:
        return

    # Step 1: Ask AI what actions to take
    try:
        ai_response = ai_decide_and_respond(user_text)
        actions = parse_actions(ai_response)

        # Step 2: Execute actions
        action_results = {}
        if actions:
            action_results = execute_actions(actions)

        # Step 3: Ask AI to generate final response with data
        final_response = ai_decide_and_respond(user_text, action_results)

        # Clean up JSON if AI returned it
        if final_response.strip().startswith("{"):
            try:
                data = json.loads(final_response)
                final_response = data.get("response_template", final_response)
            except Exception:
                pass

        send_telegram(final_response, chat_id)

    except Exception as e:
        send_telegram(f"Sorry, something went wrong: {str(e)}", chat_id)


# ─── Telegram Polling ────────────────────────────────────────────────────────

last_update_id = 0


def poll_telegram():
    global last_update_id
    while True:
        try:
            r = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35
            )
            updates = r.json().get("result", [])
            for update in updates:
                last_update_id = update["update_id"]
                if "message" in update:
                    threading.Thread(
                        target=handle_message,
                        args=(update["message"],),
                        daemon=True
                    ).start()
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)


# ─── Flask Routes ────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Instantly Telegram AI Bot is running"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json or {}
        event_type = data.get("event_type", "")

        if "reply" in event_type.lower() or event_type == "reply_received":
            lead_email = data.get("lead_email") or data.get("contact") or data.get("email", "Unknown")
            first_name = data.get("first_name") or data.get("firstName") or ""
            last_name = data.get("last_name") or data.get("lastName") or ""
            full_name = f"{first_name} {last_name}".strip() or "Unknown"
            campaign_name = data.get("campaign_name") or "Milwaukee IOS Deal"
            subject = data.get("subject") or "(reply thread)"
            reply_text = data.get("reply_text") or data.get("body") or "(no preview)"
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

        return jsonify({"status": "event received"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Start ───────────────────────────────────────────────────────────────────

# Start Telegram polling in background thread
polling_thread = threading.Thread(target=poll_telegram, daemon=True)
polling_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
