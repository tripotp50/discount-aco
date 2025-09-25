import discord
import asyncio
import aiohttp
import database
import re
from dotenv import load_dotenv
import os
import imap
from bypass import bypass

load_dotenv()
USER_TOKEN = os.getenv('USER_TOKEN')

REQUEST_ORDER = "Please provide the following information in one reply, separated by commas:\n `GroupOrderLink,cardnumber,expmonth/expyear,cvv,zipcode,email, Extral Promo(optional)`"
CHANGE_EMAIL = "Would you like to change your email address? (yes/no)"
UBER_REACTIONS = "🚀 Proceed to checkout\n🏬 Update Address 2"
UBER_REACTIONS_2 = "🚀 Proceed to checkout\n🏬 Update Address 2\n🎁 Modify tip\n🚪 Switch Delivery Type (current: Hand to customer)\n👤 Change Name\n📝 Add Delivery Notes\n❌ Cancel"
ITEM_MISSING = "❌ Please Make Another Selection"
AUTH_HOLD = "Detected 2 authorization holds. Processing 3DS..."
AUTH_PROVIDE = "Please provide verification amounts separated by comma (e.g. 85,44)"
ERROR_MESSAGE = "Something went wrong, could be Daisy key error issue or incorrect payment info, please try again."
ERROR_WEBHOOK = "https://discord.com/api/webhooks/1357083321544212674/XMdL6tUWaW0n8LLA_atzZX91Ajqai2Eb2t5ZlrFwGm20JBA8vXn3Ej6ECh6LeQzR0XY5"
CART_LOCK = "Error happend while joining draft order, make sure group order is not cancled or locked and try again."
STORE_UNAVAILABLE = "❌ Checkout Error\n**Store is currently unavailable**\nStore is not available at the moment. You can schedule an order for when they are open, or find a different store that is open now."
SELECTED_STORES = "https://www.ubereats.com/marketing?mft=TARGETING_STORE_PROMO&p&promotionUuid=449baf92-dda2-44d1-9ad6-24033c26f516&targetingStoreTag=restaurant_us_target_all"

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

INTERACTION_API = "https://discord.com/api/v10/interactions"
WOOLIX_CHANNEL = "https://discord.com/api/v10/channels/1406550397199319162/messages"

class TimeWindowSelect(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=30)
        self.selected_value = None
        self.options = [
            discord.SelectOption(label=option["label"], value=option["value"], description=option.get("description", ""))
            for option in options
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
        selected_label = next(opt.label for opt in self.options if opt.value == self.selected_value)  # Get label

        await interaction.response.edit_message(content=f"You selected: **{selected_label}**", view=None)  
        
        self.stop()

    async def wait_for_selection(self):
        """Waits for the user to select a value and returns it."""
        await self.wait()
        return self.selected_value

# Create session once and pass it to functions
async def create_session():
    return aiohttp.ClientSession()

async def filterACO(session, userID, fare_data, emailAcc, tip):
    print("Grabbing ACO Fare with embed data")
    subtotal = fare_data["subtotal"]
    delivery_fee = fare_data["delivery_fee"]
    taxes = fare_data["taxes"]
    total = fare_data["total"]
    total_after_tip = fare_data["total_after_tip"]
    cart_items = fare_data["cart_items"]
    address = fare_data["address"]
    promotion = fare_data["promotion"]
    canCheckOut = True

    # Validation logic from original filterACO
    if subtotal and delivery_fee and address:
        try:
            user_credits = float(await database.getBalance(str(userID)))
            deduction = 9 + tip + delivery_fee + taxes
            deduction = round(deduction, 2)
            remaining_credits = round(user_credits - deduction, 2)
            if remaining_credits < 0:
                print(f"{userID} does not have enough credits. ({remaining_credits})")
                canCheckOut = False
                embed = discord.Embed(
                    title="Not enough Credits!",
                    description=f"Not enough credits for this order, need a total of {deduction} credits",
                    color=discord.Color.red()
                )
                print("ACO Fare done.")
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
            # Construct the order breakdown embed
            embed = discord.Embed(
                title="🍽️ MaxGains Delivery Order Details",
                color=discord.Color.orange()
            )
            embed.add_field(name="MaxGains🆔", value=f"`{userID}`", inline=False)
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

            print("ACO Fare done")
            return embed, deduction, total_after_tip, canCheckOut
        except Exception as e:
            await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer in filterACO: {e}"})
            embed = discord.Embed(
                title="Please open a manual order ticket.",
                description="Error with generating order fare.",
                color=discord.Color.red()
            )
            print("Filter ACO done with error")
            return embed, 0, 0, False
    else:
        await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer: {fare_data}"})
        embed = discord.Embed(
            title="Please open a manual order ticket.",
            description="Error with generating order fare.",
            color=discord.Color.red()
        )
        print("Filter ACO done2")
        return embed, 0, 0, False
    
async def filterFare(interaction, session, userID, fare_data, emailAcc, tip):
    print("Grabbing Fare with embed data")
    # Ensure tip is a number, default to 0 if invalid
    try:
        tip = float(tip) if tip is not None else 0
    except (ValueError, TypeError) as e:
        print(f"FilterFare - Invalid tip value: {tip}, error: {e}, defaulting to 0")
        tip = 0

    # Extract fare_data with defaults to prevent KeyError
    subtotal = fare_data.get("subtotal", 0)
    delivery_fee = fare_data.get("delivery_fee", 0)
    taxes = fare_data.get("taxes", 0)
    total = fare_data.get("total", 0)
    total_after_tip = fare_data.get("total_after_tip", 0)
    cart_items = fare_data.get("cart_items", "No items")
    address = fare_data.get("address", "Unknown address")
    promotion = fare_data.get("promotion", 0)
    surcharge = 0
    canCheckOut = True

    print(f"FilterFare - Validation started: subtotal={subtotal}, delivery_fee={delivery_fee}, address={address}, tip={tip}")
    # Validation logic from original filterFare
    if subtotal and delivery_fee is not None and address:  # Allow delivery_fee to be 0
        try:
            print("FilterFare - Entering validation try block")
            ubercash = 0  # Assuming no Uber Cash in embed for now
            if subtotal < 20:
                embed = discord.Embed(
                    title="Error: Subtotal Too Low",
                    description="The subtotal is too low. Please make sure it is above $20.00.",
                    color=discord.Color.red()
                )
                print("FilterFare - Subtotal too low, returning error embed")
                await interaction.followup.send(embed=embed)
                print("Filter Fare done")
                return embed, 0, 0, False
            
            if subtotal > 30.00:
                embed = discord.Embed(
                    title="Error: Subtotal Too High",
                    description="The subtotal is too High. Please make sure it is under $30.00.",
                    color=discord.Color.red()
                )
                print("FilterFare - Subtotal too high, returning error embed")
                await interaction.followup.send(embed=embed)
                print("Filter Fare done")
                return embed, 0, 0, False

            if subtotal > 25:
                surcharge = subtotal - 25
            if delivery_fee + taxes > 9:
                surcharge = surcharge + ((delivery_fee + taxes) - 9)
            deduction = 9 + total_after_tip
            deduction = round(deduction, 2)
            print(f"FilterFare - Calculating credits: deduction={deduction}")
            user_credits = float(await database.getBalance(str(userID)))
            remaining_credits = round(user_credits - deduction, 2)
            if remaining_credits < 0:
                print(f"{userID} does not have enough credits. ({remaining_credits})")
                canCheckOut = False
                embed = discord.Embed(
                    title="Not enough Credits!",
                    description=f"Need a total of {deduction} credits.\nMissing {remaining_credits} credits.",
                    color=discord.Color.red()
                )
                print("FilterFare - Not enough credits, returning error embed")
                await interaction.followup.send(embed=embed)
                print("Filter Fare done, not enough creds")
                return embed, 0, 0, False

            #if (subtotal > 20 and not promotion > 20) and ubercash == 0:
                #embed = discord.Embed(
                    #title="Store not part of Selected $25",
                    #description=f"Problem with orderlink, seems that your store is not part of selected $25.\n{SELECTED_STORES}",
                    #color=discord.Color.red()
                #)
                #print("FilterFare - Store not part of selected $25, returning error embed")
                #await interaction.followup.send(embed=embed)
                #return embed, 0, 0, False

            print(f"FilterFare - Setting address: {address}")
            await database.setAddy(address)
            if await database.checkAddy():
                print(f"{userID} has addy ban")
                embed = discord.Embed(
                    title="Address Ban",
                    description="Your address has been banned by Uber, please wait 2 days before trying again. Or try placing at a nearby address.",
                    color=discord.Color.red()
                )
                print("FilterFare - Address ban detected, returning error embed")
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
            # Construct the order breakdown embed
            print("FilterFare - Constructing order breakdown embed")
            embed = discord.Embed(
                title="🍽️ MaxGains Order Details",
                color=discord.Color.orange()
            )
            embed.add_field(name="MaxGains", value=f"`{userID}`", inline=False)
            embed.add_field(name="🧾 UberEats Receipt", value="", inline=False)
            embed.add_field(name="Subtotal", value=f"${subtotal:.2f}", inline=True)
            embed.add_field(name="Delivery Fee", value=f"${delivery_fee:.2f}", inline=True)
            embed.add_field(name="Taxes & Fees", value=f"${taxes:.2f}", inline=True)
            embed.add_field(name="Tip", value=f"${tip:.2f}", inline=True)
            embed.add_field(name="💰 Total", value=f"**${og_total:.2f}**", inline=False)
            embed.add_field(name="🍔 Items Placed", value=cart_items or "No items", inline=False)
            embed.add_field(name="📍 Address", value=address, inline=True)
            embed.add_field(name="🎁 Credits Applied", value=credits_message, inline=False)

            print("FilterFare - Embed constructed successfully")
            print("Filter Fare done")
            return embed, deduction, total_after_tip, canCheckOut
        except Exception as e:
            print(f"FilterFare - Error processing fare: {e}")
            await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer in filterFare: {e}"})
            embed = discord.Embed(
                title="Please open a manual order ticket.",
                description=f"Error with generating order fare: {str(e)}",
                color=discord.Color.red()
            )
            print("Filter Fare done with error")
            await interaction.followup.send(embed=embed)
            return embed, 0, 0, False
    else:
        print(f"FilterFare - Validation failed: subtotal={subtotal}, delivery_fee={delivery_fee}, address={address}")
        await session.post(ERROR_WEBHOOK, data={"content": f"Error generating the fare for customer: {fare_data}"})
        embed = discord.Embed(
            title="Please open a manual order ticket.",
            description="Error with generating order fare.",
            color=discord.Color.red()
        )
        print("Filter Fare done2")
        await interaction.followup.send(embed=embed)
        return embed, 0, 0, False
    
async def successOrderMsg(interaction, order_details, moneySaved):
    print("successOrderMsg - Processing order_details:", order_details)
    
    # Validate order_details structure
    if not order_details:
        print("successOrderMsg - Invalid order_details: None or empty")
        await interaction.followup.send("Order Success, but failed to get final details due to invalid order data. Open ticket to get your order tracker.")
        return
    if not isinstance(order_details, list):
        print("successOrderMsg - Invalid order_details: not a list, type:", type(order_details))
        await interaction.followup.send("Order Success, but failed to get final details due to invalid order data. Open ticket to get your order tracker.")
        return
    if not order_details[0].get("fields"):
        print("successOrderMsg - No fields in order_details[0]:", order_details[0])
        await interaction.followup.send("Order Success, but failed to get final details due to missing fields. Open ticket to get your order tracker.")
        return

    embed = discord.Embed(
        title="🎉Successfully Placed Order!🎉",
        description="",
        color=order_details[0].get("color", discord.Color.orange().value),
    )

    try:
        # Extract store
        store = "Unknown Store"
        if len(order_details[0]["fields"]) > 0:
            store = order_details[0]["fields"][0].get("value", "Unknown Store")
        else:
            print("successOrderMsg - No fields available for store extraction, fields length:", len(order_details[0]["fields"]))
        embed.description = f"**Store:** {store}\n"
        print("successOrderMsg - Store extracted:", store)

        # Extract items ordered
        items = "No items found"
        if len(order_details[0]["fields"]) > 2:
            items = order_details[0]["fields"][2].get("value", "No items found")
        else:
            print("successOrderMsg - Not enough fields for items, fields length:", len(order_details[0]["fields"]))
        embed.add_field(name="Items Ordered:", value=items, inline=False)
        print("successOrderMsg - Items extracted:", items)

        # Add saved amount
        embed.add_field(name="You Saved:", value=f'${moneySaved:.2f}', inline=True)
        print("successOrderMsg - Money saved added:", f'${moneySaved:.2f}')

        # Extract order link
        order_link = order_details[0].get("url", "No link available")
        if len(order_details[0]["fields"]) > 4:
            order_link = order_details[0]["fields"][3].get("value", order_link)
        else:
            print("successOrderMsg - Not enough fields for order link, fields length:", len(order_details[0]["fields"]))
        embed.add_field(name="Order Link:", value=order_link, inline=True)
        print("successOrderMsg - Order link extracted:", order_link)

        # Extract delivery address
        address = "Unknown address"
        if len(order_details[0]["fields"]) > 12:
            address = order_details[0]["fields"][11].get("value", "Unknown address")
        else:
            print("successOrderMsg - Not enough fields for address, fields length:", len(order_details[0]["fields"]))
        embed.add_field(name="Delivery Address:", value=address, inline=False)
        print("successOrderMsg - Address extracted:", address)

        # Add user ID
        embed.add_field(name="MaxGains UUID:", value=str(interaction.user.id), inline=True)
        print("successOrderMsg - UUID added:", str(interaction.user.id))

        # Log the final embed before sending
        print("successOrderMsg - Final embed to send:", embed.to_dict())

        # Check interaction state and attempt to send
        print("successOrderMsg - Interaction state:", interaction)
        try:
            await interaction.followup.send(embed=embed)
            print("successOrderMsg - Embed sent successfully")
        except Exception as send_error:
            print("successOrderMsg - Failed to send embed, error:", send_error)
            raise send_error  # Re-raise to catch in outer try-except

        await asyncio.sleep(0.5)
        try:
            print("Sent Order Tracker and Success MSG")
        except Exception as follow_error:
            print("successOrderMsg - Failed to send follow-up message, error:", follow_error)
            raise follow_error

    except IndexError as e:
        print(f"successOrderMsg - IndexError during embed construction: {e}, order_details[0]['fields'] length: {len(order_details[0].get('fields', []))}")
        await interaction.followup.send("Order Success, but failed to get final details due to index error. Open ticket to get your order tracker.")
    except KeyError as e:
        print(f"successOrderMsg - KeyError during embed construction: {e}, order_details[0]: {order_details[0]}")
        await interaction.followup.send("Order Success, but failed to get final details due to missing key. Open ticket to get your order tracker.")
    except discord.errors.HTTPException as e:
        print(f"successOrderMsg - Discord HTTPException during sending: {e}, status: {e.status}, code: {e.code}, text: {e.text}")
        await interaction.followup.send("Order Success, but failed to send details due to Discord API error. Open ticket to get your order tracker.")
    except Exception as e:
        print(f"successOrderMsg - General Error: {e}")
        await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
        
def OTPInteraction(email):
    return {
        "type": 2,
        "application_id": "1386839434531438652",  # your bot's app ID
        "channel_id": "1406550397199319162",      # Woolix channel ID
        "session_id": "66ee3d4285916d7ed81f9286a6a062bc",  # optional, can be left out
        "data": {
            "version": "1420614686013001771",     # ✅ updated
            "id": "1386840161907642439",         # ✅ updated
            "name": "otp",
            "type": 1,
            "options": [
                {
                    "type": 3,
                    "name": "email",
                    "value": email
                }
            ],
            "application_command": {
                "id": "1386840161907642439",         # ✅ updated
                "type": 1,
                "application_id": "1386839434531438652",  # ✅ same as above
                "version": "1420614686013001771",     # ✅ updated
                "name": "otp",
                "description": "Get OTP code for an email address",
                "options": [
                    {
                        "type": 3,
                        "name": "email",
                        "description": "The email to get OTP for",
                        "required": True,
                        "description_localized": "The email to get OTP for",
                        "name_localized": "email"
                    }
                ],
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




def OTPInteraction2(email):
    return

async def ERRORMESSAGEHOOK(session, name, msg1, msg2):
    await session.post(ERROR_WEBHOOK, data={"content": f"Error occured at {name} func:\n{msg1}\n{msg2}"})
    return

async def returnMessage(msg, session):
    data = {
        "content": f'{msg}',
        "tts": False,
    }
    async with session.post(WOOLIX_CHANNEL, data=data, headers=headers) as response:
        return response

async def getOrderInfoMSG(session): # STEP 1 !ACO -> GET ORDER INFO MSG
    err_count = 0
    while True:
        async with session.get(f'{WOOLIX_CHANNEL}?limit=2', headers=headers) as response:
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
                    print("Exception error occur 3 times at getOrderInfoMSG func")
                    await session.post(ERROR_WEBHOOK, data={"content": "Exception error occur 3 times at getOrderInfoMSG func"})
                    return False
                err_count += 1
        await asyncio.sleep(2)
        

async def getOTPMSG(session):
    otpTries = 0
    while otpTries < 7:
        try:
            # Search for the provide OTP message
            async with session.get(f'{WOOLIX_CHANNEL}?limit=1', headers=headers) as response:
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

async def OTP(interaction, session, emailAcc):  # STEP 2 OTP CODE -> UBER FARE BREAKDOWN
    print("Getting OTP")
    changeEmail = emailAcc.split("@")
    prefix = changeEmail[0]
    suffix = changeEmail[1]
    newEmail = prefix + "@" + "outlook"
    otpTries = 0
    retryFlag = True
    if await getOTPMSG(session):
        print("Got the message for OTP")
        otpMSG = await interaction.followup.send("Inputting Cart Items.")
        # if suffix != "outlook":
        #    print(f"used glze for otp for {interaction.user.name}")
        await asyncio.sleep(3)
        response = await session.post(INTERACTION_API, json=OTPInteraction(emailAcc), headers=headers)
        print("POST status:", response.status)
        print("POST reply:", await response.text())
        # else:
        #    otpCode = await imap.main(emailAcc)
        #    await returnMessage(str(otpCode), session)
        #    if otpCode == None:
        #        await database.setDeadStatus(emailAcc)
        #        return False
        err_count = 0
        await asyncio.sleep(5)

        while True:
            try:
                async with session.get(f'{WOOLIX_CHANNEL}?limit=4', headers=headers) as response:
                    json_data = await response.json()
                    # print("OTP - Full API Response:", json_data)  # Log every message
                    for message in json_data:
                        print("OTP - Message Content:", message.get("content", "No content"), "Embeds:", message.get("embeds", "No embeds"))

                    if json_data[0]["content"] == "Please enter the new email address:":
                        if newEmail == emailAcc:
                            await returnMessage(newEmail, session)
                            await otpMSG.edit(content="Obtaining fare breakdown from Uber.")
                            await asyncio.sleep(1)
                            return True  
                        await asyncio.sleep(1)
                        await returnMessage(newEmail, session)
                        await asyncio.sleep(3)
                        code = await imap.main(newEmail)
                        if code == None:
                            await database.setDeadStatus(emailAcc)
                            return False
                        await returnMessage(str(code), session)
                        await database.updateEmail(emailAcc, newEmail)
                        await otpMSG.edit(content="Obtaining fare breakdown from Uber.")
                        await asyncio.sleep(1)
                        return True   

                    elif json_data[0]["content"] == "Would you like to change your email address? (yes/no)":
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
                        otpTries += 1  # Always increment every time this shows up

                        if otpTries >= 10:  # <--- SET to 10 or whatever you want
                            await otpMSG.edit(content="Cart failed, please retry")
                            print("Timed out")
                            await database.setDeadStatus(emailAcc)
                            return False

                        if len(json_data) > 1 and json_data[1]["content"] == "Email OTP code incorrect, trying again...":
                            await otpMSG.edit(content="Retrying to grab cart...")
                            if retryFlag:
                                await session.post(INTERACTION_API, json=OTPInteraction(emailAcc), headers=headers)
                                retryFlag = False

                    elif json_data[0]["content"] == ERROR_MESSAGE:
                        await otpMSG.edit(content="Error message occurred at Cart. Please try placing again.")
                        await ERRORMESSAGEHOOK(session, "OTP", json_data[1]["content"], json_data[0]["content"])
                        return False

                    elif json_data[0]["content"] == CART_LOCK:
                        await otpMSG.edit(content="Error message occurred at Cart. Your cart is locked, please unlock.")
                        await ERRORMESSAGEHOOK(session, "OTP", json_data[1]["content"], json_data[0]["content"])
                        return False

                    elif json_data[0]["content"] == "CardNum verified":
                        pass

            except Exception as e:
                print(f"OTP - Error fetching messages: {e}")
                if err_count >= 3:
                    print("Exception error occurred 3 times at OTP func")
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
            print(f"GetFare - Attempt {attempt + 1} starting, session status: {session.closed}")
            async with session.get(f'{WOOLIX_CHANNEL}?limit=10', headers=headers) as response:
                #print(f"GetFare - HTTP Response Status: {response.status}")
                response_json = await response.json()
                #print(f"GetFare - Full API Response (Attempt {attempt + 1}): {response_json}") too much clutter
                for msg_idx, message in enumerate(response_json):
                    print(f"GetFare - Message {msg_idx} Details: Content: {message.get('content', 'No content')}, Embeds: {message.get('embeds', 'No embeds')}")
                    if "embeds" in message and message["embeds"]:
                        for embed_idx, embed in enumerate(message["embeds"]):
                            print(f"GetFare - Embed {embed_idx} Details: Title: {embed.get('title', 'No title')}, Fields: {embed.get('fields', 'No fields')}")
                            if "Checkout Information" in embed.get("title", ""):
                                print("GetFare - Target Embed 'Checkout Information' Found")
                                fields = embed.get("fields", [])
                                print(f"GetFare - Extracted Fields: {fields}")
                                
                                # Extract from fields if available, otherwise use defaults
                                fare_breakdown = next((f["value"] for f in fields if "Order Details" in f["name"]), "")
                                tip_value = next((f["value"] for f in fields if "Tip" in f["name"]), "**$0**")
                                order_total = next((f["value"] for f in fields if "Order Total" in f["name"]), "**$0**")

                                # Parse fare_breakdown for cart_items and address
                                fare_lines = fare_breakdown.split("\n") if fare_breakdown else []
                                print(f"GetFare - Fare Breakdown Lines: {fare_lines}")
                                
                                # Initialize defaults
                                cart_items = "Items could not be found."
                                address = "Unknown address"
                                subtotal = 0
                                promotion = 0
                                delivery_fee = 0
                                taxes = 0
                                total = 0

                                # Parse cart items and address from fare_breakdown
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
                                        # Next line should be the address
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

                                # Clean tip and order total
                                tip_amount = float(tip_value.replace("**$", "").replace("**", "") if tip_value else 0)
                                total_after_tip = float(order_total.replace("**$", "").replace("**", "") if order_total else 0)
                                print(f"GetFare - Calculated Values: subtotal={subtotal}, promotion={promotion}, delivery_fee={delivery_fee}, taxes={taxes}, total={total}, tip_amount={tip_amount}, total_after_tip={total_after_tip}")

                                # Prepare fare data
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
                                print(f"GetFare - Prepared Fare Data: {fare_data}")

                                print("GetFare - Exiting after processing embed")
                                return True, fare_data, message_id, True
        except Exception as e:
            print(f"GetFare - Error fetching messages: {e}")
            if err_count >= 3:
                print("GetFare - Exception error occurred 3 times")
                await session.post(ERROR_WEBHOOK, data={"content": f"Exception error occurred 3 times in GetFare function: {e}"})
                return False, 0, 0, True
            err_count += 1
        attempt += 1
        print(f"GetFare - Sleeping for 5 seconds before next attempt, attempt {attempt}")
        await asyncio.sleep(5)
    print("GetFare - Max attempts reached, exiting")
    return False, 0, 0, False

async def reCheckOut(session, interaction, emailAcc, aco, tip):
    await asyncio.sleep(5)
    err_count = 0
    while True:
        try:
            async with session.get(f'{WOOLIX_CHANNEL}?limit=4', headers=headers) as response:
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
                print("Exception error occur 3 times at reCheckOut func")
                await session.post(ERROR_WEBHOOK, data={"content": "Exception error occur 3 times at reCheckout func"})
                return False, 0, 0, 1, True
            err_count += 1
        await asyncio.sleep(3)

async def CHECK3DS(bot, session, interaction):
    print("in 3ds")
    await asyncio.sleep(1)
    interaction.followup.send("Please provide verification amounts separated by comma (e.g. 85,44)")
    def check_message(msg):
        return msg.author == interaction.user and msg.channel == interaction.channel
    response = await bot.wait_for("message", timeout=60, check=check_message)
    returnMessage(response.content, session)
    await asyncio.sleep(3)
    while True:
        try:
            async with session.get(f'{WOOLIX_CHANNEL}?limit=1', headers=headers) as response:
                json_data = await response.json()
                if json_data[0]["content"] == "3DS challenge processed successfully. Checking out again...":
                    pass
                elif json_data[0]["content"] == "Successfully checked out the order!":
                    pass
                elif json_data[0]["content"] == "":
                    return True
                else:
                    return False
        except Exception as e:
            print(f"Error: {e}")
        print("Waiting on 3DS...")
        await asyncio.sleep(3)

async def FINAL_CHECK(bot, session, interaction, moneySaved, cost, orderLink, emailAcc, aco):
    print("Entering Final Checkout")
    await asyncio.sleep(10)  # Initial delay to allow Woolix to process
    max_poll_attempts = 20  # Poll for up to 10 minutes (120 * 5s = 600s)
    attempt = 0
    
    while attempt < max_poll_attempts:
        try:
            async with session.get(f'{WOOLIX_CHANNEL}?limit=10', headers=headers) as response:  # Increased limit to 20
                json_data = await response.json()
                print("FINAL_CHECK - Fetched messages:", json_data)  # Debug: Log all fetched messages
                
                # Check for success embed first
                success_embed_found = False
                success_message = None
                for msg in reversed(json_data):  # Iterate from oldest to newest
                    if msg.get("embeds") and msg["embeds"]:
                        embed = msg["embeds"][0]
                        if "Order Successfully Placed" in embed.get("title", "") or any("Order Link" in field.get("name", "") for field in embed.get("fields", [])):
                            success_embed_found = True
                            success_message = msg
                            break
                        elif embed.get("title") == "❌ Checkout Failed" or "Timed out waiting for response" in msg.get("content", ""):
                            print("FINAL_CHECK - Checkout failed detected in embed")
                            if not aco:
                                if "Promotion codes have been deemed invalid for this account and all trips will be ordered at the full price." in embed.get("description", ""):
                                    await database.incrementAddy()
                                if "Store is not available at the moment" in embed.get("description", ""):
                                    await interaction.followup.send("Store closed, please select another store.")
                                else:
                                    await database.setDeadStatus(emailAcc)
                                    await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                            await ERRORMESSAGEHOOK(session, "FINAL_CHECK", msg["content"], str(msg.get("embeds", [])))
                            return
                
                if success_embed_found:
                    await asyncio.sleep(5)  # Wait for the confirmation message
                    async with session.get(f'{WOOLIX_CHANNEL}?limit=10', headers=headers) as response:
                        json_data = await response.json()
                        print("FINAL_CHECK - Fetched messages after success embed:", json_data)
                        
                        # Check all messages for confirmation
                        confirmation_found = False
                        for msg in reversed(json_data):  # Iterate from oldest to newest
                            if msg.get("content") == "More actions after checkout?":
                                confirmation_found = True
                                print("FINAL_CHECK - Confirmed success with 'More actions after checkout?'")
                                break
                            elif msg.get("content") == "Uber One cancelled after two sucessful orders":
                                confirmation_found = True
                                print("FINAL_CHECK - Confirmed success with 'More actions after checkout?'")
                                break
                        
                        if confirmation_found:
                            embed_to_send = [msg["embeds"][0] for msg in json_data if msg.get("embeds") and msg["id"] == success_message["id"]]
                            print("FINAL_CHECK - Embed to send to successOrderMsg:", embed_to_send)
                            if embed_to_send:
                                try:
                                    await successOrderMsg(interaction, embed_to_send, moneySaved)
                                except Exception as e:
                                    print(f"FINAL_CHECK - Error in successOrderMsg: {e}")
                                    await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
                            else:
                                await interaction.followup.send("Order Success, but failed to get final details. Open ticket to get your order tracker.")
                            if not aco:
                                await database.updateInfo(emailAcc)
                            try:
                                await database.updateBalance(interaction.user.id, -moneySaved, cost, orderLink)
                            except Exception as e:
                                print(f"FINAL_CHECK - Error updating balance: {e}")
                            print(f"Order has been placed for {interaction.user.id}")
                            await database.resetAddy()
                            await bot.get_channel(1420771626223534090).send(f"<@{interaction.user.id}> has placed a successful UE order for ${moneySaved}!")
                            #if aco:
                                #await bot.get_channel(1420771626223534090).send(f"{interaction.user.name} ({interaction.user.id}): ACO Success of ${moneySaved} for cost of ${cost}")
                            #else:
                                #await bot.get_channel(1371288622413905920).send(f"{interaction.user.id}: UEACO Success of ${moneySaved} for cost of ${cost}")
                            return
                        else:
                            print("FINAL_CHECK - No 'More actions after checkout?' found, waiting...")
                
                elif json_data[0]["content"] == "Successfully checked out the order!":
                    print("FINAL_CHECK - Detected successful checkout via content")
                    # Look for the embed with order details
                    for msg in json_data:
                        if msg.get("embeds") and msg["embeds"]:
                            print("FINAL_CHECK - Success embed message (via content):", msg)
                            try:
                                await successOrderMsg(interaction, msg["embeds"], moneySaved)
                            except Exception as e:
                                print(f"FINAL_CHECK - Error in successOrderMsg: {e}")
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
                    print(f"Order has been placed for {interaction.user.id}")
                    await database.resetAddy()
                    await bot.get_channel(1420771626223534090).send(f"<@{interaction.user.id}> has placed a successful UE order for ${moneySaved}!")
                    #if aco:
                        #await bot.get_channel(1371288622413905920).send(f"{interaction.user.name} ({interaction.user.id}): ACO Success of ${moneySaved} for cost of ${cost}")
                    #else:
                        #await bot.get_channel(1371288622413905920).send(f"{interaction.user.id}: UEACO Success of ${moneySaved} for cost of ${cost}")
                    return
                elif json_data[0]["content"] == "Would you like to cancel UE One?":
                    print("FINAL_CHECK - Detected 'Would you like to cancel UE One?' message")
                    index = 1
                    if len(json_data) > 1 and json_data[1]["content"] == "Would you like to cancel UE One?":
                        index = 2
                    if index < len(json_data) and json_data[index].get("embeds") and json_data[index]["embeds"][0].get("title") == "❌ Checkout Failed":
                        print("FINAL_CHECK - Checkout failed detected in cancel prompt")
                        if not aco:
                            if "Promotion codes have been deemed invalid for this account and all trips will be ordered at the full price." in json_data[index]["embeds"][0].get("description", ""):
                                await database.incrementAddy()
                            await database.setDeadStatus(emailAcc)
                        await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                        await ERRORMESSAGEHOOK(session, "FINAL_CHECK", json_data[1]["content"], str(json_data[index].get("embeds", [])))
                        return
                elif json_data[0].get("embeds"):
                    print("FINAL_CHECK - Checking embeds for failure")
                    if json_data[0]["embeds"][0].get("title") == "❌ Checkout Failed":
                        print("FINAL_CHECK - Checkout failed detected in embed")
                        if not aco:
                            if "Promotion codes have been deemed invalid for this account and all trips will be ordered at the full price." in json_data[0]["embeds"][0].get("description", ""):
                                await database.incrementAddy()
                            if "Store is not available at the moment" in json_data[0]["embeds"][0].get("description", ""):
                                await interaction.followup.send("Store closed, please select another store.")
                            else:
                                await database.setDeadStatus(emailAcc)
                                await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                        await ERRORMESSAGEHOOK(session, "FINAL_CHECK", json_data[0]["content"], str(json_data[0].get("embeds", [])))
                        return
                elif json_data[0]["content"] == ERROR_MESSAGE:
                    print("FINAL_CHECK - Detected ERROR_MESSAGE")
                    if not aco:
                        await database.setDeadStatus(emailAcc)
                        await interaction.followup.send("Checkout could not be completed at this time. Please try again.")
                        await ERRORMESSAGEHOOK(session, "FINAL_CHECK", json_data[1]["content"], "Error occurred at checkout, daisy/payment issue.")
                    return
                # If we reach here without returning, wait for the next message
        except Exception as e:
            print(f"FINAL_CHECK - Error: {e}")
        
        attempt += 1
        print(f"FINAL_CHECK - Waiting on Checkout... Attempt {attempt}/{max_poll_attempts}")
        await asyncio.sleep(5)
    
    print("FINAL_CHECK - No success detected after max attempts")
    await interaction.followup.send("Order status unclear. Please check UberEats for confirmation and contact support if needed.")
    await session.post(ERROR_WEBHOOK, data={"content": f"Order for {interaction.user.id} timed out but may have succeeded. OrderLink: {orderLink}"})

async def CHECKFORPROMO(messages, emailAcc, type, aco):
    print("Checking Promos")
    if aco:
        return True
    promos = []
    for i in range(len(messages)-1, -1, -1):
        promo_match = re.search(r'Claimed savings:\s*(.*)', messages[i]["content"])
        if promo_match:
            result = promo_match.group(1)
            promos.append(result)
        else:
            pass
    if len(promos) > 0:
        if promos[0] == "$30 off":
            await database.updateType(emailAcc, "30")
            return True
        elif promos[0] == "$25 off":
            await database.updateType(emailAcc, "s25")
            return True
        elif promos[0] == "$25 off (selected stores)":
            await database.updateType(emailAcc, "s25")
            if type == "s25" or type == "s20":
                return True
            else:
                return False
        elif promos[0] == "$20 off":
            await database.updateType(emailAcc, "s25")
            return True
        elif promos[0] == "$20 off (selected stores)":
            await database.updateType(emailAcc, "s25")
            return True
        else:
            print("Couldnt get the account type")
            return False
    elif len(promos) == 0:
        await database.setDeadStatus(emailAcc)
        return False


async def CHECKOUT(session, interaction, emailAcc, aco, type):
    print("CHECKOUT - Starting process, emailAcc:", emailAcc)
    err_count = 0
    while True:
        try:
            async with session.get(f'{WOOLIX_CHANNEL}?limit=6', headers=headers) as response:
                json_data = await response.json()
                #print("CHECKOUT - Full API Response:", json_data) Too much clutter, dont need
                for msg_idx, message in enumerate(json_data):
                    print(f"CHECKOUT - Message {msg_idx} Content:", message.get("content", "No content"), "Embeds:", message.get("embeds", "No embeds"))
                    if "embeds" in message and message["embeds"]:
                        for embed in message["embeds"]:
                            if "Checkout Information" in embed.get("title", ""):
                                print("CHECKOUT - Found 'Checkout Information' embed")
                                #if await CHECKFORPROMO(json_data, emailAcc, type, aco):
                                    #pass
                                #else:
                                    #return False, 0, 0, 1, True
                                print("CHECKOUT - Calling GetFare immediately")
                                result = await GetFare(session, interaction, json_data[0]["id"], emailAcc, aco, 0)
                                print("CHECKOUT - Returned from GetFare:", result)
                                return result  # Exit after calling GetFare
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
                print("CHECKOUT - Session closed, attempting to recreate session")
                session = await create_session()
            if err_count >= 3:
                print("Exception error occurred 3 times at CHECKOUT func")
                await session.post(ERROR_WEBHOOK, data={"content": "Exception error occurred 3 times at CHECKOUT func"})
                return False, 0, 0, 1, True
            err_count += 1
        await asyncio.sleep(3)
        
async def changeAddy2(session, interaction, user_input):
    """Processes the second address input."""
    print(f"[changeAddy2] Updating address 2 to: {user_input}")
    await asyncio.sleep(2)
    try:
        await returnMessage(user_input, session)
        await interaction.followup.send(f"Address 2 updated to: {user_input}")
    except Exception as e:
        print(f"[changeAddy2] Error: {e}")
        await interaction.followup.send("An error occurred while updating the address. Please try again.")


async def changeTip(session, interaction, user_input):
    """Processes the tip amount input."""
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
    """Processes the name input."""
    print(f"[changeName] Updating name to: {user_input}")
    await asyncio.sleep(2)
    try:
        if "," not in user_input:
            name = user_input.split(" ")
            try:
                user_input = name[0]+","+name[1]
            except:
                user_input = name[0]+","+"R"
        await returnMessage(user_input, session)
        await interaction.followup.send(f"Name updated to: {user_input}")
    except Exception as e:
        print(f"[changeName] Error: {e}")
        await interaction.followup.send("An error occurred while updating the Name. Please try again.")
    
def scheduleInteraction(message_id, selection):
    return {
  "type": 3,
  "nonce": "",
  "guild_id": None,
  "channel_id": "1406550397199319162",
  "message_flags": 0,
  "message_id": message_id,
  "application_id": "1313217756769943653",
  "session_id": "ccdc15a7a461176140ee68ea468b52c3",
  "data": {
    "component_type": 3,
    "custom_id": "time_window_select",
    "type": 3,
    "values": [f"{selection}"]
  }
}

def interactionPayload(message_id, custom_id):
    return {
                "type": 3,  # Message component interaction
                "nonce": "",  # Ensure nonce is empty as per your suggestion
                "guild_id": None,
                "channel_id": "1406550397199319162",
                "message_flags": 0,
                "message_id": message_id,
                "application_id": "1363880287276236821",
                "session_id": "070f7136d42d6e4703f1e12a7c99b746",
                "data": {
                    "component_type": 2,  # Button component
                    "custom_id": custom_id
                }
            }
async def handleReactions(session, bot, interaction, message_id, moneySaved, cost, orderLink, emailAcc, aco):
    print("handleReactions - START: Waiting on user input, initial message_id:", message_id)
    
    while True:  # Loop until checkout or cancel
        # Fetch the latest message to get reaction options
        print("handleReactions - Fetching latest message(s) from WOOLIX_CHANNEL")
        components = []
        attempts = 0
        max_attempts = 5  # Try for up to 10 seconds for most actions
        while not components and attempts < max_attempts:
            async with session.get(f'{WOOLIX_CHANNEL}?limit=2', headers=headers) as response:
                messages = await response.json()
                #print("handleReactions - Fetched messages:", messages)
                for msg in messages:
                    if msg.get("components"):
                        latest_message_json = [msg]
                        components = msg.get("components", [])
                        break
                if not components:
                    print("handleReactions - No components found in messages, waiting 2 seconds before retrying...")
                    attempts += 1
                    await asyncio.sleep(2)

        if not components:
            print("handleReactions - No components found after max attempts, using default reactions")
            reactions = {
                "🚀": "checkout",
                "🏬": "update_address",
                "👤": "change_name",
                "🎯": "joggle_addy",
                "📅": "schedule",
                "❌": "cancel"
            }
            reaction_to_custom_id = {
                "🚀": "proceed_checkout",
                "🏬": "update_address",
                "👤": "change_name",
                "🎯": "address_joggling",
                "📅": "schedule_order",
                "❌": "cancel"
            }
            latest_message_json = messages[:1]
        else:
            print("handleReactions - Components found in message:", latest_message_json)

        latest_content = latest_message_json[0].get("content", "")
        message_id = latest_message_json[0].get("id")

        # Dynamically build reaction options with custom_id mapping
        print("handleReactions - Building reaction options from content or components")
        reactions = {}
        reaction_to_custom_id = {}
        if UBER_REACTIONS in latest_content or UBER_REACTIONS_2 in latest_content:
            print("here")
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
            # Define the allowed custom_ids we want to show
            allowed_custom_id_patterns = {
                "to_checkout_steps_": "proceed_checkout",    # Match to_checkout_steps_ followed by any number
                "update_address": "update_address",
                "change_name": "change_name",
               #"address_joggling_": "address_joggling",
                "delivery_notes": "delivery_notes",
                "cancel": "cancel"
            }
            emoji_mapping = {
                "proceed_checkout": "🚀",
                "update_address": "🏬",
                "change_name": "👤",
                #"address_joggling": "🎯",
                "delivery_notes": "📅",
                "cancel": "❌"
            }
            action_mapping = {
                "proceed_checkout": "checkout",
                "update_address": "update_address",
                "change_name": "change_name",
                #"address_joggling": "joggle_addy",
                "delivery_notes": "delivery_notes",
                "cancel": "cancel"
            }
            for component_group in components:
                for component in component_group.get("components", []):
                    custom_id = component.get("custom_id")
                    print(f"handleReactions - Processing component: custom_id={custom_id}")  # Debug: Log each custom_id
                    # Only include reactions for allowed custom_ids
                    for pattern, pAction in allowed_custom_id_patterns.items():
                        if pattern in custom_id:
                            emoji = emoji_mapping.get(pAction)
                            action = action_mapping.get(pAction, "unknown")
                            if emoji:
                                reactions[emoji] = action
                                reaction_to_custom_id[emoji] = custom_id
                            else:
                                print(f"handleReactions - No emoji mapped for allowed custom_id={custom_id}, skipping")
                        else:
                            print(f"handleReactions - Skipping unallowed custom_id={custom_id}")

        print("handleReactions - Dynamic reactions set:", reactions)
        print("handleReactions - Reaction to custom_id mapping:", reaction_to_custom_id)

        # Send new reaction message each iteration
        print("handleReactions - Sending new reaction message")
        reaction_message = await interaction.followup.send("React with one of the following:\n" + "\n".join([f"{k} {v}" for k, v in reactions.items()]))
        print("handleReactions - Reaction message sent, msg.id:", reaction_message.id)
        for reaction in reactions.keys():
            try:
                await reaction_message.add_reaction(reaction)
                print(f"handleReactions - Successfully added reaction: {reaction}")
            except discord.errors.HTTPException as e:
                print(f"handleReactions - Failed to add reaction {reaction}: {e}")

        def check_reaction(reaction, user):
            is_valid = str(reaction.emoji) in reactions and user.id == interaction.user.id and reaction.message.id == reaction_message.id
            print(f"check_reaction - Checking reaction: emoji={reaction.emoji}, user={user.id}, reaction.message.id={reaction.message.id}, msg.id={reaction_message.id}, is_valid={is_valid}")
            return is_valid

        try:
            print("handleReactions - Waiting for reaction, timeout set to 60 seconds")
            reaction, user = await bot.wait_for("reaction_add", timeout=60, check=check_reaction)
            print("handleReactions - Reaction received: emoji=", reaction.emoji, "user=", user.id, "action=", reactions[str(reaction.emoji)])
            action = reactions[str(reaction.emoji)]
            custom_id = reaction_to_custom_id[str(reaction.emoji)]

            # Send button interaction to Woolix
            print(f"handleReactions - Sending button interaction to Woolix: custom_id={custom_id}, message_id={message_id}")
            async with session.post(INTERACTION_API, json=interactionPayload(message_id, custom_id), headers=headers) as response:
                print(f"handleReactions - Button interaction sent, response status: {response.status}")
                #print(f"handleReactions - Button interaction payload: {interaction_payload}")
                if response.status != 204:
                    print(f"handleReactions - Button interaction failed: {await response.text()}")

            # Wait for Woolix's response before proceeding with input-based actions
            if action in ["update_address", "change_tip", "change_name", "delivery_notes"]:
                print(f"handleReactions - Waiting for Woolix response after {action} button press")
                await asyncio.sleep(2)
                components_found = False
                attempts = 0
                max_attempts = 5
                while not components_found and attempts < max_attempts:
                    async with session.get(f'{WOOLIX_CHANNEL}?limit=1', headers=headers) as response:
                        latest_response = await response.json()
                        print("handleReactions - Woolix response after button press:", latest_response)
                        if latest_response[0].get("content") or latest_response[0].get("embeds"):
                            components_found = True
                            break
                    print("handleReactions - No prompt yet, waiting 2 seconds before retrying...")
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
                    print(f"handleReactions - Prompt sent for {action}")
                    def check_message(msg):
                        return msg.author == interaction.user and msg.channel == interaction.channel
                    try:
                        response = await bot.wait_for("message", timeout=60, check=check_message)
                        user_input = response.content
                        print(f"handleReactions - User input received for {action}: {user_input}")
                        print(f"handleReactions - Sending user input to Woolix: {user_input}")
                        await returnMessage(user_input, session)
                        if action == "change_tip":
                            try:
                                tip = float(user_input)
                                print("handleReactions - New tip value:", tip)
                                return tip
                            except ValueError as e:
                                print(f"handleReactions - Invalid tip value: {user_input}, error: {e}")
                                await interaction.followup.send("Invalid tip value. Please try again.")
                                continue
                        continue
                    except asyncio.TimeoutError:
                        print("handleReactions - Timeout waiting for user input")
                        await interaction.followup.send("You took too long to respond. Please try again.")
                        continue
                else:
                    print("handleReactions - No Woolix response received after button press")
                    continue
            elif action == "checkout":
                await interaction.followup.send("Checking out...")
                print("handleReactions - Checkout action triggered")
                # Fetch the latest message to get reaction options
                print("handleReactions - Fetching latest message(s) from WOOLIX_CHANNEL")
                #components = []
                #attempts = 0
                #max_attempts = 5  # Try for up to 10 seconds for most actions
               # while not components and attempts < max_attempts:
                    #async with session.get(f'{WOOLIX_CHANNEL}?limit=1', headers=headers) as response:
                        #messages = await response.json()
                        #lastMsg = messages[0]["embeds"][0]["title"]
                        #print("handleReactions - Fetched messages:", messages)
                        #if "Checkout Options" in lastMsg:
                           # custom_id = messages[0]["components"][0]["components"][0]["custom_id"]
                           # message_id = messages[0]["id"]
                            #break
                #print(message_id, custom_id)
                # DO EPH HERE
                if "to_checkout_steps_" in custom_id:
                    asyncio.create_task(bypass(1406550397199319162, 10))
                    await asyncio.sleep(5)
                async with session.post(INTERACTION_API, json=interactionPayload(message_id, custom_id), headers=headers) as response:
                    print(f"handleReactions - Button interaction sent, response status: {response.status}")
                await asyncio.sleep(2)
                await FINAL_CHECK(bot, session, interaction, moneySaved, cost, orderLink, emailAcc, aco)
                print("handleReactions - FINAL_CHECK completed")
                return -2
            elif action == "joggle_addy":
                print("handleReactions - Joggling addy")
                await interaction.followup.send("Activated Address Joggling.")
                print(custom_id, message_id)
                async with session.post(INTERACTION_API, json=interactionPayload(message_id, custom_id), headers=headers) as response:
                    print(f"handleReactions - Button interaction sent, response status: {response.status}")
                
                continue
            elif action == "cancel":
                print("handleReactions - Order Cancelled!")
                await interaction.followup.send("Order Cancelled...")
                return -3
        except asyncio.TimeoutError:
            print("handleReactions - TIMEOUT: Timed out waiting for reaction")
            await interaction.followup.send("Timed out. Order Cancelled.")
            return -3
        except Exception as e:
            print("handleReactions - ERROR: Unexpected error:", e)
            return -3
                   
async def handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, firstTime, tip):
    print("handleLoop - Starting process, emailAcc:", emailAcc)
    print(f"handleLoop - Parameters: aco={aco}, tip={tip}")
    if firstTime:
        result, fare_data, message_id, canCheckOut = await CHECKOUT(session, interaction, emailAcc, aco, type)
    else:
        result, fare_data, message_id, canCheckOut = await reCheckOut(session, interaction, emailAcc, aco, tip)
    print("handleLoop - Got from CHECKOUT/RECHECKOUT: result=", result, "fare_data=", fare_data, "message_id=", message_id, "canCheckOut=", canCheckOut)
    
    if result and canCheckOut:
        # Call the appropriate filter function based on aco
        print("handleLoop - Calling filter function, aco=", aco)
        if aco:
            embed, moneySaved, cost, canCheckOut = await filterACO(session, interaction.user.id, fare_data, emailAcc, tip)
        else:
            embed, moneySaved, cost, canCheckOut = await filterFare(interaction, session, interaction.user.id, fare_data, emailAcc, tip)
        
        if not canCheckOut:
            print("handleLoop - Checkout not possible, sending error embed")
            await interaction.followup.send(embed=embed)
            return False

        # Send the order breakdown embed and wait for the next message
        print("handleLoop - Sending order breakdown embed")
        await interaction.followup.send(embed=embed)
        await asyncio.sleep(1)  # Give time for Woolix to respond with the next message

        # Proceed to handleReactions
        print("handleLoop - Proceeding to handleReactions")
        state = await handleReactions(session, bot, interaction, message_id, moneySaved, cost, orderLink, emailAcc, aco)
        print("handleLoop - Got from handleReactions: state=", state)
        if state == -2:
            return True
        elif state == -1:
            return await handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, False, tip)
        elif state == -3:
            return False
        else:
            return await handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, False, state)
    else:
        print("handleLoop - Ended Woolix due to result=", result, "or canCheckOut=", canCheckOut)
        return False
    
async def woolix(bot, interaction, orderLink, cardNumber, expDate, cvv, zipCode, emailAcc, aco, type):
    orderInfo = f'{orderLink},{cardNumber},{expDate},{cvv},{zipCode},{emailAcc}'
    session = await create_session()

    try:
        async with session:
            # Sends !aco to Woolix process
            await returnMessage("once", session)
            await asyncio.sleep(1)
            await returnMessage("twice", session)
            await asyncio.sleep(1)
            await returnMessage("yay", session)
            await asyncio.sleep(1)
            response = await returnMessage("!aco", session)
            await interaction.followup.send("Starting Order...")

            if response.status == 200:
                await asyncio.sleep(2)
                if await getOrderInfoMSG(session):  # STEP 1, ORDER
                    response = await returnMessage(orderInfo, session)
                    await interaction.followup.send("Collecting cart items.")

                    if response.status == 200:
                        await asyncio.sleep(3)

                        # ✅ Only run OTP for non-ACO (i.e., when OTP is expected)
                        if not aco:
                            otp_ok = await OTP(interaction, session, emailAcc)
                            if not otp_ok:
                                await interaction.followup.send("Cart Failed.")
                                print("Ended Woolix")
                                return "OTP verification failed."
                        else:
                            # ACO/Woolix accounts: skip OTP entirely
                            print("Skipping OTP step for ACO/Woolix account")

                        # Continue to checkout loop
                        try:
                            await handleLoop(session, bot, interaction, emailAcc, aco, type, orderLink, True, 0)
                            return
                        except Exception as e:
                            await session.post(ERROR_WEBHOOK, data={"content": f"Problem with CHECKOUT func: {e}"})
                            await interaction.followup.send("Checkout Failed.")
                            print(f"Problem with CHECKOUT func: {e}")
                        print("Ended Woolix")
                        return
                    else:
                        await interaction.followup.send("Failed to send order info.")
                        print("Ended Woolix")
                        return "Failed to send order info."
                else:
                    await interaction.followup.send("Failed to retrieve order info message.")
                    print("Ended Woolix")
                    return "Failed to retrieve order info message."
            else:
                await interaction.followup.send("ACO Failed!")
                await session.post(ERROR_WEBHOOK, data={"content": "Failed at !ACO, Check Token."})
                print("Ended Woolix")
                return "ACO Failed!"
    except Exception as e:
        print(f"Error occurred: {e}")
        await interaction.followup.send("An error occurred during processing.")
        print("Ended Woolix")
        return "Processing error."
    print("Ended Woolix")
    return "Processing completed."
