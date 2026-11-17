import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.modules['scrape_products'] = types.SimpleNamespace(scrape_product=lambda url: None)
import revalidate_catalog as target

class RevalidationTests(unittest.TestCase):
    def test_identity_and_price_validation(self):
        old = {'product_id': 7}
        good = {'product_id': 7, 'name': 'Book', 'price': 20, 'in_stock': True}
        self.assertTrue(target.valid_product(old, good))
        for bad in [dict(good, price=float('nan')), dict(good, product_id=8), dict(good, in_stock=None)]:
            self.assertFalse(target.valid_product(old, bad))

    def test_resume_keeps_indexes_and_retries_failures_last(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                products = [{'url': 'done', 'name': 'Existing'}, {'url': 'bad', 'needs_revalidation': True}, {'url': 'ok', 'needs_revalidation': True}]
                Path('products.json').write_text(json.dumps(products))
                with patch.object(target, 'scrape_product', return_value=None):
                    report = target.run(limit=1, pause=0)
                self.assertEqual(report['remaining'], 2)
                fresh = {'url': 'ok', 'name': 'Verified', 'price': 20, 'in_stock': True}
                with patch.object(target, 'scrape_product', return_value=fresh) as scraper:
                    report = target.run(limit=1, pause=0)
                scraper.assert_called_once_with('ok')
                result = json.loads(Path('products.json').read_text())
                self.assertEqual(result[0], products[0])
                self.assertFalse(result[1]['in_stock'])
                self.assertEqual(result[2], fresh)
                self.assertEqual(report['remaining'], 1)
            finally:
                os.chdir(previous)

if __name__ == '__main__':
    unittest.main()
