import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from app.config import LOG_LEVEL
from app.proxy import forward_stream_chat
from app.scrubber import session_store

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pii-proxy")


async def _cleanup_loop():
    while True:
        await asyncio.sleep(300)
        removed = session_store.cleanup_expired()
        if removed:
            logger.info("Session cleanup: removed %d expired sessions", removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


# CORS is handled by Caddy — do not add CORSMiddleware here or the browser
# will see duplicate Access-Control-Allow-Origin headers and reject the response.
app = FastAPI(title="pii-proxy", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "phase": 2,
        "presidio": True,
        "spacy_model": "en_core_web_lg",
        "active_sessions": session_store.active_session_count,
    }


@app.post("/api/embed/{embed_id}/stream-chat")
async def stream_chat(embed_id: str, request: Request):
    return await forward_stream_chat(embed_id, request)
