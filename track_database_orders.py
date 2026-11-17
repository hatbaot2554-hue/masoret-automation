"""Synchronize only fulfillment statuses; never place supplier orders."""
import os
import requests
import psycopg2

STATUS_MAP = {'processing': 'warehouse_processing', 'completed': 'delivered',
              'shipped': 'shipped', 'delivered': 'delivered'}

def main():
    required = ['DATABASE_URL', 'SOURCE_WC_KEY', 'SOURCE_WC_SECRET']
    if any(not os.getenv(key) for key in required):
        raise RuntimeError('Missing tracking configuration: ' + ', '.join(key for key in required if not os.getenv(key)))
    base = os.getenv('SOURCE_WC_URL', 'https://www.seferkodesh.co.il').rstrip('/')
    with psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, external_order_id, status FROM orders WHERE external_order_id ~ '^[0-9]+$' AND status NOT IN ('delivered','cancelled')")
            orders = cur.fetchall()
        for order_id, external_id, previous in orders:
            response = requests.get(f'{base}/wp-json/wc/v3/orders/{external_id}', auth=(os.environ['SOURCE_WC_KEY'], os.environ['SOURCE_WC_SECRET']), timeout=20)
            response.raise_for_status()
            raw = str(response.json().get('status', '')).removeprefix('wc-')
            status = STATUS_MAP.get(raw)
            if status and status != previous:
                with conn.cursor() as cur:
                    cur.execute('UPDATE orders SET status=%s WHERE id=%s AND status=%s', (status, order_id, previous))
                conn.commit()
        print(f'Tracking completed: {len(orders)} database orders checked')

if __name__ == '__main__':
    main()
