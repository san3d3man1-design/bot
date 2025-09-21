# bot.py
import os
import asyncio
import aiosqlite
import secrets
import time
from decimal import Decimal
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID") or 0)  # deine Telegram numeric user id
BOT_WALLET_ADDRESS = os.getenv("BOT_WALLET_ADDRESS", "DEINE_WALLET_ADRESSE")
FEE_PERCENT = Decimal(os.getenv("FEE_PERCENT") or "3.0")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_PATH = "giftelf.db"


# ----------------- DB INIT -----------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_token TEXT UNIQUE,
            seller_id INTEGER,
            seller_name TEXT,
            amount TEXT,
            description TEXT,
            status TEXT,
            buyer_id INTEGER,
            payment_token TEXT,
            created_at INTEGER
        )""")
        await db.commit()


# ----------------- UI HELPERS -----------------
def main_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Neues Deal", callback_data="create_deal")],
        [InlineKeyboardButton(text="🔎 Meine Deals", callback_data="my_deals")],
        [InlineKeyboardButton(text="❓ Hilfe", callback_data="help")]
    ])
    return kb


def deal_buttons(deal, uid):
    kb = []
    if deal["status"] == "open" and deal["seller_id"] == uid:
        kb.append([InlineKeyboardButton("🔗 Käufer-Link", callback_data=f"get_link:{deal['deal_token']}")])
        kb.append([InlineKeyboardButton("❌ Abbrechen", callback_data=f"cancel:{deal['deal_token']}")])
    if deal["status"] == "paid" and deal["seller_id"] == uid:
        kb.append([InlineKeyboardButton("📤 Markiere als versandt", callback_data=f"shipped:{deal['deal_token']}")])
    if deal["status"] == "shipped" and deal["buyer_id"] == uid:
        kb.append([InlineKeyboardButton("📦 Ich habe erhalten", callback_data=f"received:{deal['deal_token']}")])
    kb.append([InlineKeyboardButton("🔙 Menü", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ----------------- START -----------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await init_db()
    await message.answer("👋 Willkommen bei GiftElf!\nErstelle sichere Deals über mich.", reply_markup=main_menu())


# ----------------- CALLBACK HANDLER -----------------
user_states = {}

@dp.callback_query()
async def cb_all(cq: types.CallbackQuery):
    data = cq.data or ""
    uid = cq.from_user.id

    async def fetch_deal(token):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT * FROM deals WHERE deal_token=?", (token,))
            r = await cur.fetchone()
        if not r:
            return None
        keys = ["id","deal_token","seller_id","seller_name","amount","description","status","buyer_id","payment_token","created_at"]
        return dict(zip(keys, r))

    # neues Deal
    if data == "create_deal":
        user_states[uid] = {"flow":"create","step":"amount"}
        await cq.message.answer("Gib den Betrag in TON ein (z. B. 10.5):")
        await cq.answer()
        return

    # meine Deals
    if data == "my_deals":
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT deal_token,amount,description,status FROM deals WHERE seller_id=? OR buyer_id=?", (uid,uid))
            rows = await cur.fetchall()
        if not rows:
            await cq.message.answer("Du hast keine Deals.")
        else:
            for r in rows:
                token,amount,desc,status = r
                await cq.message.answer(f"Deal {token}\n{amount} TON\n{desc}\nStatus: {status}",
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                            [InlineKeyboardButton("Öffnen", callback_data=f"open:{token}")]
                                        ]))
        await cq.answer()
        return

    # Deal öffnen
    if data.startswith("open:"):
        token = data.split(":")[1]
        deal = await fetch_deal(token)
        if not deal:
            await cq.message.answer("Deal nicht gefunden.")
            return
        msg = (f"Deal {deal['deal_token']}\n"
               f"Betrag: {deal['amount']} TON\n"
               f"Beschreibung: {deal['description']}\n"
               f"Status: {deal['status']}\n"
               f"Payment Token: {deal['payment_token']}\n"
               f"Wallet: {BOT_WALLET_ADDRESS}")
        await cq.message.answer(msg, reply_markup=deal_buttons(deal, uid))
        await cq.answer()
        return

    # Käufer-Link
    if data.startswith("get_link:"):
        token = data.split(":")[1]
        bot_user = (await bot.get_me()).username
        link = f"https://t.me/{bot_user}?start=join_{token}"
        await cq.message.answer(f"🔗 Käufer-Link:\n{link}")
        await cq.answer()
        return

    # Seller cancel
    if data.startswith("cancel:"):
        token = data.split(":")[1]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE deals SET status='cancelled' WHERE deal_token=?", (token,))
            await db.commit()
        await cq.message.answer("Deal abgebrochen.")
        await cq.answer()
        return

    # Seller shipped
    if data.startswith("shipped:"):
        token = data.split(":")[1]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE deals SET status='shipped' WHERE deal_token=?", (token,))
            await db.commit()
        await cq.message.answer("📤 Als versandt markiert.")
        await cq.answer()
        return

    # Buyer received
    if data.startswith("received:"):
        token = data.split(":")[1]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE deals SET status='received' WHERE deal_token=?", (token,))
            await db.commit()
        await cq.message.answer("📦 Empfang bestätigt. Auszahlung erfolgt automatisch durch das System.")
        await cq.answer()
        return

    if data == "back_menu":
        await cq.message.answer("Menü:", reply_markup=main_menu())
        await cq.answer()
        return


# ----------------- MESSAGE HANDLER -----------------
@dp.message()
async def msg_handler(message: types.Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()

    # Buyer join via link
    if txt.startswith("/start join_"):
        token = txt.split("join_")[1]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE deals SET buyer_id=? WHERE deal_token=?", (uid, token))
            await db.commit()
            cur = await db.execute("SELECT amount,description,payment_token FROM deals WHERE deal_token=?", (token,))
            r = await cur.fetchone()
        if r:
            amount,desc,payment_token = r
            await message.answer(f"Deal {token}\nBetrag: {amount} TON\n{desc}\n\n"
                                 f"💰 Zahle an:\n`{BOT_WALLET_ADDRESS}`\n\n"
                                 f"Memo: `{payment_token}`\n\n"
                                 f"Sobald die Zahlung eingegangen ist, bestätigt das System automatisch.",
                                 parse_mode="Markdown")
        return

    # Admin commands
    if uid == ADMIN_ID:
        if txt.startswith("/paid "):
            token = txt.split()[1]
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE deals SET status='paid' WHERE deal_token=?", (token,))
                await db.commit()
            await message.answer(f"✅ Deal {token} als bezahlt markiert. Verkäufer wird informiert.")
            return
        if txt.startswith("/payout "):
            token = txt.split()[1]
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE deals SET status='payout_done' WHERE deal_token=?", (token,))
                await db.commit()
            await message.answer(f"💸 Auszahlung für Deal {token} abgeschlossen.")
            return
        if txt.startswith("/cancel "):
            token = txt.split()[1]
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE deals SET status='cancelled' WHERE deal_token=?", (token,))
                await db.commit()
            await message.answer(f"❌ Deal {token} storniert.")
            return

    # Create deal flow
    state = user_states.get(uid)
    if state and state["flow"] == "create":
        if state["step"] == "amount":
            try:
                amt = Decimal(txt)
                if amt <= 0: raise Exception()
                state["amount"] = str(amt)
                state["step"] = "desc"
                user_states[uid] = state
                await message.answer("Beschreibung des Deals eingeben:")
                return
            except:
                await message.answer("Ungültiger Betrag. Bitte erneut eingeben:")
                return
        elif state["step"] == "desc":
            desc = txt
            deal_token = secrets.token_hex(6)
            payment_token = f"DEAL-{deal_token}-{secrets.token_hex(4)}"
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO deals (deal_token,seller_id,seller_name,amount,description,status,payment_token,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (deal_token, uid, message.from_user.full_name, state["amount"], desc, "open", payment_token, int(time.time())))
                await db.commit()
            user_states.pop(uid, None)
            await message.answer(f"✅ Deal erstellt!\nToken: {deal_token}\nPayment Token: {payment_token}\n\n"
                                 f"Teile den Käufer-Link:\nhttps://t.me/{(await bot.get_me()).username}?start=join_{deal_token}")
            return

    await message.answer("Menü:", reply_markup=main_menu())


# ----------------- MAIN -----------------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
