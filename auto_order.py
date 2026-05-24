"""
auto_order.py
-------------
Processes new orders from the dashboard database and prepares/submits them on
the source WooCommerce site.

Safety default:
- The script does NOT click the final "place order" button unless
  AUTO_ORDER_SUBMIT=true is set in GitHub Secrets.
- This prevents accidental real supplier orders while still keeping the code
  ready for full automation when you explicitly enable it.
"""

import asyncio
import html
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

import psycopg2
from playwright.async_api import Page, async_playwright


SOURCE_URL = "https://www.seferkodesh.co.il"
PRODUCTS_FILE = "products.json"
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SOURCE_EMAIL = os.environ.get("SOURCE_EMAIL", "")
SOURCE_PASSWORD = os.environ.get("SOURCE_PASSWORD", "")
AUTO_ORDER_SUBMIT = os.environ.get("AUTO_ORDER_SUBMIT", "").lower() == "true"
MAX_ORDERS = int(os.environ.get("AUTO_ORDER_LIMIT", "5"))
VALID_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def public_order_id(order_id: str) -> str:
    digits = re.sub(r"\D", "", str(order_id))
    return digits[-5:].rjust(5, "0")


def load_products() -> List[Dict[str, Any]]:
    if not os.path.exists(PRODUCTS_FILE):
        return []
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def split_name(full_name: str) -> Tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def split_address(address: str) -> Tuple[str, str]:
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return address or "", ""


def connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg2.connect(normalize_database_url(DATABASE_URL))


def normalize_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = query.get("sslmode", "").lower()
    if sslmode not in VALID_SSLMODES:
        query["sslmode"] = "require"
    return urlunparse(parsed._replace(query=urlencode(query)))


def normalize_text(value: Any) -> str:
    text = html.unescape(unquote(str(value or ""))).strip().lower()
    text = re.sub(r"^attribute[_-]?", "", text)
    text = re.sub(r"[\s_:\-–—/]+", " ", text)
    return text.strip()


def item_selected_attributes(item: Dict[str, Any]) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for key in ("selectedAttributes", "selectedAttrs", "attributes"):
        raw = item.get(key)
        if isinstance(raw, dict):
            for attr_key, attr_value in raw.items():
                if attr_value not in (None, ""):
                    attrs[str(attr_key)] = str(attr_value)
    return attrs


def attribute_label(product: Dict[str, Any], attr_key: str) -> str:
    labels = product.get("attribute_labels")
    if isinstance(labels, dict):
        return str(labels.get(attr_key) or "")
    return ""


def matching_variation(
    item: Dict[str, Any], product: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if not product:
        return None

    variations = product.get("variations")
    if not isinstance(variations, list):
        return None

    wanted_id = str(item.get("variationId") or item.get("variation_id") or "")
    wanted_sku = str(item.get("sku") or "")
    if wanted_id or wanted_sku:
        for variation in variations:
            if wanted_id and wanted_id == str(variation.get("variation_id") or ""):
                return variation
            if wanted_sku and wanted_sku == str(variation.get("sku") or ""):
                return variation

    selected = item_selected_attributes(item)
    if not selected:
        return None

    normalized_selected = {
        normalize_text(key): normalize_text(value) for key, value in selected.items()
    }
    for variation in variations:
        variation_attrs = variation.get("attributes") or {}
        if not isinstance(variation_attrs, dict):
            continue
        matches = True
        for attr_key, attr_value in variation_attrs.items():
            label = attribute_label(product, attr_key)
            selected_value = (
                normalized_selected.get(normalize_text(attr_key))
                or normalized_selected.get(normalize_text(label))
            )
            if selected_value and selected_value != normalize_text(attr_value):
                matches = False
                break
        if matches:
            return variation
    return None


def selected_value_for_attribute(
    item: Dict[str, Any], product: Dict[str, Any], attr_key: str
) -> Optional[str]:
    selected = item_selected_attributes(item)
    label = attribute_label(product, attr_key)
    for key, value in selected.items():
        if normalize_text(key) in {normalize_text(attr_key), normalize_text(label)}:
            return value

    variation = matching_variation(item, product)
    variation_attrs = variation.get("attributes") if variation else None
    if isinstance(variation_attrs, dict) and variation_attrs.get(attr_key):
        return str(variation_attrs[attr_key])

    return None


def required_attribute_keys(product: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    options = product.get("attribute_options")
    if isinstance(options, dict):
        keys.extend(str(key) for key in options.keys())

    for variation in product.get("variations") or []:
        attrs = variation.get("attributes") or {}
        if isinstance(attrs, dict):
            for key in attrs.keys():
                if str(key) not in keys:
                    keys.append(str(key))
    return keys


def get_pending_orders() -> List[Dict[str, Any]]:
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, customer_name, customer_phone, customer_email,
                       customer_address, items, notes
                FROM orders
                WHERE (auto_submitted = FALSE OR auto_submitted IS NULL)
                  AND COALESCE(status, 'pending') IN (
                    'pending',
                    'ai_ready_for_source_submit',
                    'source_submit_in_progress',
                    'needs_care'
                  )
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (MAX_ORDERS,),
            )
            rows = cur.fetchall()

    orders = []
    for row in rows:
        items = row[5]
        if isinstance(items, str):
            items = json.loads(items)
        orders.append(
            {
                "id": row[0],
                "customer_name": row[1] or "",
                "customer_phone": row[2] or "",
                "customer_email": row[3] or "",
                "customer_address": row[4] or "",
                "items": items or [],
                "notes": row[6] or "",
            }
        )
    return orders


def update_order(order_id: str, **fields: Any) -> None:
    if not fields:
        return
    allowed = {"auto_submitted", "checkout_url", "external_order_id", "status"}
    updates = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        values.append(value)
        updates.append(f"{key} = %s")
    if not updates:
        return
    values.append(order_id)
    with connect_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE orders SET {', '.join(updates)} WHERE id = %s",
                values,
            )
        conn.commit()


def resolve_product_url(item: Dict[str, Any], products: List[Dict[str, Any]]) -> Optional[str]:
    product = resolve_product(item, products)
    return product.get("url") if product else None


def resolve_product(
    item: Dict[str, Any], products: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    for key in ("source_url", "url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http"):
            for product in products:
                if product.get("url") == value:
                    return product
            return {"url": value, "variations": []}

    index = item.get("sourceProductIndex")
    if isinstance(index, int) and 0 <= index < len(products):
        return products[index]

    raw_id = str(item.get("sourceProductId") or "")
    if raw_id.startswith("http"):
        for product in products:
            if product.get("url") == raw_id:
                return product
        return {"url": raw_id, "variations": []}

    for product in products:
        if raw_id and raw_id in {str(product.get("product_id", "")), str(product.get("sku", ""))}:
            return product

    return None


async def login_to_source(page: Page) -> None:
    if not SOURCE_EMAIL or not SOURCE_PASSWORD:
        print("SOURCE_EMAIL/SOURCE_PASSWORD are not configured; continuing without login")
        return

    await page.goto(f"{SOURCE_URL}/my-account/", wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    email_selector = "input#username, input[name='username'], input[name='email']"
    password_selector = "input#password, input[name='password']"
    submit_selector = "button[name='login'], button[type='submit']"

    if not await page.locator(email_selector).count():
        print("Login form not found; maybe already logged in")
        return

    await page.fill(email_selector, SOURCE_EMAIL)
    await page.fill(password_selector, SOURCE_PASSWORD)
    await page.click(submit_selector)
    await page.wait_for_timeout(2500)
    print("Login step completed")


async def set_quantity(page: Page, quantity: int) -> None:
    quantity = max(1, int(quantity or 1))
    qty = page.locator("input.qty, input[name='quantity']").first
    if await qty.count():
        await qty.fill(str(quantity))


async def choose_select_option(select, desired: str) -> bool:
    desired_norm = normalize_text(desired)
    options = await select.locator("option").evaluate_all(
        """options => options.map(option => ({
            value: option.value || '',
            text: option.textContent || '',
            label: option.label || ''
        }))"""
    )
    for option in options:
        candidates = [option.get("value"), option.get("text"), option.get("label")]
        if any(normalize_text(candidate) == desired_norm for candidate in candidates):
            await select.select_option(value=option.get("value") or "")
            return True
    return False


async def select_product_options(
    page: Page, product: Dict[str, Any], item: Dict[str, Any]
) -> None:
    required_keys = required_attribute_keys(product)
    if not required_keys:
        return

    for attr_key in required_keys:
        desired = selected_value_for_attribute(item, product, attr_key)
        label = attribute_label(product, attr_key) or attr_key
        if not desired:
            raise RuntimeError(f"Missing required option '{label}' for item {item.get('name')}")

        matching_select = None
        selects = page.locator("select")
        for i in range(await selects.count()):
            select = selects.nth(i)
            meta = await select.evaluate(
                """el => ({
                    name: el.getAttribute('name') || '',
                    id: el.getAttribute('id') || '',
                    dataName: el.getAttribute('data-attribute_name') || '',
                    aria: el.getAttribute('aria-label') || ''
                })"""
            )
            candidates = {
                normalize_text(meta.get("name")),
                normalize_text(meta.get("id")),
                normalize_text(meta.get("dataName")),
                normalize_text(meta.get("aria")),
            }
            if normalize_text(attr_key) in candidates or normalize_text(label) in candidates:
                matching_select = select
                break

        if matching_select is None:
            raise RuntimeError(f"Could not find source option selector for '{label}'")

        if not await choose_select_option(matching_select, desired):
            raise RuntimeError(f"Could not choose '{desired}' for source option '{label}'")

    await page.wait_for_timeout(1000)


def format_item_options(item: Dict[str, Any]) -> List[str]:
    parts: List[str] = []
    for key, value in item_selected_attributes(item).items():
        if normalize_text(key) and normalize_text(value):
            parts.append(f"{key}: {value}")

    engraving = item.get("engraving")
    if isinstance(engraving, dict):
        engraving_parts = []
        for key in ("type", "letterColor", "text", "qty", "bulkType", "sketchText", "extraQty"):
            value = engraving.get(key)
            if value not in (None, ""):
                engraving_parts.append(f"{key}: {value}")
        note = engraving.get("note")
        if note:
            engraving_parts.append(str(note))
        if engraving_parts:
            parts.append("engraving: " + " | ".join(engraving_parts))
    return parts


def build_order_comments(order: Dict[str, Any]) -> str:
    lines = [f"Order number: #{public_order_id(order['id'])}"]
    if order.get("notes"):
        lines.append(str(order["notes"]))

    item_lines = []
    for item in order.get("items") or []:
        options = format_item_options(item)
        if options:
            name = item.get("name") or item.get("sourceProductId") or "item"
            item_lines.append(f"{name}: " + " | ".join(options))
    if item_lines:
        lines.append("Item options:")
        lines.extend(item_lines)

    return "\n".join(lines)


async def add_item_to_cart(
    page: Page, item: Dict[str, Any], product: Dict[str, Any], quantity: int
) -> bool:
    url = product.get("url")
    if not url:
        return False

    print(f"Adding to source cart: {url} x{quantity}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await select_product_options(page, product, item)
    await set_quantity(page, quantity)

    selectors = [
        "button.single_add_to_cart_button",
        "button[name='add-to-cart']",
        ".single_add_to_cart_button",
        ".add_to_cart_button",
    ]
    for selector in selectors:
        button = page.locator(selector).first
        if await button.count():
            await button.click()
            await page.wait_for_timeout(2500)
            return True

    print("Could not find add-to-cart button")
    return False


async def fill_checkout(page: Page, order: Dict[str, Any]) -> None:
    first_name, last_name = split_name(order["customer_name"])
    address, city = split_address(order["customer_address"])

    await page.goto(f"{SOURCE_URL}/checkout/", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)

    fields = {
        "billing_first_name": first_name,
        "billing_last_name": last_name,
        "billing_email": order["customer_email"],
        "billing_phone": order["customer_phone"],
        "billing_address_1": address,
        "billing_city": city,
        "order_comments": f"מספר הזמנה שלנו: #{public_order_id(order['id'])}\n{order['notes']}",
    }

    fields["order_comments"] = build_order_comments(order)

    for field_id, value in fields.items():
        locator = page.locator(f"#{field_id}, [name='{field_id}']").first
        if await locator.count():
            await locator.fill(str(value or ""))

    country = page.locator("#billing_country, [name='billing_country']").first
    if await country.count():
        try:
            await country.select_option("IL")
        except Exception:
            pass


async def click_place_order(page: Page) -> Optional[str]:
    for selector in ("#payment_method_bacs", "input[name='payment_method'][value='bacs']"):
        payment = page.locator(selector).first
        if await payment.count():
            await payment.check()
            break

    button = page.locator("#place_order, button[name='woocommerce_checkout_place_order']").first
    if not await button.count():
        raise RuntimeError("Place order button was not found")

    await button.click()
    await page.wait_for_timeout(5000)

    match = re.search(r"order-received/(\d+)", page.url)
    return match.group(1) if match else None


async def process_order(page: Page, order: Dict[str, Any], products: List[Dict[str, Any]]) -> None:
    print(f"\nProcessing order #{public_order_id(order['id'])}")

    await page.goto(f"{SOURCE_URL}/cart/", wait_until="domcontentloaded")
    await page.wait_for_timeout(1000)
    empty_cart_links = page.locator(".remove, a.remove")
    for i in range(await empty_cart_links.count()):
        await empty_cart_links.nth(i).click()
        await page.wait_for_timeout(600)

    added = 0
    for item in order["items"]:
        product = resolve_product(item, products)
        if not product:
            print(f"Missing source URL for item: {item.get('name') or item.get('sourceProductId')}")
            continue
        if await add_item_to_cart(page, item, product, int(item.get("quantity") or 1)):
            added += 1

    if added == 0:
        raise RuntimeError("No items were added to the source cart")

    await fill_checkout(page, order)

    if not AUTO_ORDER_SUBMIT:
        print("AUTO_ORDER_SUBMIT is not true; stopping before final source-site submission")
        update_order(
            order["id"],
            auto_submitted=False,
            status="source_submit_simulated",
            checkout_url=page.url,
            external_order_id=f"SIM-{public_order_id(order['id'])}",
        )
        return

    external_order_id = await click_place_order(page)
    update_order(
        order["id"],
        auto_submitted=True,
        status="confirmed",
        checkout_url=page.url,
        external_order_id=external_order_id or "",
    )
    print(f"Submitted source order: {external_order_id or 'unknown'}")


async def main() -> None:
    orders = get_pending_orders()
    if not orders:
        print("No pending orders")
        return

    products = load_products()
    if not products:
        raise RuntimeError("products.json is missing or empty")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="he-IL")
        page = await context.new_page()
        await login_to_source(page)

        for order in orders:
            try:
                update_order(order["id"], status="source_submit_in_progress")
                await process_order(page, order, products)
            except Exception as exc:
                print(f"Order {order['id']} failed: {exc}")
                update_order(order["id"], status="needs_care")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
