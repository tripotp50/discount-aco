import motor
from dotenv import load_dotenv
import os
from bson import ObjectId
from pymongo import ReturnDocument
import motor.motor_asyncio
import random
import string
import io
import pandas as pd

from datetime import datetime, timedelta, timezone

load_dotenv()

CONNECTION_STRING = os.getenv('MONGODB_TEST_CONNECTION')

client = motor.motor_asyncio.AsyncIOMotorClient(CONNECTION_STRING)
db = client['peddler']
userCollection = db['user']
orderCollection = db['orders']
infoCollection = db['info']
addyCollection = db['addy']

async def updateEmail(email, newEmail):
    await infoCollection.update_one(
                {"email": email},  # Find the account by email
                {"$set": {"email": newEmail}}
            )
    print(f"{email} changed to {newEmail}.")
    return

async def clearAcc():
    try:
        # Delete all documents where status is 'dead'
        result = await infoCollection.delete_many({"status": "dead"})
        return f"Deleted {result.deleted_count} documents with status 'dead'."
    except Exception as e:
        return f"An error occurred while deleting the documents: {e}"

async def accLeft():
    try:
        # Count only documents where status is 'active'
        count = await infoCollection.count_documents({"status": "active"})
        return count
    except Exception as e:
        return f"An error occurred while counting the documents: {e}"

async def updateBalance(userID, creditsToLoad, cost, order):
    userID = str(userID)
    user = await userCollection.find_one({ "userID": userID })
    if user:
        await userCollection.update_one(
            {"userID": userID},
            {"$inc": 
                {"credits": float(creditsToLoad)}
            }
        )
    else:
        await userCollection.insert_one({
                "userID": userID, 
                "credits": float(creditsToLoad)  # Ensure 'credits' is properly initialized
            })
    await orderCollection.insert_one({
        "userID": userID,
        "credits": float(creditsToLoad),
        "orderID": order,
        "CostOfOrder": cost
        }
    )

async def whitelistCheck(userID):
    userID = str(userID)
    data = await userCollection.find_one({"userID": userID})
    if data:
        access = data.get("whitelist", False)
        return access
    else:
        userCollection.insert_one({
            "userID": str(userID),
            "credits": float(0),
            "whitelist": False
        })
        return False

async def whitelistUser(userID, add):
    if add:
        print(f"whitelist ({userID})")
        whitelist = True
    else:
        print(f"whitelist ({userID})")
        whitelist = False
    userID = str(userID)
    data = await userCollection.find_one({"userID": userID})
    if data:
        await userCollection.update_one(
            {"userID": userID},
            {"$set": 
                {"whitelist": whitelist}
            }
        )
        return
    else:
        userCollection.insert_one({
            "userID": str(userID),
            "credits": float(0),
            "whitelist": whitelist
        })
        return
    
async def getBalance(userID):
    print(f"Balance check on ({userID})")
    userID = str(userID)
    data = await userCollection.find_one({"userID": userID})
    if data:
        credits = data.get("credits", "No credits found")
        return float(credits)
    else:
        userCollection.insert_one({
            "userID": str(userID),
            "credits": float(0),
            "whitelist": False
        })
        return float(0)

async def getFirstInfo(type): #Obtains the info necessary for ordering
    info = await infoCollection.find_one(
        {"status": "active", "type": type},
        sort=[("_id", 1)]  # 1 for ascending order
    )
    if not info:
        info = await infoCollection.find_one(
        {"status": "active", "type": "unknown"},
        sort=[("_id", 1)]  # 1 for ascending order
        )
    if info:
        cardNumber = info.get("cardNumber")
        expDate = info.get("expDate")
        cvv = info.get("cvv")
        email = info.get("email")
        print(f"card {cardNumber} is being used.")
        return cardNumber, expDate, cvv, email
    else:
        return f"No accounts left for {type}"

async def updateType(emailAcc, type):
    type = str(type)
    try:
        await infoCollection.update_one(
            {"email": emailAcc},
            {"$set": 
                {"type": type}
            }
        )
        print(f"{emailAcc} type was updated to {type}.")
    except:
        pass
    return

async def upload_csv_to_mongo(csv_file):
    try:
        # Read the CSV from the file-like object
        data = pd.read_csv(io.StringIO(csv_file.decode('utf-8')))

        # Create a list of dictionaries to insert into MongoDB
        data_dict = []
        for _, row in data.iterrows():
            # Convert each row into the desired format
            formatted_row = {
                "cardNumber": str(row['cardNumber']),  # Convert to MongoDB's Int64 for large numbers
                "cvv": str(row['cvv']),  # Ensure it's a string
                "expDate": str(row['expDate']),  # Ensure it's a string
                "email": str(row['email']),  # Ensure it's a string
                "status": "active",  # Default status
                "usage": 0,  # Default usage
                "type": str(row['type'])  # Ensure it's a string
            }
            data_dict.append(formatted_row)

        # Insert the data into MongoDB
        infoCollection.insert_many(data_dict)
        return "CSV data uploaded successfully to MongoDB!"

    except Exception as e:
        return f"An error occurred: {e}"
    
async def updateInfo(emailAcc):
    # Find the account and increment usage, returning the updated document
    acc = await infoCollection.find_one_and_update(
        {"email": emailAcc},  # Query to find the account
        {"$inc": {"usage": 1}},  # Increment the usage field by 1
        return_document=ReturnDocument.AFTER  # Return the updated document after the update
    )

    if acc:
        accUsage = acc.get("usage")  # Get the updated usage value
        if accUsage >= 2:  # If usage is 2 or more, mark the account as "dead"
            await setDeadStatus(emailAcc)
            return
        else:
            print(f"Account {emailAcc} usage is now {accUsage}.")
    else:
        print(f"Account with email {emailAcc} not found.")
    return

async def setDeadStatus(emailAcc):
    await infoCollection.update_one(
                {"email": emailAcc},  # Find the account by email
                {"$set": {"status": "dead"}}  # Update the status to "dead"
            )
    print(f"{emailAcc} marked as dead.")
    return

async def setAddy(addy):
    await addyCollection.find_one_and_update(
        {"type": "current"},
        {"$set": {"address": addy}}
    )

async def checkAddy():
    curr = await addyCollection.find_one({"type": "current"})
    if not curr:
        return False  # Handle missing "current" document case

    data = await addyCollection.find_one({"address": curr["address"]})
    
    if data:
        # Check if it's banned and has a "banned_at" timestamp
        if data.get("type") == "banned":
            banned_at = data.get("banned_at")
            if banned_at:
                banned_time = datetime.fromisoformat(banned_at)  # Use ISO format for safer conversion
                if datetime.now(timezone.utc) - banned_time >= timedelta(hours=48):
                    # Unban the address after 48 hours
                    await addyCollection.update_one(
                        {"_id": data["_id"]},
                        {"$set": {"type": "unbanned"}, "$unset": {"banned_at": ""}}
                    )
                    return False  # Considered unbanned now
            return True  # Still banned if under 48 hours
        return False  # Not banned
    else:
        # Create a new entry if it doesn't exist
        await addyCollection.insert_one({
            "address": str(curr["address"]),
            "type": "unbanned",
            "tries": 0,
            "banned_at": datetime.now(timezone.utc).isoformat()
        })
        return False

async def incrementAddy():
    curr = await addyCollection.find_one({"type": "current"})
    if not curr:
        return

    data = await addyCollection.find_one({"address": curr["address"]})
    if data:
        if data.get("tries", 0) == 2:
            await addyCollection.update_one(
                {"_id": data["_id"]},
                {"$set": {
                    "tries": 0,
                    "type": "banned",
                    "banned_at": datetime.now(timezone.utc).isoformat()  # Store as ISO format
                }}
            )
        else:
            await addyCollection.update_one(
                {"_id": data["_id"]},
                {"$inc": {"tries": 1}}
            )

async def resetAddy():
    curr = await addyCollection.find_one({"type": "current"})
    if not curr:
        return

    data = await addyCollection.find_one({"address": curr["address"]})
    if data:
        await addyCollection.update_one(
            {"_id": data["_id"]},
            {"$set": {"tries": 0}}
        )
