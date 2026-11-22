"""Resume supplier verification without changing product indexes or placing orders."""
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from scrape_products import scrape_product, stable_product_merge

def valid_product(old, new):
    if not isinstance(new, dict) or not new.get('name') or not isinstance(new.get('in_stock'), bool):
        return False
    try:
        price = float(new.get('price', 0))
        if not math.isfinite(price) or price <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if old.get('product_id') and str(old['product_id']) != str(new.get('product_id')):
        return False
    return True

def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def run(limit=400, minutes=25, pause=0.6):
    path = Path('products.json')
    products = json.loads(path.read_text(encoding='utf-8'))
    pending = [i for i, p in enumerate(products) if p.get('needs_revalidation') and not p.get('source_catalog_missing')]
    # Failed products move to the back so every pending product gets a first attempt.
    pending.sort(key=lambda i: products[i].get('revalidation_attempts', 0))
    deadline = time.monotonic() + minutes * 60
    checked = verified = 0
    for index in pending[:limit]:
        if time.monotonic() >= deadline:
            break
        old = products[index]
        try:
            fresh = scrape_product(old['url'])
        except Exception:
            fresh = None
        if valid_product(old, fresh):
            products[index] = stable_product_merge([old], [fresh])[0]
            verified += 1
        else:
            old['revalidation_attempts'] = old.get('revalidation_attempts', 0) + 1
            old['revalidation_checked_at'] = datetime.now(timezone.utc).isoformat()
            old['in_stock'] = False
        checked += 1
        if checked % 25 == 0:
            save(path, products)
            print(f'Checked {checked}; verified {verified}', flush=True)
        time.sleep(pause)
    save(path, products)
    report = {'checked': checked, 'verified': verified, 'failed': checked - verified,
              'remaining': sum(bool(p.get('needs_revalidation')) for p in products),
              'updated_at': datetime.now(timezone.utc).isoformat()}
    save(Path('revalidation-progress.json'), report)
    print(json.dumps(report), flush=True)
    return report

if __name__ == '__main__':
    run()
