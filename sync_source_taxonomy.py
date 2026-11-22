"""Read public catalog metadata only. Never access carts, orders or customer data."""
import html
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.seferkodesh.co.il/wp-json/wc/store/v1/'


def read_pages(endpoint, session):
    rows = []
    total = None
    page = 1
    while True:
        response = session.get(BASE + endpoint, params={
            'per_page': 100, 'page': page,
            'orderby': 'name' if endpoint.endswith('/categories') else 'id', 'order': 'asc',
            **({'hide_empty': 'false'} if endpoint.endswith('/categories') else {}),
        }, timeout=45)
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError('Unexpected catalog response')
        current_total = int(response.headers['X-WP-Total'])
        if total is not None and current_total != total:
            raise ValueError('Source changed during scan; retry without publishing')
        total = current_total
        rows.extend(batch)
        print(f'{endpoint}: {len(rows)}/{total}', flush=True)
        if page >= int(response.headers['X-WP-TotalPages']):
            break
        page += 1
        time.sleep(0.2)
    if len(rows) != total or len({row['id'] for row in rows}) != total:
        raise ValueError('Incomplete or duplicate source catalog')
    return rows


def build_tree(categories):
    by_id = {c['id']: c for c in categories}
    nodes = {}
    for category in categories:
        seen = set()
        current = category
        while current['parent']:
            if current['id'] in seen or current['parent'] not in by_id:
                raise ValueError('Cyclic or missing category parent')
            seen.add(current['id'])
            current = by_id[current['parent']]
        nodes[category['id']] = {
            'id': category['id'], 'name': html.unescape(category['name']),
            'parent_id': category['parent'], 'children': [],
        }
    roots = []
    for category in categories:
        node = nodes[category['id']]
        if node['parent_id']:
            nodes[node['parent_id']]['children'].append(node)
        else:
            roots.append(node)
    return [dict(node, parent=node['name'], nodes=node['children'],
                 children=[child['name'] for child in node['children']]) for node in roots]


def url_key(url):
    return unquote(urlsplit(url or '').path).rstrip('/')


def build_navigation(categories, homepage):
    taxonomy = build_tree(categories)
    by_url = {url_key(c['permalink']): c for c in categories}
    nodes = {}

    def collect(node):
        nodes[node['id']] = dict(node, children=node.get('nodes', node['children']))
        for child in nodes[node['id']]['children']:
            collect(child)

    for root in taxonomy:
        collect(root)
    used = set()
    groups = []
    soup = BeautifulSoup(homepage, 'html.parser')
    for item in soup.select('li.sk-menu-item'):
        control = item.find(class_='sk-parent-control', recursive=False)
        if not control:
            continue
        labels = control.find_all('span', recursive=False)
        name = next((label.get_text(' ', strip=True) for label in labels
                     if label.get('aria-hidden') != 'true'), '')
        if not name or any(group['name'] == name for group in groups):
            continue
        children = []
        for link in item.select('.sk-submenu a[href]'):
            if '/product-category/' not in link['href']:
                continue
            category = by_url.get(url_key(link['href']))
            if not category:
                raise ValueError('Menu category not present in source taxonomy: ' + link['href'])
            if not any(child['id'] == category['id'] for child in children):
                children.append(nodes[category['id']])
            used.add(category['id'])
        if children:
            groups.append(dict(id='menu:' + name, name=name, parent=name,
                               nodes=children, children=[c['name'] for c in children]))
    if not groups:
        raise ValueError('Source navigation missing; refusing to flatten existing menu')
    # Keep categories not linked from the source menu accessible, without promoting its children.
    for root in taxonomy:
        if root['id'] not in used:
            groups.append(root)
    return groups


def reconcile(products, source, categories):
    by_id = {str(p['id']): p for p in source}
    by_url = {url_key(p['permalink']): p for p in source}
    category_ids = {c['id'] for c in categories}
    matched, absent, seen = 0, [], set()
    output = []
    for index, old in enumerate(products):
        product = dict(old)
        source_id = old.get('product_id') or old.get('source_product_id')
        original = by_id.get(str(source_id)) if source_id else by_url.get(url_key(old.get('url')))
        if original:
            assigned = original.get('categories', [])
            if any(c['id'] not in category_ids for c in assigned):
                raise ValueError('Product references unknown category')
            product['source_category_ids'] = [c['id'] for c in assigned]
            product['categories'] = [html.unescape(c['name']) for c in assigned]
            product['source_product_id'] = original['id']
            product['source_catalog_missing'] = False
            seen.add(original['id'])
            matched += 1
        else:
            # Preserve indexes used by existing orders, but do not sell unlisted items.
            product['source_catalog_missing'] = True
            product['in_stock'] = False
            product['needs_revalidation'] = True
            absent.append(index)
        output.append(product)
    missing = [dict(id=p['id'], name=html.unescape(p['name']), url=p['permalink'])
               for p in source if p['id'] not in seen]
    return output, matched, absent, missing


def save(path, data):
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    os.replace(temporary, path)


def main():
    with requests.Session() as session:
        categories = read_pages('products/categories', session)
        source = read_pages('products', session)
    response = requests.get('https://www.seferkodesh.co.il/', timeout=30)
    response.raise_for_status()
    tree = build_navigation(categories, response.text)
    with open('products.json', encoding='utf-8') as handle:
        products = json.load(handle)
    updated, matched, absent, missing = reconcile(products, source, categories)
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'source_products': len(source), 'local_products': len(products),
        'source_categories': len(categories), 'root_categories': len(tree),
        'source_menu_groups': sum(str(node['id']).startswith('menu:') for node in tree),
        'matched_products': matched, 'local_not_in_source': len(absent),
        'missing_products': len(missing),
        'pending_revalidation': sum(bool(p.get('needs_revalidation')) and not p.get('source_catalog_missing') for p in updated),
        'local_not_in_source_indexes': absent,
    }
    # Publish only after every page and relationship has been validated.
    save('categories.json', tree)
    save('source-categories.json', categories)
    save('products.json', updated)
    save('missing-source-products.json', missing)
    save('catalog-audit.json', report)
    with open('all_urls.json', encoding='utf-8') as handle:
        urls = json.load(handle)
    save('all_urls.json', list(dict.fromkeys(urls + [p['url'] for p in missing])))
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}))


if __name__ == '__main__':
    main()
