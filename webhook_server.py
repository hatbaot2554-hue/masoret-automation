"""
webhook_server.py
-----------------
שרת קטן שרץ תמיד ומחכה להזמנות מהאתר החדש.
כשמגיעה הזמנה — מפעיל את place_order.py אוטומטית.
גם שולח התראה במייל עם פרטי התשלום.
"""

from flask import Flask, request, jsonify
import threading
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from place_order import place_order

app = Flask(__name__)

# הגדרות מייל (Gmail)
GMAIL_USER     = os.environ.get("GMAIL_USER", "")      # המייל שלך
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")  # App Password של Gmail
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL", "")    # לאן לשלוח התראות


def send_payment_notification(order_data, original_price):
    """שולח מייל עם פרטי התשלום"""
    if not GMAIL_USER or not NOTIFY_EMAIL:
        print("  ⚠️ מייל לא מוגדר, מדלג על התראה")
        return

    try:
        customer = order_data["customer"]
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"💰 הזמנה חדשה — יש להעביר ₪{original_price}"
        msg["From"] = GMAIL_USER
        msg["To"] = NOTIFY_EMAIL

        body = f"""
        <div dir="rtl" style="font-family: Arial; padding: 20px;">
            <h2 style="color: #1A2332;">הזמנה חדשה התקבלה!</h2>

            <div style="background: #f8f4ee; padding: 16px; border-radius: 8px; margin: 16px 0;">
                <h3>💳 פעולה נדרשת</h3>
                <p style="font-size: 20px; font-weight: bold; color: #8B6914;">
                    יש להעביר ₪{original_price} לאתר של אבא
                </p>
            </div>

            <h3>פרטי הלקוח:</h3>
            <ul>
                <li>שם: {customer['first_name']} {customer['last_name']}</li>
                <li>אימייל: {customer['email']}</li>
                <li>טלפון: {customer['phone']}</li>
                <li>כתובת: {customer['address']}, {customer['city']}</li>
            </ul>

            <h3>פרטי המוצר:</h3>
            <ul>
                <li>מוצר: {order_data.get('product_name', '')}</li>
                <li>כמות: {order_data.get('quantity', 1)}</li>
                <li>מחיר באתר המקורי: ₪{original_price}</li>
            </ul>

            <p style="color: #666; font-size: 13px;">
                ההזמנה נשלחה אוטומטית לאתר של אבא ✅
            </p>
        </div>
        """

        msg.attach(MIMEText(body, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())

        print("  📧 התראת מייל נשלחה!")

    except Exception as e:
        print(f"  ⚠️ שגיאה בשליחת מייל: {e}")


def process_order_async(order_data, original_price):
    """מעבד הזמנה ברקע — לא מחכה"""
    def run():
        # מפעיל את רובוט ההזמנה
        result = place_order(order_data)

        # שולח התראת מייל
        send_payment_notification(order_data, original_price)

        print(f"\n✅ עיבוד הזמנה הושלם: {result}")

    thread = threading.Thread(target=run)
    thread.daemon = True
    thread.start()


@app.route("/webhook/new-order", methods=["POST"])
def new_order():
    """
    מקבל הזמנה מהאתר החדש (Next.js).
    
    פורמט בקשה:
    {
        "product_url": "https://www.seferkodesh.co.il/product-page/...",
        "product_name": "שם המוצר",
        "quantity": 1,
        "original_price": 45.00,
        "discount_code": "SALE10",
        "customer": {
            "first_name": "ישראל",
            "last_name": "ישראלי", 
            "email": "israel@example.com",
            "phone": "050-1234567",
            "address": "רחוב הרצל 1",
            "city": "תל אביב"
        }
    }
    """
    try:
        data = request.get_json()

        if not data or not data.get("customer") or not data.get("product_url"):
            return jsonify({"error": "חסרים פרטים"}), 400

        original_price = data.get("original_price", 0)

        # מעבד ברקע — מיד מחזיר תשובה ללקוח
        process_order_async(data, original_price)

        return jsonify({
            "success": True,
            "message": "ההזמנה התקבלה ועוברת עיבוד"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"})


if __name__ == "__main__":
    print("🚀 שרת webhook מופעל על פורט 5000")
    app.run(host="0.0.0.0", port=5000)
