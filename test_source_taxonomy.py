import unittest
from sync_source_taxonomy import build_tree, build_navigation, reconcile


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.categories = [dict(id=1, name='Root', parent=0),
                           dict(id=2, name='Child', parent=1),
                           dict(id=3, name='Leaf &amp; Name', parent=2)]

    def test_all_levels(self):
        tree = build_tree(self.categories)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['nodes'][0]['children'][0]['name'], 'Leaf & Name')

    def test_invalid_tree_rejected(self):
        for categories in [[dict(id=1, name='A', parent=2)],
                           [dict(id=1, name='A', parent=1)]]:
            with self.assertRaises(ValueError):
                build_tree(categories)

    def test_visible_menu_grouping(self):
        categories = [dict(id=1, name='Book', parent=0, permalink='/product-category/book/'),
                      dict(id=2, name='Other', parent=0, permalink='/product-category/other/')]
        menu = '<li class="sk-menu-item"><button class="sk-parent-control"><span aria-hidden="true">icon</span><span>Group</span></button><ul class="sk-submenu"><li><a href="/product-category/book/">Book</a></li></ul></li>'
        tree = build_navigation(categories, menu)
        self.assertEqual([node['parent'] for node in tree], ['Group', 'Other'])
        self.assertEqual(tree[0]['nodes'][0]['id'], 1)
        with self.assertRaises(ValueError):
            build_navigation(categories, '<html></html>')

    def test_indices_preserved_and_membership_exact(self):
        old = [dict(product_id=8, url='/old', price=12, categories=['Wrong']),
               dict(product_id=9, url='/removed', in_stock=True)]
        source = [dict(id=8, name='Book', permalink='/new', categories=[self.categories[2]]),
                  dict(id=10, name='Missing', permalink='/missing', categories=[])]
        updated, matched, absent, missing = reconcile(old, source, self.categories)
        self.assertEqual([p['product_id'] for p in updated], [8, 9])
        self.assertEqual(updated[0]['source_category_ids'], [3])
        self.assertEqual(updated[0]['price'], 12)
        self.assertFalse(updated[1]['in_stock'])
        self.assertEqual((matched, absent, missing[0]['id']), (1, [1], 10))

    def test_reused_url_cannot_change_product_identity(self):
        old = [dict(product_id=8, url='/reused', in_stock=True)]
        source = [dict(id=9, name='Different', permalink='/reused', categories=[])]
        updated, matched, absent, missing = reconcile(old, source, self.categories)
        self.assertEqual(matched, 0)
        self.assertTrue(updated[0]['source_catalog_missing'])
        self.assertFalse(updated[0]['in_stock'])
        self.assertEqual(missing[0]['id'], 9)


if __name__ == '__main__':
    unittest.main()
