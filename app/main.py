from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import JSONResponse
from app.api import router as api_router, r
from app.config import settings
from app.ws_manager import ws_manager
import asyncio, json, os

app = FastAPI(title="AllDebrid Proxy")

@app.on_event("startup")
async def startup():
    # Launch pubsub listener in background
    loop = asyncio.get_event_loop()
    loop.create_task(ws_manager.start_pubsub_loop())

@app.get("/health")
def health():
    # Soft checks + storage write test
    ok = True
    storage = settings.STORAGE_ROOT
    try:
        test_path = os.path.join(storage, ".healthcheck")
        with open(test_path, "w") as fh:
            fh.write("ok")
        os.remove(test_path)
    except Exception as e:
        ok = False
    return JSONResponse({"ok": ok})

app.include_router(api_router)
