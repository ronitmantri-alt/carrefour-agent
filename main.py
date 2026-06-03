import os
import json
from flask import Flask, request, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client
from playwright.sync_api import sync_playwright
import anthropic

app = Flask(__name__)

# Load environment variables
CARREFOUR_EMAIL = os.environ.get("CARREFOUR_EMAIL")
CARREFOUR_PASSWORD = os.environ.get("CARREFOUR_PASSWORD")
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")
TWILIO_WHATSAPP_TO = os.environ.get("TWILIO_WHATSAPP_TO")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Shopping list stored in a simple JSON file
SHOPPING_LIST_FILE = "shopping_list.json"

def load_shopping_list():
    if os.path.exists(SHOPPING_LIST_FILE):
        with open(SHOPPING_LIST_FILE, "r") as f:
            return json.load(f)
    return []

def save_shopping_list(items):
    with open(SHOPPING_LIST_FILE, "w") as f:
        json.dump(items, f)

def send_whatsapp(message):
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    client.messages.create(
        body=message,
        from_=TWILIO_WHATSAPP_FROM,
        to=TWILIO_WHATSAPP_TO
    )

def add_to_carrefour_cart():
    shopping_list = load_shopping_list()
    if not shopping_list:
        send_whatsapp("⚠️ Your shopping list is empty! Add items on your webpage.")
        return

    added = []
    failed = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # Login to Carrefour UAE
            page.goto("https://www.carrefouruae.com/login")
            page.wait_for_load_state("networkidle")
            page.fill("input[type='email']", CARREFOUR_EMAIL)
            page.fill("input[type='password']", CARREFOUR_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")

            for item in shopping_list:
                try:
                    # Search for item
                    page.goto(f"https://www.carrefouruae.com/search?q={item['name']}")
                    page.wait_for_load_state("networkidle")

                    # Click first add to cart button
                    add_btn = page.locator("button[data-testid='add-to-cart-button']").first
                    add_btn.click()
                    page.wait_for_timeout(1000)
                    added.append(item['name'])
                except Exception as e:
                    failed.append(item['name'])

        except Exception as e:
            send_whatsapp(f"❌ Carrefour login failed. Please check your credentials.")
            browser.close()
            return

        browser.close()

    # Send WhatsApp notification
    msg = f"🛒 Carrefour cart updated!\n\n"
    if added:
        msg += f"✅ Added ({len(added)}):\n" + "\n".join(f"• {i}" for i in added)
    if failed:
        msg += f"\n\n❌ Failed ({len(failed)}):\n" + "\n".join(f"• {i}" for i in failed)
    msg += "\n\nGo checkout when ready! 🎉"
    send_whatsapp(msg)

# Webpage routes
@app.route("/")
def index():
    items = load_shopping_list()
    return render_template("index.html", items=items)

@app.route("/add", methods=["POST"])
def add_item():
    data = request.json
    items = load_shopping_list()
    items.append({"name": data["name"], "quantity": data.get("quantity", 1)})
    save_shopping_list(items)
    return jsonify({"success": True, "items": items})

@app.route("/remove", methods=["POST"])
def remove_item():
    data = request.json
    items = load_shopping_list()
    items = [i for i in items if i["name"] != data["name"]]
    save_shopping_list(items)
    return jsonify({"success": True, "items": items})

@app.route("/run", methods=["POST"])
def run_now():
    add_to_carrefour_cart()
    return jsonify({"success": True})

# Scheduler - runs every Sunday at 9am
scheduler = BackgroundScheduler()
scheduler.add_job(add_to_carrefour_cart, "cron", day_of_week="sun", hour=9)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
