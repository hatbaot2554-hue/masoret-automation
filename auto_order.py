import asyncio
import json
import os
import psycopg2
from playwright.async_api import async_playwright

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_pending_orders():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.our_order_id, o.first_name, o.last_name, o.email, o.phone,
               o.address, o.city, o.note, o.items
        FROM orders o
        WHERE o.auto_submitted = FALSE AND o.status = 'ממתין'
        ORDER BY o.created_at ASC
        LIMIT 10
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def mark_submitted(order_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("UPDATE orders SET auto_submitted = TRUE, status = 'אושר' WHERE id = %s", (order_id,))
    conn.commit()
    cur.close()
    conn.close()

async def submit_order(page, order):
    order_id, our_id, first, last, email, phone, address, city, note, items = order
    items = json.loads(items) if isinstance(items, str) else items

    for item in items:
        url = item.get('source_url') or item.get('url')
        if not url:
            continue

        await page.goto(url, wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)

        # בחירת כמות
        qty = item.get('quantity', 1)
        # ... לוגיקה ספציפית לאתר המקור

    mark_submitted(order_id)
    print(f'✅ הזמנה #{our_id} הוגשה')

async def main():
    orders = get_pending_orders()
    if not orders:
        print('אין הזמנות ממתינות')
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for order in orders:
            try:
                await submit_order(page, order)
            except Exception as e:
                print(f'שגיאה בהזמנה {order[0]}: {e}')
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
