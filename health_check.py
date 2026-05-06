import json
import os
from pathlib import Path

REQUIRED_SECRETS = [
    ("DATABASE_URL", "מסד נתונים"),
    ("RESEND_API_KEY", "שליחת מיילים"),
    ("SOURCE_EMAIL", "אימייל לאתר המקורי"),
    ("SOURCE_PASSWORD", "סיסמה לאתר המקורי"),
]

OPTIONAL_SECRETS = [
    ("AUTO_ORDER_SUBMIT", "אישור שליחת הזמנות בפועל"),
]


def status_line(name: str, label: str, required: bool = True) -> tuple[bool, str]:
    exists = bool(os.getenv(name, "").strip())
    if exists:
        return True, f"✅ {label}: מוגדר ({name})"
    if required:
        return False, f"❌ {label}: חסר ({name})"
    return True, f"⚠️ {label}: לא מוגדר ({name})"


def products_stats() -> tuple[bool, list[str]]:
    path = Path("products.json")
    if not path.exists():
        return False, ["❌ products.json לא נמצא"]

    try:
        products = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"❌ products.json לא תקין: {exc}"]

    if not isinstance(products, list):
        return False, ["❌ products.json לא מכיל רשימת מוצרים"]

    with_product_id = sum(1 for product in products if product.get("product_id"))
    with_sku = sum(1 for product in products if product.get("sku"))
    with_images = sum(1 for product in products if product.get("image") or product.get("images"))
    in_stock = sum(1 for product in products if product.get("in_stock") is not False)

    ok = len(products) > 0 and with_product_id > 0
    return ok, [
        f"✅ מוצרים בקובץ: {len(products):,}",
        f"✅ עם מזהה מוצר: {with_product_id:,}",
        f"✅ עם מקט: {with_sku:,}",
        f"✅ עם תמונות: {with_images:,}",
        f"✅ זמינים במלאי: {in_stock:,}",
    ]


def main() -> int:
    print("# בדיקת מערכת - אוטומציית הזמנות")
    print("הבדיקה לא מדפיסה ערכי סודות, רק האם הם קיימים.\n")

    all_ok = True

    print("## סודות נדרשים")
    for name, label in REQUIRED_SECRETS:
        ok, line = status_line(name, label, required=True)
        all_ok = all_ok and ok
        print(line)

    print("\n## סודות אופציונליים")
    for name, label in OPTIONAL_SECRETS:
        ok, line = status_line(name, label, required=False)
        print(line)
        if name == "AUTO_ORDER_SUBMIT" and os.getenv(name, "").strip().lower() == "true":
            print("⚠️ AUTO_ORDER_SUBMIT=true: האוטומציה רשאית לשלוח הזמנות בפועל לאתר המקורי.")

    print("\n## קטלוג מוצרים")
    catalog_ok, lines = products_stats()
    all_ok = all_ok and catalog_ok
    for line in lines:
        print(line)

    print("\n## סיכום")
    if all_ok:
        print("✅ בדיקת האוטומציה עברה.")
        return 0

    print("❌ יש פריטים שדורשים טיפול לפני הפעלה מלאה.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
