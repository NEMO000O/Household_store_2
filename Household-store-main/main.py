import asyncio
import html
import json
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()
SHOP_NAME = os.getenv("SHOP_NAME", "Магазин").strip() or "Магазин"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError as exc:
    raise SystemExit("ADMIN_ID в .env должен быть числом") from exc

if not BOT_TOKEN:
    raise SystemExit("Задайте BOT_TOKEN в файле .env")
if not WEB_APP_URL:
    raise SystemExit("Задайте WEB_APP_URL в файле .env")
if not SUPABASE_URL or not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY):
    raise SystemExit("Задайте SUPABASE_URL и ключ (SERVICE_ROLE или ANON) в .env")

# Service role нужен для записи заказов. Anon — только чтение каталога.
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY,
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

MAX_QTY = 99
MAX_ITEMS = 40


def escape(value) -> str:
    return html.escape(str(value), quote=True)


def parse_order_payload(raw: str) -> list[dict]:
    """Принимаем только id и количество. Цену клиенту не доверяем."""
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("ожидался объект JSON")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("пустая корзина")
    if len(items) > MAX_ITEMS:
        raise ValueError("слишком много позиций")

    cleaned = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("некорректная позиция")
        product_id = int(item.get("id"))
        qty = int(item.get("qty"))
        if product_id <= 0 or qty <= 0 or qty > MAX_QTY:
            raise ValueError("некорректное количество")
        if product_id in seen:
            raise ValueError("дубликат товара")
        seen.add(product_id)
        cleaned.append({"id": product_id, "qty": qty})
    return cleaned


async def load_products_map(product_ids: list[int]) -> dict[int, dict]:
    def _fetch():
        return (
            supabase.table("products")
            .select("*")
            .in_("id", product_ids)
            .execute()
        )

    result = await asyncio.to_thread(_fetch)
    mapping = {}
    for row in result.data or []:
        mapping[int(row["id"])] = row
    return mapping


async def save_order(user: types.User, lines: list[dict], total: int) -> int | None:
    record = {
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "items": lines,
        "total": total,
        "status": "new",
    }

    def _insert():
        return supabase.table("orders").insert(record).execute()

    try:
        result = await asyncio.to_thread(_insert)
        if result.data:
            return result.data[0].get("id")
    except Exception as exc:
        print(f"[ERROR] Не удалось сохранить заказ в Supabase: {exc}")
    return None


async def decrease_stock(product_id: int, new_stock: int) -> None:
    def _update():
        return (
            supabase.table("products")
            .update({"stock": new_stock})
            .eq("id", product_id)
            .execute()
        )

    try:
        await asyncio.to_thread(_update)
    except Exception as exc:
        print(f"[ERROR] Не удалось обновить остаток товара {product_id}: {exc}")


def build_catalog_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Открыть каталог {SHOP_NAME}",
                    web_app=WebAppInfo(url=WEB_APP_URL),
                )
            ]
        ]
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        f"Добро пожаловать в {escape(SHOP_NAME)}.\n"
        "Нажмите кнопку ниже, чтобы выбрать товары и оформить заказ:",
        reply_markup=build_catalog_keyboard(),
        parse_mode="HTML",
    )


@dp.message(F.web_app_data)
async def handle_web_app_order(message: types.Message):
    user = message.from_user
    try:
        cart_items = parse_order_payload(message.web_app_data.data)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Некорректные данные заказа: {exc}")
        await message.answer("Не удалось прочитать заказ. Откройте каталог и оформите его ещё раз.")
        return

    product_ids = [item["id"] for item in cart_items]
    products = await load_products_map(product_ids)

    missing = [item["id"] for item in cart_items if item["id"] not in products]
    if missing:
        await message.answer("Некоторые товары больше недоступны. Обновите каталог и повторите заказ.")
        return

    lines = []
    computed_total = 0
    items_html = []

    for item in cart_items:
        product = products[item["id"]]
        qty = item["qty"]
        price = int(product.get("price") or 0)
        stock = product.get("stock")
        if stock is not None:
            try:
                stock = int(stock)
            except (TypeError, ValueError):
                stock = None
        if stock is not None and qty > stock:
            await message.answer(
                f"Не хватает товара «{escape(product.get('name', item['id']))}». "
                f"В наличии: {stock} шт."
            )
            return

        line_total = price * qty
        computed_total += line_total
        name = product.get("name") or f"Товар №{item['id']}"
        lines.append(
            {
                "id": item["id"],
                "name": name,
                "qty": qty,
                "price": price,
                "total": line_total,
            }
        )
        items_html.append(
            f"• {escape(name)} — <b>{qty} шт.</b> ({line_total} ₽)"
        )

    order_id = await save_order(user, lines, computed_total)

    for line in lines:
        product = products[line["id"]]
        stock = product.get("stock")
        if stock is None:
            continue
        try:
            await decrease_stock(line["id"], int(stock) - line["qty"])
        except (TypeError, ValueError):
            continue

    username = f"@{user.username}" if user.username else "скрыт"
    order_label = f"№{order_id}" if order_id else "без номера (не записан в БД)"

    order_text = (
        f"<b>Новый заказ {escape(SHOP_NAME)} {escape(order_label)}</b>\n\n"
        f"<b>Покупатель:</b> {escape(user.full_name)}\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Профиль:</b> {escape(username)}\n\n"
        f"<b>Состав:</b>\n{chr(10).join(items_html)}\n\n"
        f"<b>Итого:</b> <b>{computed_total} ₽</b>\n\n"
        "<i>Свяжитесь с клиентом, чтобы подтвердить заказ.</i>"
    )

    try:
        await bot.send_message(chat_id=ADMIN_ID, text=order_text, parse_mode="HTML")
    except Exception as exc:
        print(f"[ERROR] Не удалось отправить чек админу: {exc}")

    await message.answer(
        f"Заказ на сумму <b>{computed_total} ₽</b> оформлен.\n"
        "Менеджер проверит наличие и напишет вам.\n\n"
        "Открыть каталог снова:",
        reply_markup=build_catalog_keyboard(),
        parse_mode="HTML",
    )


async def main():
    if not SUPABASE_SERVICE_ROLE_KEY:
        print("[WARN] Нет SUPABASE_SERVICE_ROLE_KEY: запись заказов может быть запрещена RLS.")
    print(f"[BOT] {SHOP_NAME} запущен, ADMIN_ID={ADMIN_ID}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
