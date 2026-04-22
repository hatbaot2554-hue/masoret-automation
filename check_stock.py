import json
import requests
import os

PRODUCTS_URL = "https://raw.githubusercontent.com/hatbaot2554-hue/masoret-automation/refs/heads/main/products.json"
DASHBOARD_API = os.environ.get("DASHBOARD_API_URL", "https://masoret-dashboard.vercel.app")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

def get_products():
    res = requests.get(PRODUCTS_URL)
    res.raise_for_status()
    return res.json()

def get_waitlist():
    res = requests.get(f"{DASHBOARD_API}/api/waitlist")
    if res.ok:
        return res.json()
    return []

def send_email(to_email, product_name, product_index):
    product_url = f"https://masoret-website.vercel.app/products/{product_index}"
    html = f"""
    <div dir="rtl" style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: #1A2332; padding: 24px; text-align: center;">
        <h1 style="color: #C9A84C; margin: 0; font-size: 22px;">המרכז למסורת יהודית</h1>
      </div>
      <div style="padding: 32px; background: #F8F4EE;">
        <h2 style="color: #1A2332; margin-bottom: 16px;">🎉 הספר חזר למלאי!</h2>
        <p style="color: #2C2416; font-size: 16px; line-height: 1.8;">
          שלום,<br><br>
          הספר שביקשת להתעדכן לגביו חזר למלאי:
        </p>
        <div style="background: #fff; border: 1px solid #EDE6D9; border-right: 4px solid #C9A84C; padding: 16px; margin: 20px 0; border-radius: 4px;">
          <strong style="color: #1A2332; font-size: 16px;">📚 {product_name}</strong>
        </div>
        <a href="{product_url}"
           style="display: inline-block; background: #C9A84C; color: #1A2332; padding: 14px 32px; text-decoration: none; font-weight: 700; font-size: 16px; border-radius: 4px; margin-top: 8px;">
          לרכישה ←
        </a>
        <p style="color: #6B5C3E; font-size: 12px; margin-top: 24px;">
          מיהרו — המלאי מוגבל!
        </p>
      </div>
      <div style="background: #1A2332; padding: 16px; text-align: center;">
        <p style="color: rgba(255,255,255,0.5); font-size: 12px; margin: 0;">
          © המרכז למסורת יהודית |
          <a href="https://masoret-website.vercel.app" style="color: #C9A84C; text-decoration: none;">לאתר</a>
        </p>
      </div>
    </div>
    """
    res = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "from": "onboarding@resend.dev",
            "to": to_email,
            "subject": f"✅ {product_name} — חזר למלאי!",
            "html": html
        }
    )
    print(f"  Resend status: {res.status_code} — {res.text[:100]}")
    return res.ok

def main():
    print("בודק חזרת מוצרים למלאי...")
    try:
        products = get_products()
    except Exception as e:
        print(f"שגיאה בטעינת מוצרים: {e}")
        return

    waitlist = get_waitlist()
    if not waitlist:
        print("רשימת המתנה ריקה — אין מה לשלוח")
        return

    print(f"נמצאו {len(waitlist)} רשומות ברשימת המתנה")
    notified_ids = []

    for entry in waitlist:
        product_index = entry.get("productIndex")
        email = entry.get("email")
        product_name = entry.get("productName", "")
        entry_id = entry.get("id")

        if product_index is None or not email:
            continue
        if product_index >= len(products):
            continue

        product = products[product_index]
        in_stock = product.get("in_stock", True)

        # אם המוצר חזר למלאי — שולחים מייל
        if in_stock is not False:
            name = product.get("name", product_name)
            print(f"שולח מייל ל-{email} על: {name}")
            success = send_email(email, name, product_index)
            if success:
                notified_ids.append(entry_id)
                print(f"  ✅ נשלח בהצלחה")
            else:
                print(f"  ❌ שגיאה בשליחה")
        else:
            print(f"  ⏳ {product_name} עדיין לא במלאי")

    # סימון רשומות שנשלחו
    if notified_ids:
        cleanup_res = requests.post(
            f"{DASHBOARD_API}/api/waitlist/cleanup",
            json={"ids": notified_ids},
            headers={"Content-Type": "application/json"}
        )
        print(f"נמחקו {len(notified_ids)} רשומות — status: {cleanup_res.status_code}")

if __name__ == "__main__":
    main()
