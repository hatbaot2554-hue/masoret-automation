import unittest
from datetime import datetime, timezone
from verify_catalog_health import validate_positions, readiness


class CatalogHealthTests(unittest.TestCase):
    def test_reordering_and_deletion_blocked(self):
        old = [dict(product_id=1), dict(product_id=2)]
        for bad in (old[::-1], old[:1], []):
            with self.assertRaises(ValueError):
                validate_positions(old, bad)
        validate_positions(old, old + [dict(product_id=3)])

    def test_incomplete_catalog_is_not_ready(self):
        report = dict(checked_at=datetime.now(timezone.utc).isoformat(), missing_products=1,
                      pending_revalidation=2, source_products=100, source_categories=10)
        self.assertEqual(len(readiness(report)), 2)
        report.update(missing_products=0, pending_revalidation=0)
        self.assertEqual(readiness(report), [])


if __name__ == '__main__':
    unittest.main()
