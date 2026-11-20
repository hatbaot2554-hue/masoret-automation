"""
scrape_products.py
------------------
רץ כל יום דרך GitHub Actions.
סורק את seferkodesh.co.il, מזהה מוצרים חדשים ושינויים,
ושומר הכל בקובץ products.json שמשמש את האתר החדש.
גם סורק את תפריט האתר ושומר ל-categories.json.
"""

import requests
from bs4 import BeautifulSoup
import json
import math
import os
import time
from datetime import datetime
from urllib.parse import unquote, urljoin, urlparse

BASE_URL = "https://www.seferkodesh.co.il"
PRODUCTS_FILE = "products.json"
PROGRESS_FILE = "progress.json"
URLS_FILE = "all_urls.json"
CATEGORIES_FILE = "categories.json"
SITEMAP_CANDIDATES = [
    f"{BASE_URL}/product-sitemap.xml",
    f"{BASE_URL}/wp-sitemap-posts-product-1.xml",
]
CATEGORY_SITEMAP_CANDIDATES = [
    f"{BASE_URL}/product_cat-sitemap.xml",
    f"{BASE_URL}/wp-sitemap-taxonomies-product_cat-1.xml",
]
DEFAULT_BATCH_SIZE = 500
DEFAULT_UPDATE_BATCH_SIZE = 250
DEFAULT_MAX_MINUTES = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


BATCH_SIZE = env_int("SCRAPE_BATCH_SIZE", DEFAULT_BATCH_SIZE)
UPDATE_BATCH_SIZE = env_int("SCRAPE_UPDATE_BATCH_SIZE", DEFAULT_UPDATE_BATCH_SIZE)
MAX_MINUTES = env_int("SCRAPE_MAX_MINUTES", DEFAULT_MAX_MINUTES)


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
        return math.ceil(with_markup * 2) / 2
    return math.ceil(with_markup)


def normalize_url(url):
    if not url:
        return ""
    absolute = urljoin(BASE_URL, url).split("#")[0].split("?")[0]
    return absolute.rstrip("/") + "/"


def request_soup(url, timeout=15):
    res = requests.get(url, headers=HEADERS, timeout=timeout)
    if not res.ok:
        return None
    return BeautifulSoup(res.text, "html.parser")


def sitemap_locations(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        if not res.ok:
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        return [loc.get_text(strip=True) for loc in soup.find_all("loc") if loc.get_text(strip=True)]
    except Exception as exc:
        print(f"  ⚠️ לא ניתן לקרוא sitemap {url}: {exc}")
        return []


def collect_product_urls_from_sitemaps():
    urls = []
    seen = set()
    for sitemap_url in SITEMAP_CANDIDATES:
        for loc in sitemap_locations(sitemap_url):
            url = normalize_url(loc)
            if ("/product/" in url or "/product-page/" in url) and url not in seen:
                seen.add(url)
                urls.append(url)
        if urls:
            print(f"  sitemap מוצרים: {len(urls)} כתובות מתוך {sitemap_url}")
            break
    return urls


def collect_category_urls_from_sitemaps():
    urls = []
    seen = set()
    for sitemap_url in CATEGORY_SITEMAP_CANDIDATES:
        for loc in sitemap_locations(sitemap_url):
            url = normalize_url(loc)
            if "/product-category/" in url and url not in seen:
                seen.add(url)
                urls.append(url)
        if urls:
            print(f"  sitemap קטגוריות: {len(urls)} כתובות מתוך {sitemap_url}")
            break
    return urls


def category_name_from_page(url):
    soup = request_soup(url, timeout=12)
    if not soup:
        return ""
    title = soup.select_one("h1.page-title, h1.entry-title, h1")
    if title:
        return clean_category_name(title.get_text(strip=True))
    return ""


def clean_category_name(name):
    cleaned = " ".join(str(name or "").split())
    prefixes = ["קטגוריה:", "Category:"]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


def merge_category_tree(existing, parent, child=""):
    parent = clean_category_name(parent)
    child = clean_category_name(child)
    if not parent:
        return
    item = next((cat for cat in existing if cat.get("parent") == parent), None)
    if not item:
        item = {"parent": parent, "children": []}
        existing.append(item)
    if child and child not in item["children"]:
        item["children"].append(child)


def category_tree_from_sitemaps():
    category_urls = collect_category_urls_from_sitemaps()
    if not category_urls:
        return []

    names_by_url = {}
    for url in category_urls:
        name = category_name_from_page(url)
        if name:
            names_by_url[url] = name
        time.sleep(0.15)

    tree = []
    for url, name in names_by_url.items():
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        marker = "product-category/"
        if marker not in path:
            continue
        rel = path.split(marker, 1)[1].strip("/")
        parts = [part for part in rel.split("/") if part]
        if len(parts) <= 1:
            merge_category_tree(tree, name)
            continue

        parent_url = normalize_url(f"{BASE_URL}/product-category/{parts[0]}/")
        parent_name = names_by_url.get(parent_url) or category_name_from_page(parent_url)
        if parent_name:
            merge_category_tree(tree, parent_name, name)

    return [cat for cat in tree if cat.get("children")]


def scrape_categories():
    from sync_source_taxonomy import read_pages, build_navigation
    with requests.Session() as session:
        categories = read_pages('products/categories', session)
    response = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    tree = build_navigation(categories, response.text)
    save_json(CATEGORIES_FILE, tree)
    return tree


def get_all_product_urls(force_refresh=False):
    if os.path.exists(URLS_FILE) and not force_refresh:
        urls = load_json(URLS_FILE, [])
        if urls:
            print(f"📋 נטען קובץ URLs קיים: {len(urls)} כתובות")
            return urls

    print("🌐 סורק עמודי חנות לאיסוף כתובות...")
    urls = set()

    for product_url in collect_product_urls_from_sitemaps():
        urls.add(product_url)

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
                    found.add(normalize_url(href))
            if not found:
                break
            urls.update(found)
            print(f"  עמוד {page}: {len(found)} מוצרים (סה\"כ: {len(urls)})")
            page += 1
            time.sleep(1)
        except Exception as e:
            print(f"  שגיאה בעמוד {page}: {e}")
            break

    existing_urls = load_json(URLS_FILE, []) if os.path.exists(URLS_FILE) else []
    current_urls = sorted(urls)
    if not current_urls:
        raise RuntimeError('Product discovery returned no URLs; refusing to publish an empty scan')
    urls_list = list(dict.fromkeys(existing_urls + current_urls))
    save_json(URLS_FILE, urls_list)
    removed = max(0, len(existing_urls) - len(urls_list)) if force_refresh else 0
    print(f"\n✅ נשמרו {len(urls_list)} כתובות ({len(urls_list) - len(existing_urls)} חדשות, {removed} הוסרו)")
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
        url = normalize_url(res.url)

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

        # קטגוריות מ-breadcrumb
        parent_category = ""
        child_category = ""
        category = ""

        breadcrumb_links = soup.select(".woocommerce-breadcrumb a, nav.woocommerce-breadcrumb a")
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

        # שמות האופציות + אפשרויות בחירה שמופיעות בעמוד
        attribute_labels = {}
        attribute_options = {}
        select_els = soup.select("table.variations tr")
        for row in select_els:
            label_el = row.select_one("label")
            select_el = row.select_one("select")
            if label_el and select_el:
                label = label_el.get_text(strip=True)
                name_attr = select_el.get("name", "")
                attribute_labels[name_attr] = label
                options = []
                for option in select_el.find_all("option"):
                    value = (option.get("value") or "").strip()
                    text = option.get_text(strip=True)
                    if not value:
                        continue
                    clean_value = text if text and text not in ["בחר אפשרות", "Choose an option"] else unquote(value)
                    if clean_value and clean_value not in options:
                        options.append(clean_value)
                if options:
                    attribute_options[name_attr] = options

        # במוצרים מסוימים WooCommerce לא מכניס data-product_variations מלא,
        # אבל כן מציג select-ים. נשמור גם אותם כדי שהאתר יציג צבע/דגם ללקוח.
        for variation in variations:
            for key, value in (variation.get("attributes") or {}).items():
                if not value:
                    continue
                attribute_options.setdefault(key, [])
                if value not in attribute_options[key]:
                    attribute_options[key].append(value)

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
            "attribute_options": attribute_options,
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
        "stock_text", "variations", "attribute_labels", "attribute_options", "sku", "product_id"
    ]
    for field in fields_to_check:
        if old.get(field) != new.get(field):
            return True, field
    return False, None


def stable_product_merge(previous, updates):
    """Keep published array positions, including duplicates and retired entries."""
    def identity(product):
        return str(product.get('product_id') or product.get('source_product_id') or normalize_url(product.get('url', '')))

    by_id = {identity(product): product for product in updates}
    result = []
    seen = set()
    for old in previous:
        key = identity(old)
        updated = by_id.get(key)
        if updated is not None:
            merged = dict(updated)
            for field in ('source_category_ids', 'source_product_id', 'source_catalog_missing'):
                if field not in merged and field in old:
                    merged[field] = old[field]
            result.append(merged)
        else:
            result.append(old)
        seen.add(key)
    for product in updates:
        key = identity(product)
        if key not in seen:
            result.append(product)
            seen.add(key)
    return result


def main():
    start_time = datetime.now()
    print(f"🔍 מתחיל סריקה — {start_time.strftime('%d/%m/%Y %H:%M')}")

    # ✅ סריקת תפריט קטגוריות בכל ריצה
    scrape_categories()

    products = load_json(PRODUCTS_FILE, [])
    products_dict = {normalize_url(p["url"]): p for p in products if p.get("url")}
    progress = load_json(PROGRESS_FILE, {"last_index": 0, "completed": False})

    print(f"📦 מוצרים קיימים: {len(products_dict)}")
    print(f"📍 המשך מאינדקס: {progress['last_index']}")

    if progress.get("completed"):
        print("✅ סריקה ראשונה הושלמה! עובר למצב עדכונים...")
        urls = get_all_product_urls(force_refresh=True)
        if not urls:
            print("No product URLs to update")
            return

        current_urls = set(urls)
        stale_urls = [url for url in products_dict if normalize_url(url) not in current_urls]
        # A missing discovery result is not evidence that a product was deleted.
        # Keep its array position: saved carts and waitlists reference these indexes.
        if stale_urls:
            print(f"🧹 הוסרו {len(stale_urls)} מוצרים שכבר לא קיימים במקור")

        new_urls = [url for url in urls if normalize_url(url) not in products_dict]
        # Prioritize products confirmed by the latest complete source catalog scan.
        confirmed_missing = {normalize_url(p['url']) for p in load_json('missing-source-products.json', [])}
        new_urls.sort(key=lambda url: normalize_url(url) not in confirmed_missing)
        if new_urls:
            print(f"🆕 נמצאו {len(new_urls)} מוצרים חדשים — סורק אותם לפני עדכון שוטף")

        added = 0
        updated = 0

        for new_url in new_urls:
            elapsed = (datetime.now() - start_time).seconds / 60
            if elapsed > MAX_MINUTES:
                print(f"\nReached {MAX_MINUTES} minutes while adding new products, saving progress")
                break
            url = normalize_url(new_url)
            product = scrape_product(url)
            if product:
                product_url = normalize_url(product.get("url") or url)
                products_dict[product_url] = product
                added += 1
                print(f"  🆕 נוסף: {product['name']}")
            time.sleep(0.5)

        total = len(urls)
        start_idx = int(progress.get("update_index", 0)) % total
        batch_size = min(UPDATE_BATCH_SIZE, total)
        batch_indexes = [(start_idx + offset) % total for offset in range(batch_size)]
        print(f"Updating {batch_size} of {total} products from index {start_idx + 1}")

        last_index = (start_idx - 1) % total
        for idx in batch_indexes:
            elapsed = (datetime.now() - start_time).seconds / 60
            if elapsed > MAX_MINUTES:
                print(f"\nReached {MAX_MINUTES} minutes, saving progress")
                break
            url = normalize_url(urls[idx])
            last_index = idx
            product = scrape_product(url)
            if product:
                product_url = normalize_url(product.get("url") or url)
                if product_url != url:
                    products_dict.pop(url, None)
                old = products_dict.get(product_url, {})
                changed, field = products_are_different(old, product)
                if changed or old.get('needs_revalidation'):
                    products_dict[product_url] = product
                    updated += 1
                    print(f"  🔄 עודכן [{field}]: {product['name']}")
            time.sleep(0.5)

        progress["update_index"] = (last_index + 1) % total
        save_json(PROGRESS_FILE, progress)
        save_json(PRODUCTS_FILE, stable_product_merge(products, list(products_dict.values())))
        print(f"\n✅ עדכון הושלם — {added} מוצרים חדשים נוספו, {updated} מוצרים שונו")
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

        url = normalize_url(all_urls[i])
        print(f"[{i+1}/{total}] {url.split('/')[-2][:40]}")

        product = scrape_product(url)
        if product:
            product_url = normalize_url(product.get("url") or url)
            if product_url != url:
                products_dict.pop(url, None)
            products_dict[product_url] = product

        progress["last_index"] = i + 1
        time.sleep(0.5)

    if progress["last_index"] >= total:
        progress["completed"] = True
        print(f"\n🎉 סריקה ראשונה הושלמה!")
    else:
        remaining = total - progress["last_index"]
        print(f"\n💾 נשארו {remaining} מוצרים לסריקות הבאות")

    save_json(PRODUCTS_FILE, stable_product_merge(products, list(products_dict.values())))
    save_json(PROGRESS_FILE, progress)
    print(f"✅ נשמרו {len(products_dict)} מוצרים")


if __name__ == "__main__":
    main()
