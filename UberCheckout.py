import os
import re
import asyncio
import aiohttp
import discord
import database
from dotenv import load_dotenv
from bypass import bypass

# =========================
# Load config
# =========================
load_dotenv()
USER_TOKEN = os.getenv("USER_TOKEN")
APP_ID = os.getenv("DISCORD_APPLICATION_ID", "1420791950893907998")  # your new bot app id
GUILD_ID_DEFAULT = os.getenv("DISCORD_GUILD_ID")  # optional, can be None

# =========================
# Constants / Text
# =========================
REQUEST_ORDER = ("Please provide the following information in one reply, separated by commas:\n "
                 "`GroupOrderLink,cardnumber,expmonth/expyear,cvv,zipcode,email, Extral Promo(optional)`")
CHANGE_EMAIL = "Would you like to change your email address? (yes/no)"
UBER_REACTIONS = "🚀 Proceed to checkout\n🏬 Update Address 2"
UBER_REACTIONS_2 = ("🚀 Proceed to checkout\n🏬 Update Address 2\n🎁 Modify tip\n"
                    "🚪 Switch Delivery Type (current: Hand to customer)\n👤 Change Name\n📝 Add Delivery Notes\n❌ Cancel")
ITEM_MISSING = "❌ Please Make Another Selection"
AUTH_HOLD = "Detected 2 authorization holds. Processing 3DS..."
AUTH_PROVIDE = "Please provide verification amounts separated by comma (e.g. 85,44)"
ERROR_MESSAGE = ("Something went wrong, could be Daisy key error issue or incorrect payment info, "
                 "please try again.")
ERROR_WEBHOOK = "https://discord.com/api/webhooks/1357083321544212674/XMdL6tUWaW0n8LLA_atzZX91Ajqai2Eb2t5ZlrFwGm20JBA8vXn3Ej6ECh6LeQzR0XY5"
CART_LOCK = ("Error happend while joining draft order, make sure group order is not cancled or "
             "locked and try again.")
STORE_UNAVAILABLE = ("❌ Checkout Error\n**Store is currently unavailable**\n"
                     "Store is not available at the moment. You can schedule an order for when they are open, "
                     "or find a different store that is open now.")
SELECTED_STORES = ("https://www.ubereats.com/marketing?mft=TARGETING_STORE_PROMO&p&"
                   "promotionUuid=449baf92-dda2-44d1-9ad6-24033c26f516&"
                   "targetingStoreTag=restaurant_us_target_all")

INTERACTION_API = "https://discord.com/api/v10/interactions"
WOOLIX_CHANNEL = "https://discord.com/api/v10/channels/1405975991322542130/messages"
# Derive numeric channel id from the URL once so we can reuse it in payloads
WOOLIX_CHANNEL_ID = WOOLIX_CHANNEL.split("/channels/")[1].split("/")[0]

headers = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "authorization": USER_TOKEN,
    "dnt": "1",
    "origin": "https://discord.com",
    "priority": "u=1, i",
    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "x-debug-options": "bugReporterEnabled",
    "x-discord-locale": "en-US",
    "x-discord-timezone": "America/New_York",
}

# =========================
# UI Helpers
# =========================
class TimeWindowSelect(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=30)
        self.selected_value = None
        self.options = [
            discord.SelectOption(label=opt["label"], value=opt["value"], description=opt.get("description", ""))
            for opt in options
        ]
        self.select = discord.ui.Select(
            custom_id="time_window_select",
            placeholder="Select a delivery time window",
            options=self.options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        self.selected_value = self.select.values[0]
        selected_label = next(opt.label for opt in self.options if opt.value == self.selected_value)
        await interaction.response.edit_message(content=f"You selected: **{selected_label}**", view=None)
        self.stop()

    async def wait_for_selection(self):
        await self.wait()
        return self.selected_value

# =========================
# HTTP session
# =========================
async def create_session():
    return aiohttp.ClientSession()

# =========================
# Utility / Message helpers
# =========================
async def ERRORMESSAGEHOOK(session, name, msg1, msg2):
    await session.post(ERROR_WEBHOOK, data={"content": f"Error occured at {name} func:\n{msg1}\n{msg2}"})
    return

async def returnMessage(msg, session):
    data = {"content": f"{msg}", "tts": False}
    async with session.post(WOOLIX_CHANNEL, data=data, headers=headers) as response:
        return response

def _derive_app_and_guild_from_message(msg):
    """
    Safely derive application_id and guild_id from a Discord message object.
    Falls back to configured defaults where possible.
    """
    app_id = msg.get("application_id") or (msg.get("author") or {}).get("id") or APP_ID
    guild_id = msg.get("guild_id") or GUILD_ID_DEFAULT
    return str(app_id), str(guild_id) if guild_id else None

# =========================
# Interactions payloads
# =========================
def OTPInteraction(email):
    # Slash command invoke payload for /otp using *your* app id
    return {
        "type": 2,
        "application_id": APP_ID,
        "channel_id": "1405975991322542130",
        "session_id": "66ee3d4285916d7ed81f9286a6a062bc",
        "data": {
            "version": "1420614686013001771",   # keep these in sync with the command version you see in the UI
            "id": "1386840161907642439",
            "name": "otp",
            "type": 1,
            "options": [{"type": 3, "name": "email", "value": email}],
            "application_command": {
                "id": "1386840161907642439",
                "type": 1,
                "application_id": APP_ID,
                "version": "1420614686013001771",
                "name": "otp",
                "description": "Get OTP code for an email address",
                "options": [{
                    "type": 3,
                    "name": "email",
                    "description": "The email to get OTP for",
                    "required": True,
                    "description_localized": "The email to get OTP for",
                    "name_localized": "email"
                }],
                "dm_permission": True,
                "contexts": [0, 1, 2],
                "integration_types": [0, 1],
                "global_popularity_rank": 1,
                "description_localized": "Get OTP code for an email address",
                "name_localized": "otp"
            },
            "attachments": []
        },
        "nonce": "",
        "analytics_location": "slash_ui"
    }

def scheduleInteraction(message_id, selection, app_id=None, guild_id=None):
    # Select component interaction (type=3)
    return {
        "type": 3,
        "nonce": "",
        "guild_id": str(guild_id) if guild_id else None,
        "channel_id": "1405975991322542130",
        "message_flags": 0,
        "message_id": str(message_id),
        "application_id": str(app_id or APP_ID),
        "session_id": "ccdc15a7a461176140ee68ea468b52c3",
        "data": {
            "component_type": 3,
            "custom_id": "time_window_select",
            "type": 3,
            "values": [f"{selection}"]
        }
    }

def interactionPayload(message_id, custom_id, app_id=None, guild_id=None):
    # Button component interaction (type=3)
    return {
        "type": 3,
        "nonce": "",
        "guild_id": str(guild_id) if guild_id else None,
        "channel_id": "1405975991322542130",
        "message_flags": 0,
        "message_id": str(message_id),
        "application_id": str(app_id or APP_ID),
        "session_id": "070f7136d42d6e4703f1e12a7c99b746",
        "data": {
            "component_type": 2,
            "custom_id": custom_id
        }
    }

# =========================
# Fare/Embed builders
# =========================
async def filterACO(session, userID, fare_data, emailAcc, tip):
    print("Grabbing ACO Fare with embed data")
    subtotal = fare_data["subtotal"]
    delivery_fee = fare_data["delivery_fee"]
    taxes = fare_data["taxes"]
    total_after_tip = fare_data["total_after_tip"]
    cart_items = fare_data["cart_items"]
    address = fare_data["address"]
    promotion = fare_data["promotion"]
    canCheckOut = True

    if subtotal and delivery_fee is not None and address:
        try:
            user_credits = float(await database.getBalance(str(userID)))
            deduction = round(9 + tip + delivery_fee + taxes, 2)
            remaining_credits = round(user_credits - deduction, 2)
            if remaining_credits < 0:
                canCheckOut = False
                embed = discord.Embed(
                    title="Not enough Credits!",
                    description=f"Not enough credits for this order, need a total of {deduction} credits",
                    color=discord.Color.red()
                )
                return embed, 0, 0, False

            credits_message = (
                f"**Credits Breakdown:**\n"
                f"========================\n"
                f"Current Credits:    ${user_credits:.2f}\n"
                f"Credits Deduction: -${deduction:.2f}\n"
                f"------------------------\n"
                f"Remaining Credits:  ${remaining_credits:.2f}\n"
            )
            og_total = subtotal + delivery_fee + taxes
            embed = discord.Embed(
                title="🍽️ DiscountPlug Delivery Order Details",
                color=discord.Color.orange()
            )
            embed.add_field(name="DiscountPlug🆔", value=f"`{userID}`", inline=False)
            embed.add_field(name="🧾 UberEats Receipt", value="", inline=False)
            embed.add_field(name="Subtotal", value=f"${subtotal:.2f}", inline=True)
            embed.add_field(name="Promotion", value=f"-${promotion:.2f}", inline=True)
            embed.add_field(name="Delivery Fee", value=f"${delivery_fee:.2f}", inline=True)
            embed.add_field(name="Taxes & Fees", value=f"${taxes:.2f}", inline=True)
            embed.add_field(name="Tip", value=f"${tip:.2f}", inline=True)
            embed.add_field(name="💰 Total", value=f"**${og_total:.2f}**", inline=False)
            embed.add_field(name="🍔 Items Placed", value=cart_items or "No items", inline=False)
            embed.add_field(name="📍 Address", value=address, inline=True)
            embed.add_field(name="🎁 Credits Applied", value=credits_message, inline=False)
            return embed, deduction, total_after_tip, canCheckOut
        except Exception as e:
            await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer in filterACO: {e}"})
            embed = discord.Embed(
                title="Please open a manual order ticket.",
                description="Error with generating order fare.",
                color=discord.Color.red()
            )
            return embed, 0, 0, False
    else:
        await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer: {fare_data}"})
        embed = discord.Embed(
            title="Please open a manual order ticket.",
            description="Error with generating order fare.",
            color=discord.Color.red()
        )
        return embed, 0, 0, False

async def filterFare(interaction, session, userID, fare_data, emailAcc, tip):
    print("Grabbing Fare with embed data")
    try:
        tip = float(tip) if tip is not None else 0
    except (ValueError, TypeError):
        tip = 0

    subtotal = fare_data.get("subtotal", 0)
    delivery_fee = fare_data.get("delivery_fee", 0)
    taxes = fare_data.get("taxes", 0)
    total_after_tip = fare_data.get("total_after_tip", 0)
    cart_items = fare_data.get("cart_items", "No items")
    address = fare_data.get("address", "Unknown address")
    promotion = fare_data.get("promotion", 0)
    canCheckOut = True

    if subtotal and delivery_fee is not None and address:
        try:
            if subtotal < 20:
                embed = discord.Embed(
                    title="Error: Subtotal Too Low",
                    description="The subtotal is too low. Please make sure it is above $20.00.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return embed, 0, 0, False

            if subtotal > 30.00:
                embed = discord.Embed(
                    title="Error: Subtotal Too High",
                    description="The subtotal is too High. Please make sure it is under $30.00.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return embed, 0, 0, False

            surcharge = 0
            if subtotal > 25:
                surcharge = subtotal - 25
            if delivery_fee + taxes > 9:
                surcharge = surcharge + ((delivery_fee + taxes) - 9)

            deduction = round(9 + total_after_tip, 2)
            user_credits = float(await database.getBalance(str(userID)))
            remaining_credits = round(user_credits - deduction, 2)
            if remaining_credits < 0:
                canCheckOut = False
                embed = discord.Embed(
                    title="Not enough Credits!",
                    description=f"Need a total of {deduction} credits.\nMissing {remaining_credits} credits.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return embed, 0, 0, False

            await database.setAddy(address)
            if await database.checkAddy():
                embed = discord.Embed(
                    title="Address Ban",
                    description="Your address has been banned by Uber, please wait 2 days before trying again. Or try placing at a nearby address.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return embed, 0, 0, False

            credits_message = (
                f"**Credits Breakdown:**\n"
                f"========================\n"
                f"Current Credits:    ${user_credits:.2f}\n"
                f"Credits Deduction: -${deduction:.2f}\n"
                f"------------------------\n"
                f"Remaining Credits:  ${remaining_credits:.2f}\n"
            )
            og_total = subtotal + delivery_fee + taxes

            embed = discord.Embed(
                title="🍽️ DiscountPlug Order Details",
                color=discord.Color.orange()
            )
            embed.add_field(name="DiscountPlug", value=f"`{userID}`", inline=False)
            embed.add_field(name="🧾 UberEats Receipt", value="", inline=False)
            embed.add_field(name="Subtotal", value=f"${subtotal:.2f}", inline=True)
            embed.add_field(name="Delivery Fee", value=f"${delivery_fee:.2f}", inline=True)
            embed.add_field(name="Taxes & Fees", value=f"${taxes:.2f}", inline=True)
            embed.add_field(name="Tip", value=f"${tip:.2f}", inline=True)
            embed.add_field(name="💰 Total", value=f"**${og_total:.2f}**", inline=False)
            embed.add_field(name="🍔 Items Placed", value=cart_items or "No items", inline=False)
            embed.add_field(name="📍 Address", value=address, inline=True)
            embed.add_field(name="🎁 Credits Applied", value=credits_message, inline=False)
            return embed, deduction, total_after_tip, canCheckOut
        except Exception as e:
            await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer in filterFare: {e}"})
            embed = discord.Embed(
                title="Please open a manual order ticket.",
                description=f"Error with generating order fare: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return embed, 0, 0, False
    else:
        await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer: {fare_data}"})
        embed = discord.Embed(
            title="Please open a manual order ticket.",
            description="Error with generating order fare.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)
        return embed, 0, 0, False

# =========================
# Success embed
# =========================
async def successOrderMsg(interaction, order_details, moneySaved):
    print("successOrderMsg - Processing order_details:", order_details)
    if not order_details or not isinstance(order_details, list) or not order_details[0].get("fields"):
        await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
        return

    embed = discord.Embed(
        title="🎉Successfully Placed Order!🎉",
        description="",
        color=order_details[0].get("color", discord.Color.orange().value),
    )

    try:
        store = order_details[0]["fields"][0].get("value", "Unknown Store") if len(order_details[0]["fields"]) > 0 else "Unknown Store"
        embed.description = f"**Store:** {store}\n"

        items = order_details[0]["fields"][2].get("value", "No items found") if len(order_details[0]["fields"]) > 2 else "No items found"
        embed.add_field(name="Items Ordered:", value=items, inline=False)

        embed.add_field(name="You Saved:", value=f'${moneySaved:.2f}', inline=True)

        order_link = order_details[0].get("url", "No link available")
        if len(order_details[0]["fields"]) > 4:
            order_link = order_details[0]["fields"][3].get("value", order_link)
        embed.add_field(name="Order Link:", value=order_link, inline=True)

        address = order_details[0]["fields"][11].get("value", "Unknown address") if len(order_details[0]["fields"]) > 12 else "Unknown address"
        embed.add_field(name="Delivery Address:", value=address, inline=False)

        embed.add_field(name="DiscountPlug UUID:", value=str(interaction.user.id), inline=True)

        await interaction.followup.send(embed=embed)
        await asyncio.sleep(0.5)

    except Exception as e:
        print(f"successOrderMsg - Error: {e}")
        await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")

# =========================
# Flow helpers
# =========================
async def getOrderInfoMSG(session):
    err_count = 0
    while True:
        async with session.get(f"{WOOLIX_CHANNEL}?limit=2", headers=headers) as response:
            try:
                json_data = await response.json()
                if json_data[0]["content"] == REQUEST_ORDER:
                    print("Order Info Message Found!")
                    return True
                elif json_data[0]["content"] == "!aco":
                    pass
                else:
                    print("Found unknown message.")
                    try:
                        await ERRORMESSAGEHOOK(session, "getOrderInfoMSG", json_data[1]["content"], json_data[0]["content"])
                    except:
                        await session.post(ERROR_WEBHOOK, data={"content": "Trouble sending original error message, found unknown message."})
                    return False
            except Exception as e:
                print(f"Error fetching messages: {e}")
                if err_count >= 3:
                    await session.post(ERROR_WEBHOOK, data={"content": "Exception error occur 3 times at getOrderInfoMSG func"})
                    return False
                err_count += 1
        await asyncio.sleep(2)

async def getOTPMSG(session):
    otpTries = 0
    while otpTries < 7:
        try:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=1", headers=headers) as response:
                json_data = await response.json()
                if json_data[0]["content"] == "Please provide your email OTP":
                    await asyncio.sleep(1)
                    return True
                elif json_data[0]["content"] == ERROR_MESSAGE:
                    await session.post(ERROR_WEBHOOK, data={"content": f"Error occured at getOTPMSG func:\n{json_data[0]['content']}"})
                    return False
        except:
            pass
        otpTries += 1
        await asyncio.sleep(2)
    await session.post(ERROR_WEBHOOK, data={"content": "Could not find provide OTP message."})
    return False

async def OTP(interaction, session, emailAcc):
    print("Getting OTP")
    changeEmail = emailAcc.split("@")
    prefix = changeEmail[0]
    newEmail = prefix + "@outlook"

    if await getOTPMSG(session):
        print("Got the message for OTP")
        otpMSG = await interaction.followup.send("Inputting Cart Items.")
        await asyncio.sleep(3)
        response = await session.post(INTERACTION_API, json=OTPInteraction(emailAcc), headers=headers)
        print("POST status:", response.status)
        print("POST reply:", await response.text())
        err_count = 0
        await asyncio.sleep(5)

        while True:
            try:
                async with session.get(f"{WOOLIX_CHANNEL}?limit=4", headers=headers) as response:
                    json_data = await response.json()
                    for message in json_data:
                        print("OTP - Message Content:", message.get("content", "No content"), "Embeds:", message.get("embeds", "No embeds"))

                    if json_data[0]["content"] == "Please enter the new email address:":
                        # Always send newEmail once asked
                        await asyncio.sleep(1)
                        await returnMessage(newEmail, session)
                        await asyncio.sleep(3)
                        # We removed direct imap fetching; rely on /otp flow to fetch the code.
                        await otpMSG.edit(content="Obtaining fare breakdown from Uber.")
                        await asyncio.sleep(1)
                        return True

                    elif json_data[0]["content"] == CHANGE_EMAIL:
                        await otpMSG.edit(content="Obtaining fare breakdown from Uber.")
                        await asyncio.sleep(1)
                        await returnMessage("no", session)
                        return True

                    elif "Failed to create payment method." in json_data[0]["content"]:
                        await database.setDeadStatus(emailAcc)
                        print("Found dead payment")
                        return False

                    elif "Claimed savings: " in json_data[0]["content"]:
                        await otpMSG.edit(content="Obtaining fare breakdown from Uber.")
                        return True

                    elif "Subscribe to" in json_data[0]["content"]:
                        await otpMSG.edit(content="Obtaining fare breakdown from Uber.")
                        return True

                    elif "Please enter payment info in format for card ending" in json_data[0]["content"]:
                        print("Card needs to be reconfirmed")
                        return False

                    elif json_data[0]["content"] == "Please provide your email OTP":
                        # loop until handler updates
                        pass

                    elif json_data[0]["content"] == ERROR_MESSAGE:
                        await otpMSG.edit(content="Error message occurred at Cart. Please try placing again.")
                        await ERRORMESSAGEHOOK(session, "OTP", json_data[1]["content"], json_data[0]["content"])
                        return False

                    elif json_data[0]["content"] == CART_LOCK:
                        await otpMSG.edit(content="Error message occurred at Cart. Your cart is locked, please unlock.")
                        await ERRORMESSAGEHOOK(session, "OTP", json_data[1]["content"], json_data[0]["content"])
                        return False

            except Exception as e:
                print(f"OTP - Error fetching messages: {e}")
                if err_count >= 3:
                    await otpMSG.edit(content="Cart did not respond, Please contact an admin about this issue.")
                    await session.post(ERROR_WEBHOOK, data={"content": "Exception error occurred 3 times at OTP func"})
                    return False
                err_count += 1
            await asyncio.sleep(2)

    await interaction.followup.send("Could not find Cart Items. Please try placing order again.")
    return False

async def GetFare(session, interaction, message_id, emailAcc, aco, tip):
    print("Getting Fare - Starting process, emailAcc:", emailAcc)
    err_count = 0
    max_attempts = 10
    attempt = 0
    while attempt < max_attempts:
        try:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=10", headers=headers) as response:
                response_json = await response.json()
                for msg_idx, message in enumerate(response_json):
                    print(f"GetFare - Message {msg_idx} Details: Content: {message.get('content', 'No content')}, Embeds: {message.get('embeds', 'No embeds')}")
                    if message.get("embeds"):
                        for embed_idx, embed in enumerate(message["embeds"]):
                            if "Checkout Information" in embed.get("title", ""):
                                fields = embed.get("fields", [])
                                fare_breakdown = next((f["value"] for f in fields if "Order Details" in f["name"]), "")
                                tip_value = next((f["value"] for f in fields if "Tip" in f["name"]), "**$0**")
                                order_total = next((f["value"] for f in fields if "Order Total" in f["name"]), "**$0**")

                                fare_lines = fare_breakdown.split("\n") if fare_breakdown else []
                                cart_items = "Items could not be found."
                                address = "Unknown address"
                                subtotal = promotion = delivery_fee = taxes = total = 0

                                cart_section = []
                                in_cart_section = False
                                for line in fare_lines:
                                    if "CART ITEMS:" in line:
                                        in_cart_section = True
                                    elif "FARE BREAKDOWN:" in line:
                                        in_cart_section = False
                                    elif in_cart_section and line.strip() and not line.startswith("```"):
                                        cart_section.append(line.strip())
                                    elif "DELIVERY ADDRESS:" in line:
                                        address_index = fare_lines.index(line) + 1
                                        if address_index < len(fare_lines):
                                            address = fare_lines[address_index].strip("```").strip()
                                    elif "Subtotal:" in line:
                                        subtotal = float(line.split(": ")[1].replace("$", ""))
                                    elif "Promotion" in line:
                                        promotion = float(line.split(": ")[1].replace("-$", "").replace("$", ""))
                                    elif "Delivery Fee:" in line:
                                        delivery_fee = float(line.split(": ")[1].replace("$", ""))
                                    elif "Taxes & Other Fees:" in line:
                                        taxes = float(line.split(": ")[1].replace("$", ""))
                                    elif "Total:" in line:
                                        total = float(line.split(": ")[1].replace("$", ""))

                                if cart_section:
                                    cart_items = "\n".join(cart_section)

                                tip_amount = float(tip_value.replace("**$", "").replace("**", "") if tip_value else 0)
                                total_after_tip = float(order_total.replace("**$", "").replace("**", "") if order_total else 0)

                                fare_data = {
                                    "subtotal": subtotal,
                                    "promotion": promotion,
                                    "delivery_fee": delivery_fee,
                                    "taxes": taxes,
                                    "total": total,
                                    "tip": tip_amount,
                                    "total_after_tip": total_after_tip,
                                    "cart_items": cart_items,
                                    "address": address
                                }
                                return True, fare_data, message_id, True
        except Exception as e:
            print(f"GetFare - Error fetching messages: {e}")
            if err_count >= 3:
                await session.post(ERROR_WEBHOOK, data={"content": f"Exception error occurred 3 times in GetFare function: {e}"})
                return False, 0, 0, True
            err_count += 1
        attempt += 1
        await asyncio.sleep(5)
    return False, 0, 0, False

async def reCheckOut(session, interaction, emailAcc, aco, tip):
    await asyncio.sleep(5)
    err_count = 0
    while True:
        try:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=4", headers=headers) as response:
                json_data = await response.json()
                if UBER_REACTIONS in json_data[0]["content"]:
                    return await GetFare(session, interaction, json_data[0]["id"], emailAcc, aco, tip)
                elif json_data[0]["content"] == ERROR_MESSAGE:
                    await interaction.followup.send(json_data[1]["content"])
                    await ERRORMESSAGEHOOK(session, "CHECKOUT", json_data[1]["content"], json_data[0]["content"])
                    return False, 0, 0, 1, True
                elif ITEM_MISSING in json_data[0]["content"]:
                    await interaction.followup.send(json_data[0]["content"])
                    await session.post(ERROR_WEBHOOK, data={"content": f"Error occured at reCheckout func:\n{json_data[0]['content']}"})
                    return False, 0, 0, 1, True
        except Exception as e:
            print(f"Error fetching messages: {e}")
            if err_count >= 3:
                await session.post(ERROR_WEBHOOK, data={"content": "Exception error occur 3 times at reCheckout func"})
                return False, 0, 0, 1, True
            err_count += 1
        await asyncio.sleep(3)

async def CHECK3DS(bot, session, interaction):
    print("in 3ds")
    await asyncio.sleep(1)
    await interaction.followup.send("Please provide verification amounts separated by comma (e.g. 85,44)")
    def check_message(msg):
        return msg.author == interaction.user and msg.channel == interaction.channel
    response = await bot.wait_for("message", timeout=60, check=check_message)
    await returnMessage(response.content, session)
    await asyncio.sleep(3)
    while True:
        try:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=1", headers=headers) as response:
                json_data = await response.json()
                if json_data[0]["content"] in [
                    "3DS challenge processed successfully. Checking out again...",
                    "Successfully checked out the order!",
                    ""
                ]:
                    return True
                else:
                    return False
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(3)

async def FINAL_CHECK(bot, session, interaction, moneySaved, cost, orderLink, emailAcc, aco):
    print("Entering Final Checkout")
    await asyncio.sleep(10)
    max_poll_attempts = 20
    attempt = 0

    while attempt < max_poll_attempts:
        try:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=10", headers=headers) as response:
                json_data = await response.json()

                success_embed_found = False
                success_message = None
                for msg in reversed(json_data):
                    if msg.get("embeds"):
                        embed = msg["embeds"][0]
                        if ("Order Successfully Placed" in embed.get("title", "")
                            or any("Order Link" in f.get("name", "") for f in embed.get("fields", []))):
                            success_embed_found = True
                            success_message = msg
                            break
                        elif embed.get("title") == "❌ Checkout Failed" or "Timed out waiting for response" in msg.get("content", ""):
                            if not aco:
                                if "Promotion codes have been deemed invalid for this account and all trips will be ordered at the full price." in embed.get("description", ""):
                                    await database.incrementAddy()
                                if "Store is not available at the moment" in embed.get("description", ""):
                                    await interaction.followup.send("Store closed, please select another store.")
                                else:
                                    await database.setDeadStatus(emailAcc)
                                    await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                            await ERRORMESSAGEHOOK(session, "FINAL_CHECK", msg.get("content", ""), str(msg.get("embeds", [])))
                            return

                if success_embed_found:
                    await asyncio.sleep(5)
                    async with session.get(f"{WOOLIX_CHANNEL}?limit=10", headers=headers) as response2:
                        json_data2 = await response2.json()

                        confirmation_found = any(
                            m.get("content") in ("More actions after checkout?", "Uber One cancelled after two sucessful orders")
                            for m in json_data2
                        )
                        if confirmation_found:
                            embed_to_send = [m["embeds"][0] for m in json_data2 if m.get("embeds") and m["id"] == success_message["id"]]
                            if embed_to_send:
                                try:
                                    await successOrderMsg(interaction, embed_to_send, moneySaved)
                                except Exception as e:
                                    await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
                            else:
                                await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
                            if not aco:
                                await database.updateInfo(emailAcc)
                            try:
                                await database.updateBalance(interaction.user.id, -moneySaved, cost, orderLink)
                            except Exception as e:
                                print(f"FINAL_CHECK - Error updating balance: {e}")
                            await database.resetAddy()
                            await bot.get_channel(1420771626223534090).send(f"<@{interaction.user.id}> has placed a successful UE order for ${moneySaved}!")
                            return
                        else:
                            print("FINAL_CHECK - No 'More actions after checkout?' found, waiting...")

                elif json_data[0].get("content") == "Successfully checked out the order!":
                    for msg in json_data:
                        if msg.get("embeds"):
                            try:
                                await successOrderMsg(interaction, msg["embeds"], moneySaved)
                            except Exception as e:
                                await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
                            break
                    else:
                        await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
                    if not aco:
                        await database.updateInfo(emailAcc)
                    try:
                        await database.updateBalance(interaction.user.id, -moneySaved, cost, orderLink)
                    except Exception as e:
                        print(f"FINAL_CHECK - Error updating balance: {e}")
                    await database.resetAddy()
                    await bot.get_channel(1420771626223534090).send(f"<@{interaction.user.id}> has placed a successful UE order for ${moneySaved}!")
                    return
                elif json_data[0].get("content") == "Would you like to cancel UE One?":
                    index = 1
                    if len(json_data) > 1 and json_data[1].get("content") == "Would you like to cancel UE One?":
                        index = 2
                    if index < len(json_data) and json_data[index].get("embeds") and json_data[index]["embeds"][0].get("title") == "❌ Checkout Failed":
                        if not aco:
                            if "Promotion codes have been deemed invalid for this account and all trips will be ordered at the full price." in json_data[index]["embeds"][0].get("description", ""):
                                await database.incrementAddy()
                            await database.setDeadStatus(emailAcc)
                        await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                        await ERRORMESSAGEHOOK(session, "FINAL_CHECK", json_data[1].get("content", ""), str(json_data[index].get("embeds", [])))
                        return
                elif json_data[0].get("embeds"):
                    if json_data[0]["embeds"][0].get("title") == "❌ Checkout Failed":
                        if not aco:
                            if "Promotion codes have been deemed invalid for this account and all trips will be ordered at the full price." in json_data[0]["embeds"][0].get("description", ""):
                                await database.incrementAddy()
                            if "Store is not available at the moment" in json_data[0]["embeds"][0].get("description", ""):
                                await interaction.followup.send("Store closed, please select another store.")
                            else:
                                await database.setDeadStatus(emailAcc)
                                await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                        await ERRORMESSAGEHOOK(session, "FINAL_CHECK", json_data[0].get("content", ""), str(json_data[0].get("embeds", [])))
                        return
                elif json_data[0].get("content") == ERROR_MESSAGE:
                    if not aco:
                        await database.setDeadStatus(emailAcc)
                        await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                        await ERRORMESSAGEHOOK(session, "FINAL_CHECK", json_data[1].get("content", ""), "Error occurred at checkout, daisy/payment issue.")
                    return
        except Exception as e:
            print(f"FINAL_CHECK - Error: {e}")

        attempt += 1
        await asyncio.sleep(5)

    await interaction.followup.send("Order status unclear. Please check UberEats for confirmation and contact support if needed.")
    await session.post(ERROR_WEBHOOK, data={"content": f"Order for {interaction.user.id} timed out but may have succeeded. OrderLink: {orderLink}"})

async def CHECKFORPROMO(messages, emailAcc, type, aco):
    print("Checking Promos")
    if aco:
        return True
    promos = []
    for i in range(len(messages) - 1, -1, -1):
        promo_match = re.search(r"Claimed savings:\s*(.*)", messages[i]["content"])
        if promo_match:
            result = promo_match.group(1)
            promos.append(result)

    if len(promos) > 0:
        if promos[0] == "$30 off":
            await database.updateType(emailAcc, "30")
            return True
        elif promos[0] == "$25 off":
            await database.updateType(emailAcc, "s25")
            return True
        elif promos[0] == "$25 off (selected stores)":
            await database.updateType(emailAcc, "s25")
            if type in ("s25", "s20"):
                return True
            else:
                return False
        elif promos[0] in ("$20 off", "$20 off (selected stores)"):
            await database.updateType(emailAcc, "s25")
            return True
        else:
            print("Couldnt get the account type")
            return False
    else:
        await database.setDeadStatus(emailAcc)
        return False

async def CHECKOUT(session, interaction, emailAcc, aco, type):
    print("CHECKOUT - Starting process, emailAcc:", emailAcc)
    err_count = 0
    while True:
        try:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=6", headers=headers) as response:
                json_data = await response.json()
                for msg_idx, message in enumerate(json_data):
                    print(f"CHECKOUT - Message {msg_idx} Content:", message.get("content", "No content"), "Embeds:", message.get("embeds", "No embeds"))
                    if message.get("embeds"):
                        for embed in message["embeds"]:
                            if "Checkout Information" in embed.get("title", ""):
                                result = await GetFare(session, interaction, json_data[0]["id"], emailAcc, aco, 0)
                                return result
                if json_data[0]["content"] == ERROR_MESSAGE:
                    await interaction.followup.send(json_data[1]["content"])
                    await ERRORMESSAGEHOOK(session, "CHECKOUT", json_data[1]["content"], json_data[0]["content"])
                    return False, 0, 0, 1, True
                elif ITEM_MISSING in json_data[0]["content"]:
                    await interaction.followup.send(json_data[0]["content"])
                    await session.post(ERROR_WEBHOOK, data={"content": f"Error occurred at CHECKOUT func:\n{json_data[0]['content']}"})
                    return False, 0, 0, 1, True
        except Exception as e:
            print(f"CHECKOUT - Error fetching messages: {e}")
            if "Session is closed" in str(e):
                session = await create_session()
            if err_count >= 3:
                await session.post(ERROR_WEBHOOK, data={"content": "Exception error occurred 3 times at CHECKOUT func"})
                return False, 0, 0, 1, True
            err_count += 1
        await asyncio.sleep(3)

# =========================
# Small input helpers
# =========================
async def changeAddy2(session, interaction, user_input):
    print(f"[changeAddy2] Updating address 2 to: {user_input}")
    await asyncio.sleep(2)
    try:
        await returnMessage(user_input, session)
        await interaction.followup.send(f"Address 2 updated to: {user_input}")
    except Exception as e:
        print(f"[changeAddy2] Error: {e}")
        await interaction.followup.send("An error occurred while updating the address. Please try again.")

async def changeTip(session, interaction, user_input):
    print(f"[changeTip] Updating tip to: {user_input}")
    await asyncio.sleep(2)
    try:
        await returnMessage(user_input, session)
        user_input = float(user_input)
        await interaction.followup.send(f"Tip updated to: ${user_input:.2f}")
        return user_input
    except Exception as e:
        print(f"[changeTip] Error: {e}")
        await interaction.followup.send("An error occurred while updating the tip. Please try again.")

async def changeName(session, interaction, user_input):
    print(f"[changeName] Updating name to: {user_input}")
    await asyncio.sleep(2)
    try:
        if "," not in user_input:
            name = user_input.split(" ")
            user_input = name[0] + "," + (name[1] if len(name) > 1 else "R")
        await returnMessage(user_input, session)
        await interaction.followup.send(f"Name updated to: {user_input}")
    except Exception as e:
        print(f"[changeName] Error: {e}")
        await interaction.followup.send("An error occurred while updating the Name. Please try again.")

# =========================
# Reactions / Interaction driver
# =========================
async def handleReactions(session, bot, interaction, message_id, moneySaved, cost, orderLink, emailAcc, aco):
    print("handleReactions - START: Waiting on user input, initial message_id:", message_id)

    while True:
        print("handleReactions - Fetching latest message(s) from WOOLIX_CHANNEL")
        components = []
        attempts = 0
        max_attempts = 5
        latest_message_json = None
        while not components and attempts < max_attempts:
            async with session.get(f"{WOOLIX_CHANNEL}?limit=2", headers=headers) as response:
                messages = await response.json()
                for msg in messages:
                    if msg.get("components"):
                        latest_message_json = [msg]
                        components = msg.get("components", [])
                        break
                if not components:
                    attempts += 1
                    await asyncio.sleep(2)

        if not components:
            print("handleReactions - No components found after max attempts, using default reactions")
            reactions = {"🚀": "checkout", "🏬": "update_address", "👤": "change_name", "🎯": "joggle_addy", "📅": "schedule", "❌": "cancel"}
            reaction_to_custom_id = {"🚀": "proceed_checkout", "🏬": "update_address", "👤": "change_name", "🎯": "address_joggling", "📅": "schedule_order", "❌": "cancel"}
            latest_message_json = messages[:1]
        else:
            print("handleReactions - Components found in message:", latest_message_json)

        latest_content = latest_message_json[0].get("content", "")
        message_id = latest_message_json[0].get("id")

        # Derive the correct application_id for this particular message (CRITICAL)
        app_id, guild_id = _derive_app_and_guild_from_message(latest_message_json[0])

        reactions = {}
        reaction_to_custom_id = {}
        if UBER_REACTIONS in latest_content or UBER_REACTIONS_2 in latest_content:
            lines = latest_content.split("\n")
            for line in lines:
                if "Proceed to checkout" in line and "🚀" in line:
                    reactions["🚀"] = "checkout"
                    reaction_to_custom_id["🚀"] = "proceed_checkout"
                elif "Update Address 2" in line and "🏬" in line:
                    reactions["🏬"] = "update_address"
                    reaction_to_custom_id["🏬"] = "update_address"
                elif "Change Name" in line and "👤" in line:
                    reactions["👤"] = "change_name"
                    reaction_to_custom_id["👤"] = "change_name"
                elif "Cancel" in line and "❌" in line:
                    reactions["❌"] = "cancel"
                    reaction_to_custom_id["❌"] = "cancel"
        elif components:
            allowed_custom_id_patterns = {
                "to_checkout_steps_": "proceed_checkout",
                "update_address": "update_address",
                "change_name": "change_name",
                "delivery_notes": "delivery_notes",
                "cancel": "cancel"
            }
            emoji_mapping = {
                "proceed_checkout": "🚀",
                "update_address": "🏬",
                "change_name": "👤",
                "delivery_notes": "📅",
                "cancel": "❌"
            }
            action_mapping = {
                "proceed_checkout": "checkout",
                "update_address": "update_address",
                "change_name": "change_name",
                "delivery_notes": "delivery_notes",
                "cancel": "cancel"
            }
            for component_group in components:
                for component in component_group.get("components", []):
                    custom_id = component.get("custom_id")
                    matched = False
                    for pattern, pAction in allowed_custom_id_patterns.items():
                        if custom_id and pattern in custom_id:
                            emoji = emoji_mapping.get(pAction)
                            action = action_mapping.get(pAction, "unknown")
                            if emoji:
                                reactions[emoji] = action
                                reaction_to_custom_id[emoji] = custom_id
                            matched = True
                            break
                    if not matched and custom_id:
                        # log unknowns but don't add to reactions by default
                        print(f"handleReactions - Unrecognized custom_id (not added): {custom_id}")

        print("handleReactions - Dynamic reactions set:", reactions)
        print("handleReactions - Reaction to custom_id mapping:", reaction_to_custom_id)

        reaction_message = await interaction.followup.send("React with one of the following:\n" + "\n".join([f"{k} {v}" for k, v in reactions.items()]))
        for r in reactions.keys():
            try:
                await reaction_message.add_reaction(r)
            except discord.errors.HTTPException as e:
                print(f"handleReactions - Failed to add reaction {r}: {e}")

        def check_reaction(reaction, user):
            return (str(reaction.emoji) in reactions
                    and user.id == interaction.user.id
                    and reaction.message.id == reaction_message.id)

        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=60, check=check_reaction)
            action = reactions[str(reaction.emoji)]
            custom_id = reaction_to_custom_id.get(str(reaction.emoji))

            if not custom_id:
                await interaction.followup.send("No action mapped; please try again.")
                continue

            # Send button interaction to Woolix using the *correct app_id*
            payload = interactionPayload(message_id, custom_id, app_id=app_id, guild_id=guild_id)
            async with session.post(INTERACTION_API, json=payload, headers=headers) as response:
                body = await response.text()
                print(f"handleReactions - Button interaction status: {response.status} body: {body}")

            # Input-based prompts after a button
            if action in ["update_address", "change_tip", "change_name", "delivery_notes"]:
                await asyncio.sleep(2)
                components_found = False
                attempts = 0
                max_attempts = 5
                while not components_found and attempts < max_attempts:
                    async with session.get(f"{WOOLIX_CHANNEL}?limit=1", headers=headers) as response:
                        latest_response = await response.json()
                        if latest_response[0].get("content") or latest_response[0].get("embeds"):
                            components_found = True
                            break
                    attempts += 1
                    await asyncio.sleep(2)

                if components_found:
                    prompts = {
                        "update_address": "Please input address 2...",
                        "change_tip": "Please input tip...",
                        "change_name": "Please input name in Firstname, Lastname...",
                        "delivery_notes": "Please input delivery instructions..."
                    }
                    await interaction.followup.send(prompts[action])

                    def check_message(msg):
                        return msg.author == interaction.user and msg.channel == interaction.channel

                    try:
                        response_msg = await bot.wait_for("message", timeout=60, check=check_message)
                        user_input = response_msg.content
                        await returnMessage(user_input, session)
                        if action == "change_tip":
                            try:
                                tip_val = float(user_input)
                                return tip_val
                            except ValueError:
                                await interaction.followup.send("Invalid tip value. Please try again.")
                                continue
                        continue
                    except asyncio.TimeoutError:
                        await interaction.followup.send("You took too long to respond. Please try again.")
                        continue
                else:
                    print("handleReactions - No Woolix response after button press")
                    continue

            elif action == "checkout":
                await interaction.followup.send("Checking out...")
                # possible ephemeral bypass
                if "to_checkout_steps_" in custom_id:
                    asyncio.create_task(bypass(int(WOOLIX_CHANNEL_ID), 10))
                    await asyncio.sleep(5)
                payload = interactionPayload(message_id, custom_id, app_id=app_id, guild_id=guild_id)
                async with session.post(INTERACTION_API, json=payload, headers=headers) as response:
                    print(f"handleReactions - Checkout click status: {response.status} body: {await response.text()}")
                await asyncio.sleep(2)
                await FINAL_CHECK(bot, session, interaction, moneySaved, cost, orderLink, emailAcc, aco)
                return -2

            elif action == "joggle_addy":
                await interaction.followup.send("Activated Address Joggling.")
                payload = interactionPayload(message_id, custom_id, app_id=app_id, guild_id=guild_id)
                async with session.post(INTERACTION_API, json=payload, headers=headers) as response:
                    print(f"handleReactions - Joggle click status: {response.status} body: {await response.text()}")
                continue

            elif action == "cancel":
                await interaction.followup.send("Order Cancelled...")
                return -3

        except asyncio.TimeoutError:
            await interaction.followup.send("Timed out. Order Cancelled.")
            return -3
        except Exception as e:
            print("handleReactions - ERROR:", e)
            return -3

# =========================
# Orchestrator
# =========================
async def handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, firstTime, tip):
    print("handleLoop - Starting process, emailAcc:", emailAcc)
    if firstTime:
        result, fare_data, message_id, canCheckOut = await CHECKOUT(session, interaction, emailAcc, aco, type)
    else:
        result, fare_data, message_id, canCheckOut = await reCheckOut(session, interaction, emailAcc, aco, tip)
    print("handleLoop - CHECKOUT/RECHECKOUT result:", result, fare_data, message_id, canCheckOut)

    if result and canCheckOut:
        if aco:
            embed, moneySaved, cost, canCheckOut = await filterACO(session, interaction.user.id, fare_data, emailAcc, tip)
        else:
            embed, moneySaved, cost, canCheckOut = await filterFare(interaction, session, interaction.user.id, fare_data, emailAcc, tip)

        if not canCheckOut:
            await interaction.followup.send(embed=embed)
            return False

        await interaction.followup.send(embed=embed)
        await asyncio.sleep(1)

        state = await handleReactions(session, bot, interaction, message_id, moneySaved, cost, orderLink, emailAcc, aco)
        if state == -2:
            return True
        elif state == -1:
            return await handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, False, tip)
        elif state == -3:
            return False
        else:
            return await handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, False, state)
    else:
        print("handleLoop - ended due to result/canCheckOut:", result, canCheckOut)
        return False

async def woolix(bot, interaction, orderLink, cardNumber, expDate, cvv, zipCode, emailAcc, aco, type):
    orderInfo = f"{orderLink},{cardNumber},{expDate},{cvv},{zipCode},{emailAcc}"
    session = await create_session()

    try:
        async with session:
            # Warm-up / Wake messages (kept as-is)
            await returnMessage("once", session); await asyncio.sleep(1)
            await returnMessage("twice", session); await asyncio.sleep(1)
            await returnMessage("yay", session); await asyncio.sleep(1)

            response = await returnMessage("!aco", session)
            await interaction.followup.send("Starting Order...")

            if response.status == 200:
                await asyncio.sleep(2)
                if await getOrderInfoMSG(session):
                    response = await returnMessage(orderInfo, session)
                    await interaction.followup.send("Collecting cart items.")

                    if response.status == 200:
                        await asyncio.sleep(3)
                        if not aco:
                            otp_ok = await OTP(interaction, session, emailAcc)
                            if not otp_ok:
                                await interaction.followup.send("Cart Failed.")
                                return "OTP verification failed."
                        else:
                            print("Skipping OTP step for ACO/Woolix account")

                        try:
                            await handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, True, 0)
                            return
                        except Exception as e:
                            await session.post(ERROR_WEBHOOK, data={"content": f"Problem with CHECKOUT func: {e}"})
                            await interaction.followup.send("Checkout Failed.")
                        return
                    else:
                        await interaction.followup.send("Failed to send order info.")
                        return "Failed to send order info."
                else:
                    await interaction.followup.send("Failed to retrieve order info message.")
                    return "Failed to retrieve order info message."
            else:
                await interaction.followup.send("ACO Failed!")
                await session.post(ERROR_WEBHOOK, data={"content": "Failed at !ACO, Check Token."})
                return "ACO Failed!"
    except Exception as e:
        print(f"Error occurred: {e}")
        await interaction.followup.send("An error occurred during processing.")
        return "Processing error."
    return "Processing completed."
