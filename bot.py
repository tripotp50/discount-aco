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

# ─── Voucher & Balance database (Render Disk at /data) ──────────
DATA_DIR = "/data"
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

# load voucher codes only from whitelist files, then persist to /data/codes.json
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
intents.message_content = True  # Enables message content intent for interaction
intents.reactions = True  # Required for handling reactions
intents.members = True  # Required for handling member-specific actions

# Create bot instance
bot = commands.Bot(command_prefix="!", intents=intents)
# ------------------------------------------------------------------
# /redeem — voucher code redemption
# ------------------------------------------------------------------
@bot.tree.command(name="redeem", description="Redeem an ACO voucher code")
@app_commands.describe(code="Your voucher code (e.g. ACO15-XXXXXX)")
async def redeem(interaction: discord.Interaction, code: str):
    code = code.upper().strip()

    # 1) unknown code
    if code not in codes:
        await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
        return

    # 2) already used
    if codes[code]["used"]:
        await interaction.response.send_message("❌ Code already used.", ephemeral=True)
        return

    # 3) value comes from JSON
    credit_value = codes[code]["value"]

    # 4) add credits to the local ledger
    uid = str(interaction.user.id)
    balances[uid] = balances.get(uid, 0) + credit_value
    save_balances()

    # 5) write the same credit to Mongo so /wallet sees it
    await database.updateBalance(uid, credit_value, 0, "Voucher redeem")

    # 6) flag voucher as used in codes.json
    codes[code]["used"] = True
    codes[code]["redeemed_by"] = uid
    save_codes()

    # 7) final confirmation to the user
    await interaction.response.send_message(
        f"✅ {credit_value} credits added!  New balance: **{balances[uid]} credits**.",
        ephemeral=True,
    )
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Queue to store the woolix requests
queue = asyncio.Queue()

# Flag to indicate if a request is currently being processed
processing_request = False

# Event when the bot is ready
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # Sync the command tree when the bot starts
    await bot.tree.sync()

    # Start the queue processing task when the bot is ready
    start_queue_processing.start()

# Background task to process the queue
@tasks.loop(seconds=1.0)
async def start_queue_processing():
    if not processing_request and not queue.empty():
        await process_queue()

# Queue processing function
async def process_queue():
    global processing_request
    while True:
        if not processing_request and not queue.empty():
            request = await queue.get()
            aco, interaction, order_link, cardNumber, expDate, cvv, email, type, zipCode= request
            try:
                # If we're not already processing, start processing the current request
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
                        # Handle any additional timeout logic here (e.g., log, notify admins, etc.)

            finally:
                # Mark the request as processed
                processing_request = False
                queue.task_done()  # Mark the task as done
        await asyncio.sleep(1)  # Wait 1 second before checking again

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
        #position = queue.qsize() + 1  # Position is based on current queue size + 1
        await interaction.response.send_message(f"Your order has been queued for processing.")
        if self.aco:
            await queue.put((True, interaction, self.order_link, self.cardNumber, self.expDate, self.cvv, self.email, "s25", self.zipCode))
        else:
            await queue.put((False, interaction, self.order_link, "", "", "", "", "s25", "48127"))
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Ueaco Cancelled.")
        self.stop()  # Stop the view after interaction

@bot.tree.command(name="slink", description="Check stores that are available for Selected $25 in your area.")
async def slink(interaction: discord.Interaction):
    await interaction.response.send_message("https://www.ubereats.com/marketing?mft=TARGETING_STORE_PROMO&p&promotionUuid=449baf92-dda2-44d1-9ad6-24033c26f516&targetingStoreTag=restaurant_us_target_all")

@bot.tree.command(name="ueaco", description="Uber Eats Auto Checkout, only need order link")
async def ueaco(interaction: discord.Interaction, order_link: str):
    if isinstance(interaction.channel, discord.DMChannel):  # Ensure it's in DM
       # if await database.whitelistCheck(interaction.user.id):
           # pass
        #else:
            #await interaction.response.send_message("Please buy monthly")
            #return
        if "https://eats.uber.com/group-orders/" in order_link or "https://www.ubereats.com/group-orders/" in order_link:
           # if interaction.user.id != 350494339228499969:
                #await interaction.response.send_message("Bot down, in testing.")
               # return
            #if await database.getBalance(interaction.user.id) < 12:
                #await interaction.response.send_message("Insufficient credits, please load up before attempting to place an order. DM .oukii")
                #return
            embed = discord.Embed(
                title="New DM Received",
                description=f"**From:** {interaction.user.name} ({interaction.user.id})\n\n**Message:** /ueaco {order_link}",
                color=discord.Color.blue(),
            )
            #await bot.get_channel(1364282286400606429).send(embed=embed)
            await interaction.response.send_message("Please select your discount type:", view=OrderTypeView(interaction, order_link, "", "", "", "", "", False))
        else:
            await interaction.response.send_message("Please input a UberEats group link\nExample: https://eats.uber.com/group-orders/60f61198-9b19-492a-a89a-384b205bb859/join")
    else:
        await interaction.response.send_message("This command can only be used in Direct Messages (DMs).")

@bot.tree.command(name="accleft", description="Check accounts left")
async def accleft(interaction: discord.Interaction):
    num = await database.accLeft()
    await interaction.response.send_message(f"{num} accounts are stocked!")

@bot.tree.command(name="clear", description="Clear Accounts")
async def clear(interaction: discord.Interaction):
    if interaction.user.id != [1403493273376391218]:
        await interaction.response.send_message("Not Authorized")
        return
    await interaction.response.send_message(f"Cleared used accounts")
    await database.clearAcc()

@bot.tree.command(name="setdead", description="set dead accounts")
async def dead(interaction: discord.Interaction, email: str):
    if interaction.user.id != [1403493273376391218]:
        await interaction.response.send_message("Not Authorized")
        return
    await interaction.response.send_message(f"Setting {email} dead")
    await database.setDeadStatus(email)

@bot.tree.command(name="upload", description="Upload a CSV file to MongoDB")
async def upload(interaction: discord.Interaction, csv_file: discord.Attachment):
    if interaction.user.id not in [1403493273376391218]:
        await interaction.response.send_message("Not Authorized")
    if not csv_file.filename.endswith('.csv'):
        await interaction.response.send_message("The uploaded file is not a CSV file. Please upload a valid CSV file.", ephemeral=True)
        return
    csv_data = await csv_file.read()
    result_message = await database.upload_csv_to_mongo(csv_data)
    await interaction.response.send_message(result_message)

@bot.tree.command(name="aco", description="Uber Eats Auto Checkout w own VCC")
async def aco(
    interaction: discord.Interaction,
    order_info: str  # The full order info provided by the user
):  
    if interaction.user.id != [1403493273376391218]:
        await interaction.response.send_message("Not Authorized")
        return
    if isinstance(interaction.channel, discord.DMChannel):  # Ensure it's in DM
        #if await database.whitelistCheck(interaction.user.id):
            #pass
       # else:
            #await interaction.response.send_message("Please buy monthly")
            #return
        parts = order_info.split(",")
        if len(parts) != 6:
            await interaction.response.send_message("Correct format: orderlink,cardNumber,expDate,cvv,zipcode,email")
            return
        order_link = parts[0]
        cardNumber = parts[1]
        expDate = parts[2]
        cvv = parts[3]
        zipCode = parts[4]
        email = parts[5]
        if "https://eats.uber.com/group-orders/" in order_link or "https://www.ubereats.com/group-orders/" in order_link:

            embed = discord.Embed(
                title="New DM Received",
                description=f"**From:** {interaction.user.name} ({interaction.user.id})\n\n**Message:** /aco {order_link}",
                color=discord.Color.blue(),
            )
            await bot.get_channel(1420770900906872893).send(embed=embed)
            await interaction.response.send_message("Please select your discount type:", view=OrderTypeView(interaction, order_link, cardNumber, expDate, cvv, zipCode, email, True))
        else:
            await interaction.response.send_message("Please input a UberEats group link\nExample: https://eats.uber.com/group-orders/60f61198-9b19-492a-a89a-384b205bb859/join")
    else:
        await interaction.response.send_message("This command can only be used in Direct Messages (DMs).")

async def confirmRequest(aco, interaction, order_link, cardNumber, expDate, cvv, zipCode, emailAcc, type):
    msg = await interaction.followup.send(f"Processing order: {order_link} with {type}.\nPlease confirm all information is correct.")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    # Reaction check to ensure the correct user and emoji
    def check(reaction, user):
        return str(reaction.emoji) in ['✅', '❌'] and user.id == interaction.user.id and reaction.message.id == msg.id
    try:
        # Wait for a reaction (with a timeout of 30 seconds)
        reaction, user = await bot.wait_for('reaction_add', timeout=60, check=check)
        if str(reaction.emoji) == '✅':
            try:
                print(f"{interaction.user.name} is attempting to place an order.")
                # Add the request to the queue
                await asyncio.wait_for(
                    woolix(
                        bot,
                        interaction,
                        order_link,
                        cardNumber,
                        expDate,
                        cvv,
                        zipCode,
                        emailAcc,
                        aco,
                        type
                    ),
                    timeout=240  # Timeout after 4 minutes (240 seconds)
                )
            except asyncio.TimeoutError:
                await interaction.followup.send("Order process timed out(Too long). Please try again.")
                # Handle any additional timeout logic here (e.g., log, notify admins, etc.)
        elif str(reaction.emoji) == '❌':
            await interaction.followup.send("Task Cancelled...")
            print(f"{interaction.user.name} has cancelled order.")
    except:
        await interaction.followup.send("Timed out. Please input an answer next time.")

async def loadcredits(interaction: discord.Interaction, amount: float):
    await interaction.response.defer()

    try:
        # Convert the amount to cents
        amount_in_cents = int(amount * 100)
        
        # Create a Stripe Checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",  # You can change this to another currency if needed
                    "product_data": {
                        "name": f"Load ${amount} Credits",
                    },
                    "unit_amount": amount_in_cents,
                },
                "quantity": 1,
                "tax_rates": ["txr_1QOVqnGMMMgbOUn4hWrg15lb"],
            }],
            mode="payment",
            success_url="https://discord.com/channels/@me",  # Change this to your success URL
            cancel_url="https://google.com/",  # Change this to your cancel URL
            metadata={
                "userID": f"{interaction.user.id}"  # Use colon instead of equals sign
            }
        )

        # Send the checkout session URL to the user
        await interaction.followup.send(f"Click on Stripe link to load ${amount} credits.\n{session.url}")

    except stripe.error.StripeError as e:
        # Handle errors with Stripe API
        await interaction.followup.send(f"Error: {e.user_message}")
    except Exception as e:
        # Handle other exceptions
        await interaction.followup.send(f"An error occurred: {str(e)}")

class CreditInputModal(discord.ui.Modal, title="Enter Credit Amount"):
    userID = discord.ui.TextInput(label="userID", placeholder="Enter ID", required=True)
    amount = discord.ui.TextInput(label="Credit Amount", placeholder="Enter a number", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            userID = str(self.userID)
            credit_amount = float(self.amount.value)  # Convert input to float
            await database.updateBalance(userID, credit_amount, 0, "Load Credits command")
            await interaction.response.send_message(f"You entered: {credit_amount}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid number. Please enter a valid amount.", ephemeral=True)

# Button View for the wallet command (Get Balance and Load Credits)
# ------------------------------------------------------------
# Button view shown by /wallet
# ------------------------------------------------------------
class WalletButtons(View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    # ────────────────────────────────────────────────
    # 1)  Check Balance
    # ────────────────────────────────────────────────
    @discord.ui.button(label="Check Balance", style=discord.ButtonStyle.green)
    async def check_balance(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        # Acknowledge quickly so the interaction doesn’t time out
        await interaction.response.defer(ephemeral=True)

        credits = await database.getBalance(str(interaction.user.id))
        await interaction.followup.send(
            f"Your current credit balance is: **${credits}**",
            ephemeral=True,
        )

    # ────────────────────────────────────────────────
    # 2)  Load Credits  (admin-only → opens a modal)
    # ────────────────────────────────────────────────
    @discord.ui.button(label="Load Credits", style=discord.ButtonStyle.green)
    async def load_credits(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        admin_ids: set[int] = {1403493273376391218}       # add more IDs if needed

        if interaction.user.id in admin_ids:
            # A modal must be the *first* (and only) response → NO defer
            await interaction.response.send_modal(CreditInputModal())
        else:
            # Non-admin users just get an informative message
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(
                "Please open a ticket in the server to add credits to your wallet.",
                ephemeral=True,
            )

    # ────────────────────────────────────────────────
    # 3)  Cancel button
    # ────────────────────────────────────────────────
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Wallet operation canceled.", ephemeral=True)
        self.stop()                                     # destroy the view


# ------------------------------------------------------------
# /wallet slash command
# ------------------------------------------------------------
# ------------------------------------------------------------
# /wallet  – shows the WalletButtons view
# ------------------------------------------------------------
@bot.tree.command(name="wallet", description="Check your balance or load credits")
async def wallet(interaction: discord.Interaction) -> None:
    # ⬇️  FIRST (and only) response → no defer()
    await interaction.response.send_message(
        "Choose an option from the wallet:",
        view=WalletButtons(),
        ephemeral=True,              # buttons visible only to the caller
    )



@bot.event
async def on_message(message):
    if message.guild is None and not message.author.bot:  # Check if it's a DM and not from a bot
        embed = discord.Embed(
            title="New DM Received",
            description=f"**From:** {message.author} ({message.author.id})\n\n**Message:** {message.content}",
            color=discord.Color.blue(),
        )
        await bot.get_channel(1420770900906872893).send(embed=embed)

asyncio.run(bot.run(BOT_TOKEN))  # Replace with your bot's token