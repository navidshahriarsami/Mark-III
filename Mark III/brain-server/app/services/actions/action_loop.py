"""
MARK III — Action Loop

Bridges the synchronous, threading-based live architecture (always_listening_loop.py,
mesh_manager.py) with the async AsyncActionQueue (action_queue.py).

The Action Engine (action_queue, policy_engine, executors) is internally async —
that's preserved as-is, since asyncio.Queue/Semaphore/Event are how it coordinates
concurrent action execution, retries, and approval waits. Rather than rewriting
that machinery synchronously, this module runs ONE dedicated background thread
with its own event loop, and exposes a thread-safe synchronous bridge so the
voice loop (a plain Python thread) can submit actions and block for a result.

Usage from always_listening_loop.py:

    from app.services.actions.action_loop import submit_action_sync

    result_text = submit_action_sync(request, timeout=APPROVAL_TIMEOUT_SECONDS + 5)
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

log = logging.getLogger("markiii.actions.loop")

_loop:   Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread]          = None
_lock    = threading.Lock()
_started = False


def start() -> None:
    """Start the background event loop thread and the AsyncActionQueue inside it."""
    global _loop, _thread, _started
    with _lock:
        if _started:
            return
        _loop   = asyncio.new_event_loop()
        _thread = threading.Thread(target=_run_loop, args=(_loop,), name="action-loop", daemon=True)
        _thread.start()
        _started = True
    log.info("Action Loop thread started")


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_bootstrap())
    loop.run_forever()


async def _bootstrap() -> None:
    from app.services.actions.action_queue import get_action_queue
    await get_action_queue().start()
    log.info("Action Queue running inside Action Loop thread")


def submit_action_sync(request, timeout: float = 35.0):
    """
    Submit an ActionRequest from synchronous code (the voice loop) and block
    until the action reaches a terminal state OR enters AWAITING_APPROVAL
    (whichever comes first) — so the caller can speak the approval prompt
    immediately as the response, without blocking the voice thread for the
    full approval window.

    Returns the live Action object (base_action.Action).
    Raises if the action loop hasn't been started, or on submit validation errors.
    """
    if not _started or _loop is None:
        raise RuntimeError("Action Loop not started — call action_loop.start() first")

    future = asyncio.run_coroutine_threadsafe(_submit_and_wait(request), _loop)
    return future.result(timeout=timeout)


async def _submit_and_wait(request):
    from app.services.actions.action_queue import get_action_queue
    from app.services.actions.base_action import ActionState

    queue  = get_action_queue()
    action = await queue.submit(request)

    # Poll briefly for a terminal/awaiting-approval state so the caller gets
    # an immediate spoken response (either the result or the approval prompt).
    for _ in range(100):   # ~5s at 50ms — covers SAFE-tier sync execution
        current = queue.get_action(action.id)
        if current and (
            current.is_terminal() or current.state == ActionState.AWAITING_APPROVAL.value
        ):
            return current
        await asyncio.sleep(0.05)

    return queue.get_action(action.id) or action


def is_running() -> bool:
    return _started


def schedule_threadsafe(fn, *args) -> None:
    """
    Schedule a zero-arg-returning callable to run on the action loop's event
    loop, from any other thread. Required for anything that touches asyncio
    primitives owned by this loop (e.g. asyncio.Event.set()) — calling those
    directly from a different OS thread is not safe and can silently fail to
    wake a waiting coroutine.
    """
    if not _started or _loop is None:
        return
    _loop.call_soon_threadsafe(fn, *args)
