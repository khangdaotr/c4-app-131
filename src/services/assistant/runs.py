"""Slim run reservation and in-process cancellation (single worker only).

No equivalent run registry exists in the legacy agent. Conversation and turn
storage remain the existing ORM models; no graph/checkpoint state is stored.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from threading import RLock, get_ident
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.config import get_settings
from src.db.database import SessionLocal
from src.db.models import AssistantConversation, AssistantRun, AssistantTurn, User, utcnow
from src.models.assistant import AssistantRunResponse, ChatRequest, ChatResponse

_tasks: dict[str, asyncio.Task[ChatResponse]] = {}
logger = logging.getLogger(__name__)


def owned_run(db: Session, run_id: str, user: User) -> AssistantRun:
    run = db.scalar(
        select(AssistantRun)
        .join(AssistantConversation)
        .where(
            AssistantRun.id == run_id,
            AssistantRun.user_id == user.id,
            AssistantConversation.user_id == user.id,
            AssistantConversation.role == user.role,
        )
    )
    if run is None:
        raise AppError(404, "Không tìm thấy lượt chạy.", "NOT_FOUND")
    return run


def run_response(run: AssistantRun) -> AssistantRunResponse:
    return AssistantRunResponse.model_validate(run, from_attributes=True)


def existing_run(db: Session, body: ChatRequest, user: User) -> AssistantRun | None:
    query = (
        select(AssistantRun)
        .join(AssistantConversation)
        .where(
            AssistantRun.user_id == user.id,
            AssistantConversation.user_id == user.id,
            AssistantConversation.role == user.role,
            AssistantRun.client_request_id == body.client_request_id,
        )
    )
    if body.conversation_id:
        query = query.where(AssistantRun.conversation_id == body.conversation_id)
    return db.scalar(query.order_by(AssistantRun.created_at.desc()))


def reserve(
    db: Session, body: ChatRequest, user: User, conversation: AssistantConversation
) -> tuple[AssistantRun, bool]:
    previous = existing_run(db, body, user)
    if previous is not None:
        return previous, False
    run = AssistantRun(
        conversation_id=conversation.id,
        user_id=user.id,
        client_request_id=body.client_request_id,
        route=body.context.route,
        status="running",
    )
    db.add(conversation)
    db.add(run)
    try:
        db.flush()
        db.add(
            AssistantTurn(
                conversation_id=conversation.id,
                run_id=run.id,
                user_message=body.message,
                assistant_message="",
                intent="qa",
                context_json=body.context.model_dump(mode="json"),
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = existing_run(db, body, user)
        if previous is not None:
            return previous, False
        raise AppError(409, "Hội thoại đang có lượt chạy. Hãy dừng trước khi gửi tiếp.", "run_in_progress") from None
    return run, True


def finish_interrupted(run_id: str, body: ChatRequest, status: str, partial_message: str | None = None) -> None:
    with SessionLocal() as db:
        changed = db.execute(
            update(AssistantRun)
            .where(
                AssistantRun.id == run_id,
                AssistantRun.status == "running",
            )
            .values(status=status, updated_at=utcnow())
        ).rowcount
        if changed:
            run = db.get(AssistantRun, run_id)
            turn = db.scalar(select(AssistantTurn).where(AssistantTurn.run_id == run_id))
            if turn is None:
                db.add(
                    AssistantTurn(
                        conversation_id=run.conversation_id,
                        run_id=run_id,
                        user_message=body.message,
                        assistant_message=partial_message or "",
                        intent="qa",
                        context_json=body.context.model_dump(mode="json"),
                        interrupted=True,
                    )
                )
            else:
                turn.interrupted = True
                if partial_message is not None:
                    turn.assistant_message = partial_message
            db.commit()


def sweep_running(db: Session) -> int:
    ids = list(db.scalars(select(AssistantRun.id).where(AssistantRun.status == "running")))
    if ids:
        db.execute(update(AssistantTurn).where(AssistantTurn.run_id.in_(ids)).values(interrupted=True))
        db.execute(
            update(AssistantRun)
            .where(AssistantRun.id.in_(ids), AssistantRun.status == "running")
            .values(status="interrupted", updated_at=utcnow())
        )
        db.commit()
    return len(ids)


async def cancel(run_id: str) -> None:
    task = _tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def execute(
    run_id: str, body: ChatRequest, request: Request, respond: Callable[[], Awaitable[ChatResponse]]
) -> ChatResponse | AssistantRunResponse:
    async def worker() -> ChatResponse:
        try:
            return await respond()
        except asyncio.CancelledError:
            finish_interrupted(run_id, body, "cancelled")
            raise
        except Exception:
            finish_interrupted(run_id, body, "failed")
            raise AppError(
                503, "Trợ lý tạm thời chưa thể trả lời. Vui lòng thử lại.", "assistant_unavailable"
            ) from None

    task = asyncio.create_task(worker())
    _tasks[run_id] = task
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=0.1)
            if not done and await request.is_disconnected():
                await cancel(run_id)
        if task.cancelled():
            finish_interrupted(run_id, body, "cancelled")
            with SessionLocal() as db:
                return run_response(db.get(AssistantRun, run_id))
        return task.result()
    except asyncio.CancelledError:
        await cancel(run_id)
        raise
    finally:
        _tasks.pop(run_id, None)


def stream(
    run_id: str,
    conversation_id: str,
    body: ChatRequest,
    request: Request,
    respond: Callable[..., Awaitable[ChatResponse]],
) -> StreamingResponse:
    """One producer per reserved run. Generator teardown always joins upstream."""
    from src.services.assistant import streaming
    from src.services.assistant.howto import answer_language

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        loop_thread = get_ident()
        encoder = streaming.EventEncoder(run_id, conversation_id)
        guard = streaming.OutputGuard("you" if answer_language(body.message) == "en" else "bạn")
        partial = ""
        saved_partial = ""
        partial_lock = RLock()

        def snapshot() -> str:
            with partial_lock:
                return partial

        def checkpoint() -> None:
            nonlocal saved_partial
            text = snapshot()
            if text == saved_partial:
                return
            with SessionLocal() as db:
                db.execute(update(AssistantTurn).where(AssistantTurn.run_id == run_id).values(assistant_message=text))
                db.commit()
            saved_partial = text

        def sink(name: str, data: dict[str, Any]) -> None:
            nonlocal partial
            if name not in streaming.EVENTS:
                raise ValueError("Unsupported assistant event")
            if name == "token":
                with partial_lock:
                    text = guard.feed(data["text"])
                    if not text:
                        return
                    if len(partial) + len(text) > 16000:
                        raise ValueError("Assistant output exceeds the response limit")
                    partial += text
                data = {"text": text}
            elif name == "route":
                with SessionLocal() as db:
                    db.execute(update(AssistantRun).where(AssistantRun.id == run_id).values(route=data["route"]))
                    db.commit()
            if get_ident() == loop_thread:
                queue.put_nowait((name, data))
            else:
                loop.call_soon_threadsafe(queue.put_nowait, (name, data))

        async def worker() -> ChatResponse:
            nonlocal partial
            try:
                with SessionLocal() as db:
                    run = db.get(AssistantRun, run_id)
                    if run.status != "running":
                        raise asyncio.CancelledError
                sink("status", {"status": "thinking"})
                response = await respond(sink)
                if not snapshot():
                    sink("token", {"text": response.message})
                with partial_lock:
                    tail = guard.finish()
                    if len(partial) + len(tail) > 16000:
                        raise ValueError("Assistant output exceeds the response limit")
                    partial += tail
                    partial_text = partial
                if tail:
                    # finish() already sanitized the tail; do not feed it into the guard again.
                    queue.put_nowait(("token", {"text": tail}))
                response = response.model_copy(update={"message": partial_text})
                checkpoint()
                if response.sources:
                    sink("citations", {"sources": [source.model_dump(mode="json") for source in response.sources]})
                for card in response.cards:
                    sink("card", {"card": card.model_dump(mode="json")})
                if response.chips:
                    sink("card", {"chips": [chip.model_dump(mode="json") for chip in response.chips]})
                for action in response.ui_actions:
                    sink("ui_action", {"action": action.model_dump(mode="json")})
                sink("final", response.model_dump(mode="json"))
                return response
            except asyncio.CancelledError:
                text = snapshot()
                finish_interrupted(run_id, body, "cancelled", text)
                queue.put_nowait(("final", {"status": "cancelled", "interrupted": True, "message": text}))
                raise
            except Exception:
                finish_interrupted(run_id, body, "failed", snapshot())
                queue.put_nowait(
                    ("error", {"code": "assistant_unavailable", "message": "Assistant temporarily unavailable."})
                )
                raise

        task = asyncio.create_task(worker())
        _tasks[run_id] = task
        next_heartbeat = asyncio.get_running_loop().time() + streaming.HEARTBEAT_SECONDS
        checkpoint_seconds = get_settings().assistant_stream_checkpoint_seconds
        next_checkpoint = loop.time() + checkpoint_seconds
        try:
            while not task.done() or not queue.empty():
                if await request.is_disconnected():
                    break
                try:
                    name, data = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield encoder.encode(name, data)
                except TimeoutError:
                    pass
                now = asyncio.get_running_loop().time()
                if not task.done() and now >= next_checkpoint:
                    try:
                        checkpoint()
                    except SQLAlchemyError:
                        # A transient checkpoint failure must not tear down SSE.
                        # Final/cancel/error persistence is still mandatory.
                        logger.warning("Assistant stream checkpoint unavailable")
                    next_checkpoint = now + checkpoint_seconds
                if not task.done() and now >= next_heartbeat:
                    yield encoder.encode("heartbeat", {})
                    next_heartbeat = now + streaming.HEARTBEAT_SECONDS
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                finish_interrupted(run_id, body, "cancelled", snapshot())
            except Exception:
                pass  # The stream contains a sanitized error, never a traceback.
            _tasks.pop(run_id, None)

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
