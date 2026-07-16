"""Shared live-progress store for extractions (SSE streaming).

The scrapers push progress events (current company, its logo URL,
running email count) into a stable module-level asyncio queue.
The backend streams them to the frontend via Server-Sent Events at
GET /extract/stream. A stable singleton queue is used so the
SSE generator and the scrape task always share the same queue
(even if /extract/stream connects before /extract fires).
"""
import asyncio
import json
import time

# Stable singleton queue + lock. reset() only drains it; it never
# replaces the object, so concurrent connections stay consistent.
_STATE = {"queue": None, "lock": None}


def _get_queue():
    if _STATE["queue"] is None:
        _STATE["queue"] = asyncio.Queue()
        _STATE["lock"] = asyncio.Lock()
    return _STATE["queue"]


def reset():
    """Drop any stale events left from a previous scrape."""
    q = _get_queue()
    while not q.empty():
        try:
            q.get_nowait()
        except Exception:
            break


async def emit(event: dict):
    """Push a progress event (called from the async scrape task)."""
    await _get_queue().put(event)


def set_progress(running, source_label="", current_company="", current_logo_url="",
                emails_found=0, pages_fetched=0, status="running"):
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        return
    asyncio.ensure_future(emit({
        "type": "progress",
        "running": running,
        "source_label": source_label,
        "current_company": current_company,
        "current_logo_url": current_logo_url,
        "emails_found": emails_found,
        "pages_fetched": pages_fetched,
        "status": status,
        "ts": time.time(),
    }))


def emit_log(type_, message):
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        return
    asyncio.ensure_future(emit({
        "type": "log",
        "log_type": type_,
        "message": message,
        "ts": time.time(),
    }))


async def stream_generator():
    """Yield SSE-formatted progress events until the scrape finishes."""
    q = _get_queue()
    yield ": connected\n\n"  # comment so the browser opens the stream immediately
    while True:
        try:
            event = await asyncio.wait_for(q.get(), timeout=30.0)
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"  # heartbeat keeps the connection alive
            continue
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if event.get("type") == "progress" and event.get("status") in ("done", "error", "stopped"):
            break
