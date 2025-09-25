import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from main import DiscordActiveClicker

load_dotenv()

clicker = None

async def start_clicker():
    global clicker
    if clicker is None:
        token = os.environ.get("USER_TOKEN")
        guild_id = ""

        clicker = DiscordActiveClicker(token, guild_id)
        clicker.http_session = aiohttp.ClientSession(headers=clicker.headers)

        asyncio.create_task(monitor_gateway())  # monitor connection
        await clicker.session_ready.wait()
        print("[Bypass] Clicker ready and connected.")

async def monitor_gateway():
    global clicker
    while True:
        try:
            await clicker.listen_gateway()
            print("[Bypass] Gateway connection closed, retrying in 5 seconds...")
        except Exception as e:
            print(f"[Bypass] Gateway crashed with error: {e}, retrying in 5 seconds...")

        await asyncio.sleep(5)

async def bypass(channel_id: int, duration: int = 8):
    await start_clicker()
    await clicker.scan_and_click(channel_id, duration)

async def shutdown_clicker():
    if clicker and clicker.http_session:
        await clicker.http_session.close()
        print("[Bypass] Clicker session closed.") 

