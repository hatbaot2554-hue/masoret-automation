import unittest
from scrape_products import stable_product_merge, extract_product_id
from bs4 import BeautifulSoup


class StableCatalogTests(unittest.TestCase):
    def test_out_of_stock_identity_without_cart(self):
        soup = BeautifulSoup('<body class="single-product postid-123"><button name="add-to-cart" value="999">Related</button></body>', 'html.parser')
        self.assertEqual(extract_product_id(soup), '123')
        self.assertEqual(extract_product_id(BeautifulSoup('<body>Not a product</body>', 'html.parser')), '')

    def test_positions_duplicates_and_retired_products(self):
        previous = [dict(product_id=1, url='/a', price=10),
                    dict(product_id=2, url='/b'),
                    dict(product_id=1, url='/a', price=10),
                    dict(product_id=3, url='/retired')]
        updates = [dict(product_id=2, url='/b'),
                   dict(product_id=1, url='/renamed', price=12),
                   dict(product_id=4, url='/new')]
        merged = stable_product_merge(previous, updates)
        self.assertEqual([p['product_id'] for p in merged], [1, 2, 1, 3, 4])
        self.assertEqual(merged[0]['price'], 12)
        self.assertEqual(merged[2]['price'], 12)

    def test_redirect_to_different_product_does_not_replace_original(self):
        merged = stable_product_merge([dict(product_id=1, url='/old')],
                                      [dict(product_id=2, url='/new')])
        self.assertEqual([p['product_id'] for p in merged], [1, 2])

    def test_newly_discovered_id_keeps_existing_url_position(self):
        merged = stable_product_merge([dict(url='/same')], [dict(product_id=5, url='/same')])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['product_id'], 5)


if __name__ == '__main__':
    unittest.main()
