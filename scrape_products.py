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
PROGRESS_FILE = "progress.json"
URLS_FILE = "all_urls.json"
BATCH_SIZE = 500
MAX_MINUTES = 300

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def load_json(filename, default):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_all_product_urls():
    if os.path.exists(URLS_FILE):
        urls = load_json(URLS_FILE, [])
        if urls:
            print(f"📋 נטען קובץ URLs קיים: {len(urls)} כתובות")
            return urls

    print("🌐 סורק עמודי חנות לאיסוף כתובות...")
    urls = set()
    page = 1

    while True:
        try:
            url = f"{BASE_URL}/shop/page/{page}/" if page > 1 else f"{BASE_URL}/shop/"
            res = requests.get(url, headers=HEADERS, timeout=15)
            if res.status_code == 404:
                break
            soup = BeautifulSoup(res.text, "html.parser")
            product_links = soup.select("a.woocommerce-LoopProduct-link, ul.products li a")
            found = set()
            for a in product_links:
                href = a.get("href", "")
                if "/product-page/" in href or "/product/" in href:
                    found.add(href.split("?")[0])
            if not found:
                break
            urls.update(found)
            print(f"  עמוד {page}: {len(found)} מוצרים (סה\"כ: {len(urls)})")
            page += 1
            time.sleep(1)
        except Exception as e:
            print(f"  שגיאה בעמוד {page}: {e}")
            break

    urls_list = list(urls)
    save_json(URLS_FILE, urls_list)
    print(f"\n✅ נשמרו {len(urls_list)} כתובות")
    return urls_list


def scrape_product(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        # שם המוצר
        name = ""
        title_el = soup.select_one("h1.product_title, h1.entry-title")
        if title_el:
            name = title_el.get_text(strip=True)

        # מחיר — מנסה כמה selectors
        price = 0.0
        for selector in [
            ".price ins .woocommerce-Price-amount",
            ".price .woocommerce-Price-amount",
            "p.price .amount",
            ".summary .price .amount",
        ]:
            price_el = soup.select_one(selector)
            if price_el:
                price_text = price_el.get_text(strip=True)
                price_text = price_text.replace("₪", "").replace(",", "").replace("\xa0", "").strip()
                try:
                    val = float(price_text)
                    if val > 0:
                        price = val
                        break
                except:
                    continue

        # דלג על מוצרים ללא מחיר תקין
        if not name or price < 1:
            return None

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
        stock_el = soup.select_one("p.stock, .stock")
        if stock_el:
            stock_text = stock_el.get_text(strip=True)
            if any(word in stock_text for word in ["אזל", "חסר", "out of stock", "Out of stock"]):
                in_stock = False

        # חישוב מחיר עם תוספת 15% ועיגול
        marked_price = price * PRICE_MARKUP
        if marked_price > 10:
            marked_price = round(marked_price)
        else:
            marked_price = round(marked_price, 2)

        return {
            "url": url,
            "name": name,
            "original_price": round(price, 2),
            "price": marked_price,
            "description": description,
            "image": image,
            "category": category,
            "in_stock": in_stock,
            "last_updated": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"  שגיאה: {e}")
        return None


def main():
    start_time = datetime.now()
    print(f"🔍 מתחיל סריקה — {start_time.strftime('%d/%m/%Y %H:%M')}")

    products = load_json(PRODUCTS_FILE, [])
    products_dict = {p["url"]: p for p in products}
    progress = load_json(PROGRESS_FILE, {"last_index": 0, "completed": False})

    print(f"📦 מוצרים קיימים: {len(products_dict)}")
    print(f"📍 המשך מאינדקס: {progress['last_index']}")

    if progress.get("completed"):
        print("✅ סריקה ראשונה הושלמה! עובר למצב עדכונים...")
        urls = load_json(URLS_FILE, [])
        updated = 0
        for url in urls:
            elapsed = (datetime.now() - start_time).seconds / 60
            if elapsed > MAX_MINUTES:
                break
            product = scrape_product(url)
            if product:
                old = products_dict.get(url, {})
                if old.get("original_price") != product["original_price"] or old.get("in_stock") != product["in_stock"]:
                    products_dict[url] = product
                    updated += 1
                    print(f"  💰 עודכן: {product['name']}")
            time.sleep(0.5)
        save_json(PRODUCTS_FILE, list(products_dict.values()))
        print(f"\n✅ עדכון הושלם — {updated} מוצרים שונו")
        return

    all_urls = get_all_product_urls()
    total = len(all_urls)
    start_idx = progress["last_index"]
    end_idx = min(start_idx + BATCH_SIZE, total)

    print(f"\n📊 סורק {start_idx+1} עד {end_idx} מתוך {total} מוצרים...")

    for i in range(start_idx, end_idx):
        elapsed = (datetime.now() - start_time).seconds / 60
        if elapsed > MAX_MINUTES:
            print(f"\n⏰ הגענו ל-{MAX_MINUTES} דקות — עוצרים לשמירה")
            break

        url = all_urls[i]
        print(f"[{i+1}/{total}] {url.split('/')[-2][:40]}")

        product = scrape_product(url)
        if product:
            products_dict[url] = product

        progress["last_index"] = i + 1
        time.sleep(0.5)

    if progress["last_index"] >= total:
        progress["completed"] = True
        print(f"\n🎉 סריקה ראשונה הושלמה!")
    else:
        remaining = total - progress["last_index"]
        print(f"\n💾 נשארו {remaining} מוצרים לסריקות הבאות")

    save_json(PRODUCTS_FILE, list(products_dict.values()))
    save_json(PROGRESS_FILE, progress)
    print(f"✅ נשמרו {len(products_dict)} מוצרים")


if __name__ == "__main__":
    main()
