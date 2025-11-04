import asyncio, json
from typing import Dict, Set
import redis
from app.config import settings

class WSManager:
    def __init__(self):
        self.connections: Dict[str, Set] = {}
        self.redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    def add(self, task_id: str, websocket):
        self.connections.setdefault(task_id, set()).add(websocket)

    def remove(self, task_id: str, websocket):
        if task_id in self.connections:
            self.connections[task_id].discard(websocket)
            if not self.connections[task_id]:
                del self.connections[task_id]

    async def broadcast(self, task_id: str, message: dict):
        if task_id not in self.connections:
            return
        data = json.dumps(message)
        dead = set()
        for ws in list(self.connections[task_id]):
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.remove(task_id, ws)

    async def start_pubsub_loop(self):
        # Non-blocking polling to avoid blocking FastAPI startup / event loop
        pubsub = self.redis.pubsub()
        pubsub.psubscribe("task:*")

        while True:
            # get_message() is non-blocking; timeout controls internal sleep
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") in ("message", "pmessage"):
                payload = msg.get("data")
                try:
                    data = json.loads(payload)
                    task_id = data.get("taskId")
                    if task_id:
                        await self.broadcast(task_id, data)
                except Exception:
                    pass
            # yield control so uvicorn can finish startup and serve
            await asyncio.sleep(0.05)

ws_manager = WSManager()
