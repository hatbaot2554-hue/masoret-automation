import os
import psycopg2
import requests
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get('DATABASE_URL')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')

def get_orders_to_check():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, our_order_id, email, first_name, external_order_id, status
        FROM orders
        WHERE auto_submitted = TRUE
        AND status NOT IN ('הושלם', 'בוטל')
        AND created_at > NOW() - INTERVAL '30 days'
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def update_status(order_id, new_status):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
    conn.commit()
    cur.close()
    conn.close()

def send_status_email(email, first_name, our_order_id, status):
    if not RESEND_API_KEY:
        return
    requests.post('https://api.resend.com/emails', 
        headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
        json={
            'from': 'masoret@yourdomain.com',
            'to': email,
            'subject': f'עדכון הזמנה #{our_order_id}',
            'html': f'<p>שלום {first_name},</p><p>סטטוס הזמנה #{our_order_id} עודכן ל: <strong>{status}</strong></p>'
        }
    )

if __name__ == '__main__':
    orders = get_orders_to_check()
    for order in orders:
        order_id, our_id, email, first_name, ext_id, current_status = order
        # כאן תוסיף לוגיקה לבדיקת סטטוס מהאתר המקור
        print(f'בודק הזמנה #{our_id}')
