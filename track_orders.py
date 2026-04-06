"""
track_orders.py
---------------
רץ כל 10 דקות דרך GitHub Actions.
בודק את סטטוס כל הזמנה פעילה באתר של אבא,
ומעדכן את מסד הנתונים המקומי אוטומטית.
"""

import requests
import json
import os
from datetime import datetime

BASE_URL = os.environ.get("SOURCE_WC_URL", "https://www.seferkodesh.co.il")
CK = os.environ.get("SOURCE_WC_KEY", "")
CS = os.environ.get("SOURCE_WC_SECRET", "")
ORDERS_FILE = "orders.json"

# סטטוסים שקשורים לתשלום — לא מסנכרנים (מנוהלים באתר שלנו בלבד)
PAYMENT_STATUSES = {"pending", "on-hold", "failed", "cancelled"}

# תרגום סטטוסים לעברית
STATUS_LABELS = {
    "pending":           "ממתין לתשלום",
    "processing":        "בטיפול",
    "on-hold":           "בהמתנה",
    "completed":         "הושלם",
    "cancelled":         "בוטל",
    "refunded":          "הוחזר",
    "failed":            "נכשל",
    "checkout-draft":    "טיוטה",
    # סטטוסים מותאמים אישית של האתר המקורי
    "wc-pending":                    "ממתין לתשלום",
    "wc-processing":                 "בטיפול",
    "wc-on-hold":                    "בהמתנה",
    "wc-completed":                  "הושלם",
    "wc-cancelled":                  "בוטל",
    "wc-refunded":                   "הוחזר",
    "wc-failed":                     "נכשל",
    "wc-shipped":                    "נשלח",
    "wc-delivered":                  "הגיע",
    "wc-awaiting-shipment":          "ממתין למשלוח",
    "wc-awaiting-pickup":            "ממתין לאיסוף",
    "wc-pickup":                     "מוכן לאיסוף",
    "wc-ready-for-pickup":           "מוכן לאיסוף",
    "wc-in-transit":                 "בדרך",
    "wc-out-for-delivery":           "יצא למסירה",
    "wc-partially-shipped":          "נשלח חלקית",
    "wc-partially-refunded":         "הוחזר חלקית",
    "wc-exchange":                   "בהמרה",
    "wc-return-requested":           "בקשת החזרה",
    "wc-returning":                  "בתהליך החזרה",
    "wc-awaiting-payment":           "ממתין לתשלום",
    "wc-pending-payment":            "ממתין לתשלום",
    "wc-payment-pending":            "ממתין לתשלום",
    "wc-authorization-required":     "נדרש אישור",
    "wc-awaiting-fulfillment":       "ממתין לטיפול",
    "wc-in-production":              "בייצור",
    "wc-backordered":                "בהזמנה מוקדמת",
    "wc-pre-ordered":                "הוזמן מראש",
}

# צבעים לסטטוסים
STATUS_COLORS = {
    "בטיפול":           "#1a6bbf",
    "נשלח":             "#7b3fbf",
    "בדרך":             "#7b3fbf",
    "יצא למסירה":       "#e67e00",
    "הגיע":             "#1a7a3a",
    "הושלם":            "#1a7a3a",
    "מוכן לאיסוף":      "#e67e00",
    "ממתין למשלוח":     "#6b6b6b",
    "בוטל":             "#c0392b",
    "הוחזר":            "#c0392b",
}


def auth_header():
    import base64
    token = base64.b64encode(f"{CK}:{CS}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def load_orders():
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def get_source_order_status(source_order_id):
    """שולף סטטוס הזמנה מהאתר המקורי"""
    if not CK or not CS:
        print("  ⚠️ מפתחות API לא מוגדרים — לא ניתן לסנכרן סטטוסים")
        return None

    try:
        res = requests.get(
            f"{BASE_URL}/wp-json/wc/v3/orders/{source_order_id}",
            headers=auth_header(),
            timeout=10,
        )
        if res.ok:
            data = res.json()
            return data.get("status", "")
    except Exception as e:
        print(f"  ⚠️ שגיאה בשליפת סטטוס {source_order_id}: {e}")
    return None


def translate_status(raw_status):
    """מתרגם סטטוס גולמי לעברית"""
    return STATUS_LABELS.get(raw_status, STATUS_LABELS.get(f"wc-{raw_status}", raw_status))


def should_sync(raw_status):
    """האם לסנכרן את הסטטוס הזה? (לא מסנכרנים סטטוסי תשלום)"""
    clean = raw_status.replace("wc-", "")
    return clean not in PAYMENT_STATUSES


def main():
    print(f"🔄 בדיקת סטטוסי הזמנות — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    orders = load_orders()
    active_orders = {
        oid: o for oid, o in orders.items()
        if o.get("our_status") not in ["completed", "cancelled", "refunded"]
    }

    print(f"📦 הזמנות פעילות לבדיקה: {len(active_orders)}")
    updated_count = 0

    for our_order_id, order in active_orders.items():
        source_id = order.get("source_order_id")
        if not source_id:
            continue

        print(f"  בודק הזמנה #{our_order_id} (מקור: #{source_id})")
        raw_status = get_source_order_status(source_id)

        if raw_status and should_sync(raw_status):
            new_status_he = translate_status(raw_status)
            old_status_he = order.get("status_he", "")

            if new_status_he != old_status_he:
                order["raw_status"] = raw_status
                order["status_he"] = new_status_he
                order["status_color"] = STATUS_COLORS.get(new_status_he, "#6b6b6b")
                order["our_status"] = raw_status.replace("wc-", "")
                order["last_updated"] = datetime.now().isoformat()

                # שמירת היסטוריה
                if "history" not in order:
                    order["history"] = []
                order["history"].append({
                    "status": new_status_he,
                    "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
                })

                orders[our_order_id] = order
                updated_count += 1
                print(f"  ✅ עודכן: {old_status_he} → {new_status_he}")
            else:
                print(f"  — ללא שינוי ({new_status_he})")

    save_orders(orders)
    print(f"\n✅ סנכרון הושלם — {updated_count} הזמנות עודכנו")


if __name__ == "__main__":
    main()
