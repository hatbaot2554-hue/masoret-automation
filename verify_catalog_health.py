"""Separate safe publication from launch readiness; neither is inferred from exit 0."""
import json
import subprocess
import sys
from datetime import datetime, timezone


def identity(product):
    return str(product.get('product_id') or product.get('source_product_id') or product.get('url', ''))


def validate_positions(previous, current):
    if not current or len(current) < len(previous):
        raise ValueError('Catalog was emptied or shortened')
    for index, old in enumerate(previous):
        old_id = old.get('product_id') or old.get('source_product_id')
        same = identity(old) == identity(current[index]) if old_id else old.get('url') == current[index].get('url')
        if not identity(old) or not same:
            raise ValueError(f'Product identity changed at published position {index}')


def readiness(report):
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(report['checked_at'])).total_seconds()
    problems = []
    if not 0 <= age <= 86400:
        problems.append('Source audit is stale')
    for field in ('missing_products', 'pending_revalidation'):
        if report[field]:
            problems.append(f'{field}: {report[field]}')
    if report['source_products'] <= 0 or report['source_categories'] <= 0:
        problems.append('Empty source catalog')
    return problems


if __name__ == '__main__':
    if '--ready' in sys.argv:
        with open('catalog-audit.json', encoding='utf-8') as handle:
            problems = readiness(json.load(handle))
        if problems:
            for problem in problems:
                print(f'::error::{problem}')
            sys.exit(1)
        print('Catalog coverage is complete and recently audited')
    else:
        previous = json.loads(subprocess.check_output(['git', 'show', 'HEAD:products.json'], encoding='utf-8'))
        with open('products.json', encoding='utf-8') as handle:
            validate_positions(previous, json.load(handle))
        print('Published product positions preserved')
