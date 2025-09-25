import asyncio
import json
import time
import logging
import aiohttp
import websockets
import sys
import os
from dotenv import load_dotenv

load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('discord_active_clicker')

class DiscordActiveClicker:
    def __init__(self, token, guild_id=None):
        self.token = token
        self.guild_id = guild_id
        
        self.headers = {
            'Authorization': token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
            'Origin': 'https://discord.com',
            'X-Debug-Options': 'bugReporterEnabled',
            'X-Discord-Locale': 'en-US',
            'X-Discord-Timezone': 'Europe/Amsterdam',
        }
        self.headers['Referer'] = f'https://discord.com/channels/{guild_id}' if guild_id else 'https://discord.com/channels/@me'

        self.gateway_url = None
        self.session_id = None
        self.session_ready = asyncio.Event()
        self.last_sequence = None
        self.http_session = None
        self.application_ids = set()
        self.ephemeral_messages = []
        self.clicked_buttons = set()
        self.default_channel_id = ""
        self.active_scanning = False
        self.scan_interval = 1
        self.is_dm_mode = guild_id is None
        self.message_cache = set()

    async def get_gateway_url(self):
        async with self.http_session.get('https://discord.com/api/v9/gateway') as response:
            if response.status == 200:
                data = await response.json()
                self.gateway_url = data['url'] + '/?v=9&encoding=json'
                logger.info(f"Got gateway URL: {self.gateway_url}")
                return True
            else:
                logger.error(f"Failed to get gateway URL: {response.status} - {await response.text()}")
                return False

    async def heartbeat(self, websocket, interval):
        while True:
            try:
                await asyncio.sleep(interval / 1000)
                await websocket.send(json.dumps({'op': 1, 'd': self.last_sequence}))
                logger.debug("Sent heartbeat")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                return

    async def identify(self, websocket):
        payload = {
            'op': 2,
            'd': {
                'token': self.token,
                'properties': {
                    '$os': 'windows',
                    '$browser': 'chrome',
                    '$device': 'pc'
                },
                'presence': {
                    'status': 'online',
                    'since': 0,
                    'activities': [],
                    'afk': False
                },
                'intents': 32767
            }
        }
        await websocket.send(json.dumps(payload))
        logger.info("Sent identify payload")

    def process_message(self, message):
        flags = message.get('flags', 0)
        is_ephemeral = (flags & 64) != 0
        message_id = message.get('id')
        channel_id = message.get('channel_id')

        application_id = message.get("application_id") or \
                         message.get("application", {}).get("id") or \
                         message.get("interaction", {}).get("application_id")

        if application_id:
            self.application_ids.add(application_id)
        else:
            return False

        if 'components' not in message:
            return None

        button_data = []
        for row in message.get('components', []):
            if row.get('type') != 1:
                continue
            for component in row.get('components', []):
                if component.get('type') != 2:
                    continue
                custom_id = component.get('custom_id')
                if not custom_id:
                    continue
                label = component.get('label', 'Unlabeled')
                button_data.append({
                    'message_id': message_id,
                    'channel_id': channel_id,
                    'custom_id': custom_id,
                    'label': label,
                    'application_id': application_id,
                    'is_ephemeral': is_ephemeral
                })

        if is_ephemeral and len(button_data) >= 3:
            third_button = button_data[2]
            button_key = f"{message_id}:{third_button['custom_id']}"
            if button_key not in self.clicked_buttons and self.session_ready.is_set():
                asyncio.create_task(self.click_button(third_button))

        return button_data if button_data else None

    async def process_dispatch_event(self, event_type, data):
        if event_type == 'READY':
            self.session_id = data['session_id']
            logger.info(f"Connected as {data['user']['username']}")
            self.session_ready.set()
        elif event_type in ['MESSAGE_CREATE', 'MESSAGE_UPDATE']:
            self.process_message(data)
        elif event_type == 'INTERACTION_CREATE' and 'application_id' in data:
            self.application_ids.add(data['application_id'])

    async def process_gateway_event(self, event, websocket):
        op = event.get('op')
        if op == 10:
            asyncio.create_task(self.heartbeat(websocket, event['d']['heartbeat_interval']))
            await self.identify(websocket)
        elif op == 0:
            self.last_sequence = event['s']
            await self.process_dispatch_event(event.get('t'), event.get('d', {}))

    async def listen_gateway(self):
        if not await self.get_gateway_url():
            return False
        try:
            async with websockets.connect(self.gateway_url, max_size=100 * 1024 * 1024, ping_interval=30, ping_timeout=10) as websocket:
                logger.info("Connected to WebSocket")
                while True:
                    message = await websocket.recv()
                    await self.process_gateway_event(json.loads(message), websocket)
        except Exception as e:
            logger.error(f"Gateway listen error: {e}")
            return False
        return True

    async def click_button(self, button):
        if not self.session_ready.is_set():
            await asyncio.wait_for(self.session_ready.wait(), timeout=10)
        message_id = button['message_id']
        channel_id = button['channel_id']
        custom_id = button['custom_id']
        application_id = button['application_id']
        button_key = f"{message_id}:{custom_id}"
        if button_key in self.clicked_buttons:
            return True
        payload = {
            "type": 3,
            "nonce": str(int(time.time() * 1000)),
            "channel_id": channel_id,
            "message_flags": 64,
            "message_id": message_id,
            "application_id": application_id,
            "session_id": self.session_id,
            "data": {
                "component_type": 2,
                "custom_id": custom_id
            }
        }
        if self.guild_id and not self.is_dm_mode:
            payload["guild_id"] = self.guild_id
        try:
            async with self.http_session.post('https://discord.com/api/v9/interactions', json=payload) as response:
                if response.status == 204:
                    self.clicked_buttons.add(button_key)
                    return True
        except Exception as e:
            logger.error(f"Click error: {e}")
        return False

    async def run(self):
        self.http_session = aiohttp.ClientSession(headers=self.headers)
        try:
            await self.listen_gateway()
        finally:
            await self.http_session.close()

async def main():
    token = os.environ.get("USER_TOKEN")
    guild_id = None
    if not token:
        print("No token provided")
        return
    clicker = DiscordActiveClicker(token, guild_id)
    await clicker.run()

if __name__ == "__main__":
    asyncio.run(main())
