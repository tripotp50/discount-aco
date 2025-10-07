import os
import json
import asyncio
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
from discord import app_commands
import stripe
import database
from UberCheckout import woolix
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# Persistent data dir: use /var/data on Render disk, else fall back to /tmp/data
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Env / Stripe / Discord setup
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY")
GUILD_ID_ENV = os.getenv("GUILD_ID")  # optional: set to force fast per-guild sync

stripe.api_key = STRIPE_SECRET

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ──────────────────────────────────────────────────────────────────────────────
# Slash Commands
# ──────────────────────────────────────────────────────────────────────────────

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

@bot.tree.command(name="slink", description="Check stores available for Selected $25 in your area.")
async def slink(interaction: discord.Interaction):
    await interaction.response.send_message(
        "https://www.ubereats.com/marketing?mft=TARGETING_STORE_PROMO&p&promotionUuid=449baf92-dda2-44d1-9ad6-24033c26f516&targetingStoreTag=restaurant_us_target_all"
    )

class OrderTypeView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, order_link: str, cardNumber: str, expDate: str, cvv: str, zipCode: str, email: str, aco: bool):
        super().__init__()
        self.interaction = interaction
        self.order_link = order_link
        self.cardNumber = cardNumber
        self.expDate = expDate
        self.zipCode = zipCode
        self.cvv = cvv
        self.email = email
        self.aco = aco

    @discord.ui.button(label="$25 Off $25 Any", style=discord.ButtonStyle.primary)
    async def s25_selected(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Your order has been queued for processing.")
        if self.aco:
            await queue.put((True, interaction, self.order_link, self.cardNumber, self.expDate, self.cvv, self.email, "s25", self.zipCode))
        else:
            await queue.put((False, interaction, self.order_link, "", "", "", "", "s25", "07002"))
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Ueaco Cancelled.")
        self.stop()

@bot.tree.command(name="ueaco", description="Uber Eats Auto Checkout, only need order link")
async def ueaco(interaction: discord.Interaction, order_link: str):
    if isinstance(interaction.channel, discord.DMChannel):
        if "https://eats.uber.com/group-orders/" in order_link or "https://www.ubereats.com/group-orders/" in order_link:
            embed = discord.Embed(
                title="New DM Received",
                description=f"**From:** {interaction.user.name} ({interaction.user.id})\n\n**Message:** /ueaco {order_link}",
                color=discord.Color.blue(),
            )
            # optionally log: await bot.get_channel(1364282286400606429).send(embed=embed)
            await interaction.response.send_message("Please select your discount type:", view=OrderTypeView(interaction, order_link, "", "", "", "", "", False))
        else:
            await interaction.response.send_message("Please input a valid UberEats group link.\nExample: https://eats.uber.com/group-orders/xxxxx/join")
    else:
        await interaction.response.send_message("This command can only be used in Direct Messages (DMs).")

@bot.tree.command(name="accleft", description="Check accounts left")
async def accleft(interaction: discord.Interaction):
    num = await database.accLeft()
    await interaction.response.send_message(f"{num} accounts are stocked!")

@bot.tree.command(name="clear", description="Clear Accounts")
async def clear(interaction: discord.Interaction):
    if interaction.user.id != 1403493273376391218:
        await interaction.response.send_message("Not Authorized")
        return
    await interaction.response.send_message("Cleared used accounts")
    await database.clearAcc()

@bot.tree.command(name="setdead", description="Set account dead by email")
async def dead(interaction: discord.Interaction, email: str):
    if interaction.user.id != 1403493273376391218:
        await interaction.response.send_message("Not Authorized")
        return
    await interaction.response.send_message(f"Setting {email} dead")
    await database.setDeadStatus(email)

@bot.tree.command(name="upload", description="Upload a CSV file to MongoDB")
async def upload(interaction: discord.Interaction, csv_file: discord.Attachment):
    if interaction.user.id != 1403493273376391218:
        await interaction.response.send_message("Not Authorized", ephemeral=True)
        return
    if not csv_file.filename.endswith(".csv"):
        await interaction.response.send_message("Please upload a valid CSV file.", ephemeral=True)
        return
    csv_data = await csv_file.read()
    result_message = await database.upload_csv_to_mongo(csv_data)
    await interaction.response.send_message(result_message)

@bot.tree.command(name="aco", description="Uber Eats Auto Checkout with your own VCC")
async def aco(interaction: discord.Interaction, order_info: str):
    if interaction.user.id != 1403493273376391218:
        await interaction.response.send_message("Not Authorized")
        return

    if isinstance(interaction.channel, discord.DMChannel):
        parts = order_info.split(",")
        if len(parts) != 6:
            await interaction.response.send_message("Format: orderlink,cardNumber,expDate,cvv,zipcode,email")
            return
        order_link, cardNumber, expDate, cvv, zipCode, email = parts
        if "https://eats.uber.com/group-orders/" in order_link or "https://www.ubereats.com/group-orders/" in order_link:
            embed = discord.Embed(
                title="New DM Received",
                description=f"**From:** {interaction.user.name} ({interaction.user.id})\n\n**Message:** /aco {order_link}",
                color=discord.Color.blue(),
            )
            await bot.get_channel(1420770900906872893).send(embed=embed)
            await interaction.response.send_message(
                "Please select your discount type:",
                view=OrderTypeView(interaction, order_link, cardNumber, expDate, cvv, zipCode, email, True),
            )
        else:
            await interaction.response.send_message("Please input a valid UberEats group link.\nExample: https://eats.uber.com/group-orders/xxxxx/join")
    else:
        await interaction.response.send_message("This command can only be used in Direct Messages (DMs).")

# ──────────────────────────────────────────────────────────────────────────────
# Wallet Buttons / Modal
# ──────────────────────────────────────────────────────────────────────────────

async def loadcredits(interaction: discord.Interaction, amount: float):
    await interaction.response.defer()
    try:
        amount_in_cents = int(amount * 100)
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Load ${amount} Credits"},
                    "unit_amount": amount_in_cents,
                },
                "quantity": 1,
                "tax_rates": ["txr_1QOVqnGMMMgbOUn4hWrg15lb"],
            }],
            mode="payment",
            success_url="https://discord.com/channels/@me",
            cancel_url="https://google.com/",
            metadata={"userID": f"{interaction.user.id}"}
        )
        await interaction.followup.send(f"Click on Stripe link to load ${amount} credits.\n{session.url}")
    except stripe.error.StripeError as e:
        await interaction.followup.send(f"Error: {e.user_message}")
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}")

class CreditInputModal(discord.ui.Modal, title="Enter Credit Amount"):
    userID = discord.ui.TextInput(label="userID", placeholder="Enter ID", required=True)
    amount = discord.ui.TextInput(label="Credit Amount", placeholder="Enter a number", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            userID = str(self.userID)
            credit_amount = float(self.amount.value)
            await database.updateBalance(userID, credit_amount, 0, "Load Credits command")
            await interaction.response.send_message(f"You entered: {credit_amount}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid number. Please enter a valid amount.", ephemeral=True)

class WalletButtons(View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label="Check Balance", style=discord.ButtonStyle.green)
    async def check_balance(self, interaction: discord.Interaction, button: Button) -> None:
        await interaction.response.defer(ephemeral=True)
        credits = await database.getBalance(str(interaction.user.id))
        await interaction.followup.send(f"Your current credit balance is: **${credits}**", ephemeral=True)

    @discord.ui.button(label="Load Credits", style=discord.ButtonStyle.green)
    async def load_credits(self, interaction: discord.Interaction, button: Button) -> None:
        admin_ids: set[int] = {1403493273376391218}
        if interaction.user.id in admin_ids:
            await interaction.response.send_modal(CreditInputModal())
        else:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("Please open a ticket in the server to add credits to your wallet.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Wallet operation canceled.", ephemeral=True)
        self.stop()

@bot.tree.command(name="wallet", description="Check your balance or load credits")
async def wallet(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "Choose an option from the wallet:",
        view=WalletButtons(),
        ephemeral=True,
    )

# ──────────────────────────────────────────────────────────────────────────────
# Queue / Processing / Helpers
# ──────────────────────────────────────────────────────────────────────────────

queue = asyncio.Queue()
processing_request = False

@tasks.loop(seconds=1.0)
async def start_queue_processing():
    if not processing_request and not queue.empty():
        await process_queue()

async def process_queue():
    global processing_request
    while True:
        if not processing_request and not queue.empty():
            request = await queue.get()
            aco, interaction, order_link, cardNumber, expDate, cvv, email, type, zipCode = request
            try:
                if not processing_request:
                    processing_request = True
                    try:
                        if not aco:
                            data = await database.getFirstInfo(type)
                            if isinstance(data, str):
                                await interaction.followup.send(data)
                                return
                            cardNumber, expDate, cvv, email = data
                        aco = False
                        await confirmRequest(aco, interaction, order_link, cardNumber, expDate, cvv, zipCode, email, type)
                    except Exception as e:
                        print(f"Error occured at process_queue func: {e}")
            finally:
                processing_request = False
                queue.task_done()
        await asyncio.sleep(1)

async def confirmRequest(aco, interaction, order_link, cardNumber, expDate, cvv, zipCode, emailAcc, type):
    msg = await interaction.followup.send(f"Processing order: {order_link} with {type}.\nPlease confirm all information is correct.")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return str(reaction.emoji) in ["✅", "❌"] and user.id == interaction.user.id and reaction.message.id == msg.id

    try:
        reaction, user = await bot.wait_for("reaction_add", timeout=60, check=check)
        if str(reaction.emoji) == "✅":
            try:
                print(f"{interaction.user.name} is attempting to place an order.")
                await asyncio.wait_for(
                    woolix(bot, interaction, order_link, cardNumber, expDate, cvv, zipCode, emailAcc, aco, type),
                    timeout=240
                )
            except asyncio.TimeoutError:
                await interaction.followup.send("Order process timed out (Too long). Please try again.")
        else:
            await interaction.followup.send("Task Cancelled...")
            print(f"{interaction.user.name} has cancelled order.")
    except asyncio.TimeoutError:
        await interaction.followup.send("Timed out. Please input an answer next time.")

# Log DMs to a channel
@bot.event
async def on_message(message):
    if message.guild is None and not message.author.bot:
        embed = discord.Embed(
            title="New DM Received",
            description=f"**From:** {message.author} ({message.author.id})\n\n**Message:** {message.content}",
            color=discord.Color.blue(),
        )
        # replace with your log channel ID:
        await bot.get_channel(1420770900906872893).send(embed=embed)

# ──────────────────────────────────────────────────────────────────────────────
# Startup / Command sync
# ──────────────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Start background queue processor
    if not start_queue_processing.is_running():
        start_queue_processing.start()

    # Command sync
    try:
        if GUILD_ID_ENV:
            guild = discord.Object(id=int(GUILD_ID_ENV))
            synced = await bot.tree.sync(guild=guild)
            print(f"[SYNC] Synced {len(synced)} command(s) to guild {GUILD_ID_ENV}")
        else:
            synced = await bot.tree.sync()
            print(f"[SYNC] Globally synced {len(synced)} command(s)")
    except Exception as e:
        print(f"[SYNC] Failed to sync commands: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────────────
if not BOT_TOKEN:
    raise SystemExit("[FATAL] BOT_TOKEN is not set in environment")
bot.run(BOT_TOKEN)
