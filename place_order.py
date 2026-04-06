"""
place_order.py
--------------
כשלקוח מזמין באתר החדש — הסקריפט הזה:
1. נכנס לאתר של אבא
2. ממצא את דף המוצר הנכון
3. ממלא את פרטי הלקוח
4. מזין קוד הנחה אם קיים
5. שולח את ההזמנה

מופעל אוטומטית על ידי webhook מהאתר החדש.
"""

import time
import json
import os
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


BASE_URL = "https://www.seferkodesh.co.il"
DISCOUNT_CODE = os.environ.get("DISCOUNT_CODE", "")  # קוד הנחה אם יש


def create_driver():
    """יוצר דפדפן Chrome בלתי נראה"""
    options = Options()
    options.add_argument("--headless")       # רץ ברקע ללא חלון
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def add_to_cart(driver, product_url):
    """מוסיף מוצר לעגלה באתר המקורי"""
    print(f"  🛒 מוסיף לעגלה: {product_url}")
    driver.get(product_url)
    wait = WebDriverWait(driver, 10)

    try:
        # לחיצה על כפתור "הוסף לעגלה"
        add_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "button.single_add_to_cart_button, .add_to_cart_button"
            ))
        )
        add_btn.click()
        time.sleep(2)
        print("  ✅ נוסף לעגלה")
        return True
    except Exception as e:
        print(f"  ❌ שגיאה בהוספה לעגלה: {e}")
        return False


def go_to_checkout(driver):
    """עובר לעמוד תשלום"""
    print("  🔄 עובר לתשלום...")
    driver.get(f"{BASE_URL}/checkout/")
    time.sleep(2)


def fill_checkout_form(driver, customer):
    """ממלא פרטי לקוח בטופס התשלום"""
    wait = WebDriverWait(driver, 10)
    print("  📝 ממלא פרטי לקוח...")

    fields = {
        "billing_first_name": customer["first_name"],
        "billing_last_name":  customer["last_name"],
        "billing_email":      customer["email"],
        "billing_phone":      customer["phone"],
        "billing_address_1":  customer["address"],
        "billing_city":       customer["city"],
    }

    for field_id, value in fields.items():
        try:
            el = wait.until(EC.presence_of_element_located((By.ID, field_id)))
            el.clear()
            el.send_keys(value)
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ שדה {field_id}: {e}")

    # בחירת מדינה ישראל אם נדרש
    try:
        country_select = driver.find_element(By.ID, "billing_country")
        from selenium.webdriver.support.ui import Select
        Select(country_select).select_by_value("IL")
    except:
        pass

    print("  ✅ פרטים מולאו")


def apply_discount_code(driver, code):
    """מזין קוד הנחה"""
    if not code:
        return

    print(f"  🏷️ מזין קוד הנחה: {code}")
    try:
        # לחיצה על "יש לי קוד קופון"
        toggle = driver.find_element(By.CSS_SELECTOR,
            ".showcoupon, a.showcoupon, [data-toggle='coupon']"
        )
        toggle.click()
        time.sleep(1)

        coupon_input = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "coupon_code"))
        )
        coupon_input.send_keys(code)

        apply_btn = driver.find_element(By.CSS_SELECTOR,
            "button[name='apply_coupon'], .coupon button"
        )
        apply_btn.click()
        time.sleep(2)
        print("  ✅ קוד הנחה הוחל")
    except Exception as e:
        print(f"  ⚠️ לא ניתן להחיל קוד הנחה: {e}")


def submit_order(driver):
    """שולח את ההזמנה"""
    print("  📤 שולח הזמנה...")
    try:
        # בחירת תשלום בהעברה בנקאית (הכי פשוט, לא דורש כרטיס)
        try:
            bacs = driver.find_element(By.ID, "payment_method_bacs")
            bacs.click()
            time.sleep(0.5)
        except:
            pass

        # לחיצה על "בצע הזמנה"
        place_order_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "place_order"))
        )
        place_order_btn.click()
        time.sleep(4)

        # בדיקה שההזמנה עברה
        if "order-received" in driver.current_url or "thank" in driver.current_url.lower():
            print("  ✅ הזמנה בוצעה בהצלחה!")
            return True
        else:
            print(f"  ⚠️ URL לאחר הזמנה: {driver.current_url}")
            return False

    except Exception as e:
        print(f"  ❌ שגיאה בשליחת הזמנה: {e}")
        return False


def place_order(order_data):
    """
    הפונקציה הראשית — מבצעת הזמנה מלאה באתר המקורי.

    order_data = {
        "product_url": "https://www.seferkodesh.co.il/product-page/...",
        "customer": {
            "first_name": "ישראל",
            "last_name": "ישראלי",
            "email": "israel@example.com",
            "phone": "050-1234567",
            "address": "רחוב הרצל 1",
            "city": "תל אביב"
        },
        "discount_code": "SALE10"  # אופציונלי
    }
    """
    driver = None
    try:
        print(f"\n🤖 מתחיל אוטומציית הזמנה...")
        print(f"   מוצר: {order_data['product_url']}")
        print(f"   לקוח: {order_data['customer']['first_name']} {order_data['customer']['last_name']}")

        driver = create_driver()

        # שלב 1: הוספה לעגלה
        if not add_to_cart(driver, order_data["product_url"]):
            raise Exception("לא ניתן להוסיף לעגלה")

        # שלב 2: מעבר לתשלום
        go_to_checkout(driver)

        # שלב 3: קוד הנחה
        discount = order_data.get("discount_code") or DISCOUNT_CODE
        if discount:
            apply_discount_code(driver, discount)

        # שלב 4: מילוי פרטים
        fill_checkout_form(driver, order_data["customer"])

        # שלב 5: שליחת הזמנה
        success = submit_order(driver)

        return {"success": success}

    except Exception as e:
        print(f"\n❌ שגיאה: {e}")
        return {"success": False, "error": str(e)}

    finally:
        if driver:
            driver.quit()


# ===== הפעלה ישירה לבדיקה =====
if __name__ == "__main__":
    # דוגמה לבדיקה
    test_order = {
        "product_url": "https://www.seferkodesh.co.il/product-page/רוח-חיים/",
        "customer": {
            "first_name": "ישראל",
            "last_name": "ישראלי",
            "email": "test@example.com",
            "phone": "050-1234567",
            "address": "רחוב הרצל 1",
            "city": "תל אביב",
        },
        "discount_code": ""
    }

    result = place_order(test_order)
    print(f"\nתוצאה: {result}")
