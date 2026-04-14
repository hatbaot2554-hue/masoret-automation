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


def calc_our_price(base):
    with_markup = base + max(base * 0.15, 2)
    if with_markup < 20:
        return round(with_markup * 2) / 2
    return round(with_markup)


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


def parse_price(el):
    if not el:
        return 0.0
    text = el.get_text(strip=True).replace("₪", "").replace(",", "").replace("\xa0", "").strip()
    try:
        return float(text)
    except:
        return 0.0


def scrape_product(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        # שם המוצר
        name = ""
        title_el = soup.select_one("h1.product_title, h1.entry-title")
        if title_el:
            name = title_el.get_text(strip=True)

        # מחיר
        sale_price = 0.0
        regular_price = 0.0
        sale_el = soup.select_one("p.price ins .woocommerce-Price-amount bdi")
        regular_el = soup.select_one("p.price del .woocommerce-Price-amount bdi")
        if sale_el:
            sale_price = parse_price(sale_el)
            regular_price = parse_price(regular_el) if regular_el else sale_price
        else:
            price_el = soup.select_one("p.price .woocommerce-Price-amount bdi")
            if not price_el:
                price_el = soup.select_one(".woocommerce-Price-amount bdi")
            regular_price = parse_price(price_el)
            sale_price = regular_price

        current_price = sale_price if sale_price > 0 else regular_price

        if not name or current_price < 1:
            return None

        # מק"ט
        sku = ""
        sku_el = soup.select_one(".sku_wrapper .sku, span.sku")
        if sku_el:
            sku = sku_el.get_text(strip=True)

        # מזהה מוצר
        product_id = ""
        add_to_cart = soup.select_one("button.single_add_to_cart_button, [name='add-to-cart']")
        if add_to_cart:
            product_id = add_to_cart.get("value", "")
        if not product_id:
            form = soup.select_one("form.cart")
            if form:
                product_id = form.get("data-product_id", "")

        # תיאור קצר
        description = ""
        desc_el = soup.select_one("div.woocommerce-product-details__short-description")
        if desc_el:
            description = desc_el.get_text(separator=" ", strip=True)[:500]

        # תיאור מלא
        full_description = ""
        full_desc_el = soup.select_one("div#tab-description div.woocommerce-Tabs-panel--description, div.entry-content")
        if full_desc_el:
            full_description = full_desc_el.get_text(separator=" ", strip=True)[:2000]

        # תמונה ראשית
        image = ""
        img_el = soup.select_one("div.woocommerce-product-gallery img, .wp-post-image")
        if img_el:
            image = img_el.get("src", img_el.get("data-src", ""))

        # גלריית תמונות
        images = []
        gallery_imgs = soup.select("div.woocommerce-product-gallery__image img, figure.woocommerce-product-gallery__image img")
        for img in gallery_imgs:
            src = img.get("data-large_image") or img.get("data-src") or img.get("src", "")
            if src and src not in images:
                images.append(src)
        if not images and image:
            images = [image]

        # קטגוריות מ-breadcrumb — הורה + ילד
        parent_category = ""
        child_category = ""
        category = ""

        breadcrumb_links = soup.select(".woocommerce-breadcrumb a, nav.woocommerce-breadcrumb a")
        # מסנן רק קישורים שמכילים /product-category/
        cat_links = [a for a in breadcrumb_links if "/product-category/" in a.get("href", "")]

        if len(cat_links) >= 2:
            parent_category = cat_links[-2].get_text(strip=True)
            child_category = cat_links[-1].get_text(strip=True)
            category = child_category
        elif len(cat_links) == 1:
            parent_category = cat_links[0].get_text(strip=True)
            child_category = ""
            category = parent_category
        else:
            # fallback — posted_in
            cat_els = soup.select("span.posted_in a")
            all_cats = [c.get_text(strip=True) for c in cat_els if c.get_text(strip=True)]
            if len(all_cats) >= 2:
                parent_category = all_cats[0]
                child_category = all_cats[-1]
                category = child_category
            elif len(all_cats) == 1:
                parent_category = all_cats[0]
                category = parent_category

        # כל הקטגוריות
        categories = []
        cat_els_all = soup.select("span.posted_in a")
        for c in cat_els_all:
            t = c.get_text(strip=True)
            if t:
                categories.append(t)

        # תגיות
        tags = []
        tag_els = soup.select("span.tagged_as a")
        for t in tag_els:
            tags.append(t.get_text(strip=True))

        # מלאי
        in_stock = True
        stock_text_display = ""
        stock_el = soup.select_one("p.stock, .stock")
        if stock_el:
            stock_text = stock_el.get_text(strip=True)
            stock_text_display = stock_text
            if any(word in stock_text for word in ["אזל", "חסר", "out of stock", "Out of stock"]):
                in_stock = False

        # וריאציות
        variations = []
        variation_data = soup.select_one("form.variations_form")
        if variation_data:
            raw = variation_data.get("data-product_variations", "")
            if raw:
                try:
                    var_list = json.loads(raw)
                    for v in var_list:
                        var_price = v.get("display_price", 0)
                        var_regular = v.get("display_regular_price", var_price)
                        var_attrs = v.get("attributes", {})
                        var_image = ""
                        if v.get("image", {}).get("src"):
                            var_image = v["image"]["src"]
                        variations.append({
                            "variation_id": v.get("variation_id", ""),
                            "sku": v.get("sku", ""),
                            "attributes": var_attrs,
                            "original_price": round(float(var_price), 2),
                            "regular_price": round(float(var_regular), 2),
                            "price": calc_our_price(float(var_price)),
                            "regular_our_price": calc_our_price(float(var_regular)),
                            "in_stock": v.get("is_in_stock", True),
                            "image": var_image,
                        })
                except:
                    pass

        # שמות האופציות
        attribute_labels = {}
        select_els = soup.select("table.variations tr")
        for row in select_els:
            label_el = row.select_one("label")
            select_el = row.select_one("select")
            if label_el and select_el:
                label = label_el.get_text(strip=True)
                name_attr = select_el.get("name", "")
                attribute_labels[name_attr] = label

        return {
            "url": url,
            "product_id": product_id,
            "sku": sku,
            "name": name,
            "original_price": round(current_price, 2),
            "regular_price": round(regular_price, 2),
            "price": calc_our_price(current_price),
            "regular_our_price": calc_our_price(regular_price),
            "description": description,
            "full_description": full_description,
            "image": image,
            "images": images,
            "category": category,
            "parent_category": parent_category,
            "child_category": child_category,
            "categories": categories,
            "tags": tags,
            "in_stock": in_stock,
            "stock_text": stock_text_display,
            "variations": variations,
            "attribute_labels": attribute_labels,
            "last_updated": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"  שגיאה: {e}")
        return None


def products_are_different(old, new):
    fields_to_check = [
        "name", "original_price", "regular_price", "price", "regular_our_price",
        "description", "full_description", "image", "images", "category",
        "parent_category", "child_category", "categories", "tags", "in_stock",
        "stock_text", "variations", "attribute_labels", "sku", "product_id"
    ]
    for field in fields_to_check:
        if old.get(field) != new.get(field):
            return True, field
    return False, None


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
                changed, field = products_are_different(old, product)
                if changed:
                    products_dict[url] = product
                    updated += 1
                    print(f"  🔄 עודכן [{field}]: {product['name']}")
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
