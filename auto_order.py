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
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
    for key in ("source_url", "url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value

    index = item.get("sourceProductIndex")
    if isinstance(index, int) and 0 <= index < len(products):
        return products[index].get("url")

    raw_id = str(item.get("sourceProductId") or "")
    if raw_id.startswith("http"):
        return raw_id

    for product in products:
        if raw_id and raw_id in {str(product.get("product_id", "")), str(product.get("sku", ""))}:
            return product.get("url")

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


async def add_item_to_cart(page: Page, url: str, quantity: int) -> bool:
    print(f"Adding to source cart: {url} x{quantity}")
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
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
        url = resolve_product_url(item, products)
        if not url:
            print(f"Missing source URL for item: {item.get('name') or item.get('sourceProductId')}")
            continue
        if await add_item_to_cart(page, url, int(item.get("quantity") or 1)):
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
