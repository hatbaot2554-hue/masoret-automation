"""Small real supplier scan, isolated from orders and customer notifications."""
import json
from pathlib import Path
from scrape_products import scrape_product

def main():
    path = Path('products.json')
    products = json.loads(path.read_text(encoding='utf-8'))
    candidates = list(range(min(2, len(products))))
    candidates += [i for i, p in enumerate(products) if p.get('needs_revalidation')][:3]
    report = []
    for index in candidates:
        old = products[index]
        new = scrape_product(old['url'])
        if not new or not new.get('name') or float(new.get('price') or 0) <= 0:
            report.append({'index': index, 'ok': False})
            continue
        products[index] = new
        report.append({'index': index, 'ok': True, 'name': new['name'], 'price': new['price'], 'in_stock': new.get('in_stock'), 'category': new.get('category')})
    Path('sync-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(row['ok'] for row in report) or not report:
        raise RuntimeError('Supplier verification incomplete; catalog was not modified')
    path.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
