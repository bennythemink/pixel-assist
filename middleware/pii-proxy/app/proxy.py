import logging
import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse
from app.config import ANYTHINGLLM_BASE_URL
from app.scrubber import scrub

logger = logging.getLogger("pii-proxy")


async def forward_stream_chat(embed_id: str, request: Request) -> StreamingResponse:
    body = await request.json()
    original_message = body.get("message", "")

    try:
        modified_message = scrub(original_message, body.get("sessionId", "unknown"))
        body["message"] = modified_message

        logger.info(
            "stream-chat embed_id=%s sessionId=%s modified=%s",
            embed_id,
            body.get("sessionId", "?"),
            modified_message != original_message,
        )
    except Exception:
        logger.exception("Scrub failed — forwarding original message (fail-open)")
        body["message"] = original_message

    target_url = f"{ANYTHINGLLM_BASE_URL}/api/embed/{embed_id}/stream-chat"

    # Forward all headers except ones httpx needs to set itself
    forward_headers = {
        key: val for key, val in request.headers.items()
        if key.lower() not in ("host", "content-length", "transfer-encoding")
    }
    forward_headers["content-type"] = "application/json"

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0))

    try:
        upstream_req = client.build_request(
            "POST",
            target_url,
            json=body,
            headers=forward_headers,
        )
        upstream_resp = await client.send(upstream_req, stream=True)
    except Exception:
        logger.exception("Failed to connect to AnythingLLM at %s", target_url)
        await client.aclose()
        # Fail-open: try once more with the original message
        try:
            client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0))
            body["message"] = original_message
            upstream_req = client.build_request(
                "POST",
                target_url,
                json=body,
                headers=forward_headers,
            )
            upstream_resp = await client.send(upstream_req, stream=True)
        except Exception:
            logger.exception("Fail-open retry also failed")
            await client.aclose()
            return StreamingResponse(
                iter(["data: {\"error\": \"proxy upstream unreachable\"}\n\n"]),
                status_code=502,
                media_type="text/event-stream",
            )

    async def stream_generator():
        try:
            async for chunk in upstream_resp.aiter_bytes():
                yield chunk
        except Exception:
            logger.exception("Error while streaming SSE response")
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    # Forward response headers from AnythingLLM, excluding CORS (handled by middleware)
    # and transport-level headers that don't apply to the proxied response
    response_headers = {
        key: val for key, val in upstream_resp.headers.items()
        if key.lower() not in (
            "transfer-encoding", "content-encoding", "content-length",
            "access-control-allow-origin", "access-control-allow-methods",
            "access-control-allow-headers", "access-control-allow-credentials",
            "access-control-expose-headers", "access-control-max-age",
        )
    }
    response_headers["Cache-Control"] = "no-cache"
    response_headers["Connection"] = "keep-alive"
    response_headers["X-Accel-Buffering"] = "no"

    return StreamingResponse(
        stream_generator(),
        status_code=upstream_resp.status_code,
        media_type="text/event-stream",
        headers=response_headers,
    )
