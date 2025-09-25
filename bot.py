import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import asyncio
import stripe
import database
from UberCheckout import woolix
from dotenv import load_dotenv
import os
import json
from discord import app_commands   # needed for slash commands

# ─── Voucher & Balance database (use /var/data if available, else /tmp) ──────────
DATA_DIR = "/var/data" if os.path.exists("/var/data") else "/tmp/data"
os.makedirs(DATA_DIR, exist_ok=True)

CODE_FILE = os.path.join(DATA_DIR, "codes.json")
BALANCE_FILE = os.path.join(DATA_DIR, "balances.json")

# ensure the files exist the very first time
for path in (CODE_FILE, BALANCE_FILE):
    if not os.path.exists(path):
        print(f"[INFO] {path} missing - creating a blank JSON file")
        with open(path, "w", encoding="utf-8") as fp:
            json.dump({}, fp, indent=2)

# whitelist files (same folder as this script)
WL_DIR = os.path.dirname(os.path.abspath(__file__))
WL_FILES = [
    (os.path.join(WL_DIR, "wl_5.txt"), 5),
    (os.path.join(WL_DIR, "wl_10.txt"), 10),
    (os.path.join(WL_DIR, "wl_15.txt"), 15),
]

def _load_existing_codes() -> dict:
    try:
        with open(CODE_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def _read_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip().upper() for ln in f if ln.strip()]

def load_whitelist_codes() -> dict:
    """Build dict of codes only from wl_*.txt files, keeping 'used' from existing CODE_FILE."""
    existing = _load_existing_codes()
    out: dict[str, dict] = {}
    seen = set()
    dup_count = 0

    for fname, value in WL_FILES:
        for code in _read_lines(fname):
            if code in seen:
                dup_count += 1
            seen.add(code)
            prev = existing.get(code, {})
            out[code] = {"used": bool(prev.get("used", False)), "value": int(value)}

    if not out:
        print("[WARN] No whitelist codes found. Place wl_5.txt / wl_10.txt / wl_15.txt next to bot.py")
    else:
        print(f"[INFO] Whitelist union: {len(out)} codes (duplicates across files: {dup_count})")
    return out

def save_codes() -> None:
    with open(CODE_FILE, "w", encoding="utf-8") as fp:
        json.dump(codes, fp, indent=2)

def save_balances() -> None:
    with open(BALANCE_FILE, "w", encoding="utf-8") as fp:
        json.dump(balances, fp, indent=2)

# load voucher codes only from whitelist files, then persist
codes = load_whitelist_codes()
print(f"[INFO] Loaded {len(codes)} codes from whitelist files")
save_codes()

# load balances (once)
try:
    with open(BALANCE_FILE, "r", encoding="utf-8") as fp:
        balances = json.load(fp)
except json.JSONDecodeError as e:
    raise SystemExit(f"[FATAL] {BALANCE_FILE} is not valid JSON: {e}")

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
STRIPE_SECRET = os.getenv('STRIPE_SECRET_KEY')

stripe.api_key = STRIPE_SECRET

# Set up intents
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

# Create bot instance
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------------------------------------------
# /redeem — voucher code redemption
# ------------------------------------------------------------------
@bot.tree.command(name="redeem", description="Redeem an ACO voucher code")
@app_commands.describe(code="Your voucher code (e.g. ACO15-XXXXXX)")
async def redeem(interaction: discord.Interaction, code: str):
    code = code.upper().strip()

    if code not in codes:
        await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
        return
    if codes[code]["used"]:
        await interaction.response.send_message("❌ Code already used.", ephemeral=True)
        return

    credit_value = codes[code]["value"]

    uid = str(interaction.user.id)
    balances[uid] = balances.get(uid, 0) + credit_value
    save_balances()

    await database.updateBalance(uid, credit_value, 0, "Voucher redeem")

    codes[code]["used"] = True
    codes[code]["redeemed_by"] = uid
    save_codes()

    await interaction.response.send_message(
        f"✅ {credit_value} credits added!  New balance: **{balances[uid]} credits**.",
        ephemeral=True,
    )

# ------------------------------------------------------------------
# The rest of your code remains unchanged (queue, woolix handling, commands, etc.)
# ------------------------------------------------------------------

# (keep everything else exactly as you had — I didn’t touch your queue, woolix, wallet, checkout, etc.)
# ...
# ...
# At the bottom:

asyncio.run(bot.run(BOT_TOKEN))
