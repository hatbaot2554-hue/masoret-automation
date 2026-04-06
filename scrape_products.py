"""
scrape_products.py
------------------
רץ כל יום דרך GitHub Actions.
סורק את seferkodesh.co.il, מזהה מוצרים חדשים ושינויים,
ושומר הכל בקובץ products.json שמשמש את האתר החדש.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime

BASE_URL = "https://www.seferkodesh.co.il"
PRICE_MARKUP = 1.15
PRODUCTS_FILE = "products.json"
CHANGES_FILE = "last_changes.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def get_all_product_urls():
    """אוסף את כל כתובות המוצרים מהאתר"""
    urls = set()
    page = 1

    while True:
        try:
            url = f"{BASE_URL}/shop/page/{page}/" if page > 1 else f"{BASE_URL}/shop/"
            res = requests.get(url, headers=HEADERS, timeout=15)

            if res.status_code == 404:
                break

            soup = BeautifulSoup(res.text, "html.parser")

            # מוצא קישורים למוצרים
            product_links = soup.select("a.woocommerce-LoopProduct-link, ul.products li a")
            found = set()
            for a in product_links:
                href = a.get("href", "")
                if "/product-page/" in href or "/product/" in href:
                    found.add(href.split("?")[0])

            if not found:
                break

            urls.update(found)
            print(f"  עמוד {page}: נמצאו {len(found)} מוצרים (סה\"כ: {len(urls)})")
            page += 1
            time.sleep(1)  # המתנה מנומסת בין בקשות

        except Exception as e:
            print(f"  שגיאה בעמוד {page}: {e}")
            break

    return list(urls)


def scrape_product(url):
    """שולף פרטי מוצר בודד"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        # שם המוצר
        name = ""
        title_el = soup.select_one("h1.product_title, h1.entry-title")
        if title_el:
            name = title_el.get_text(strip=True)

        # מחיר
        price = 0.0
        price_el = soup.select_one("p.price .woocommerce-Price-amount, .price ins .amount, .price .amount")
        if price_el:
            price_text = price_el.get_text(strip=True).replace("₪", "").replace(",", "").strip()
            try:
                price = float(price_text)
            except:
                pass

        # תיאור
        description = ""
        desc_el = soup.select_one("div.woocommerce-product-details__short-description, div#tab-description")
        if desc_el:
            description = desc_el.get_text(separator=" ", strip=True)[:500]

        # תמונה
        image = ""
        img_el = soup.select_one("div.woocommerce-product-gallery img, .wp-post-image")
        if img_el:
            image = img_el.get("src", img_el.get("data-src", ""))

        # קטגוריה
        category = ""
        cat_el = soup.select_one("span.posted_in a, .woocommerce-breadcrumb a:last-child")
        if cat_el:
            category = cat_el.get_text(strip=True)

        # זמינות מלאי
        in_stock = True
        stock_el = soup.select_one("p.stock")
        if stock_el and "אזל" in stock_el.get_text():
            in_stock = False

        if not name or price == 0:
            return None

        return {
            "url": url,
            "name": name,
            "original_price": round(price, 2),
            "price": round(price * PRICE_MARKUP, 2),
            "description": description,
            "image": image,
            "category": category,
            "in_stock": in_stock,
            "last_updated": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"  שגיאה ב-{url}: {e}")
        return None


def load_existing():
    """טוען מוצרים קיימים מהקובץ"""
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
            return {p["url"]: p for p in json.load(f)}
    return {}


def save_products(products_dict):
    """שומר את כל המוצרים לקובץ"""
    products_list = list(products_dict.values())
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products_list, f, ensure_ascii=False, indent=2)
    print(f"\n✅ נשמרו {len(products_list)} מוצרים ב-{PRODUCTS_FILE}")


def save_changes(changes):
    """שומר סיכום שינויים"""
    with open(CHANGES_FILE, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)


def main():
    print(f"🔍 מתחיל סריקה — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"   אתר: {BASE_URL}")
    print(f"   תוספת מחיר: {int((PRICE_MARKUP-1)*100)}%\n")

    # טעינת מוצרים קיימים
    existing = load_existing()
    print(f"📦 מוצרים קיימים במערכת: {len(existing)}\n")

    # שליפת כל כתובות המוצרים
    print("🌐 סורק עמודי חנות...")
    urls = get_all_product_urls()
    print(f"\n📋 סה\"כ {len(urls)} מוצרים באתר המקורי\n")

    # סריקת כל מוצר
    changes = {"new": [], "updated": [], "out_of_stock": [], "date": datetime.now().isoformat()}
    updated = dict(existing)

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url.split('/')[-2]}")
        product = scrape_product(url)

        if not product:
            continue

        if url not in existing:
            changes["new"].append(product["name"])
            print(f"  ✨ מוצר חדש: {product['name']}")
        else:
            old = existing[url]
            if old.get("original_price") != product["original_price"]:
                changes["updated"].append({
                    "name": product["name"],
                    "old_price": old.get("price"),
                    "new_price": product["price"],
                })
                print(f"  💰 שינוי מחיר: {old.get('price')} → {product['price']}")
            if not product["in_stock"] and old.get("in_stock"):
                changes["out_of_stock"].append(product["name"])
                print(f"  ❌ אזל מהמלאי: {product['name']}")

        updated[url] = product
        time.sleep(0.5)

    save_products(updated)
    save_changes(changes)

    # סיכום
    print(f"\n📊 סיכום שינויים:")
    print(f"   מוצרים חדשים: {len(changes['new'])}")
    print(f"   שינויי מחיר: {len(changes['updated'])}")
    print(f"   אזלו מהמלאי: {len(changes['out_of_stock'])}")
    print(f"\n✅ הסריקה הושלמה בהצלחה!")


if __name__ == "__main__":
    main()
