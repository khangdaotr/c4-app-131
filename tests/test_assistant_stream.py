"""SSE contracts, boundary guards, and durable cancellation without live providers."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from src.config import get_settings
from src.db.database import SessionLocal
from src.db.models import AssistantConversation, AssistantRun, AssistantTurn, User
from src.models.assistant import ChatRequest, ChatResponse
from src.services.assistant import runs, streaming
from tests import test_assistant_runs as run_tests
from tests.test_assistant_runs import payload

assistant_accounts = run_tests.assistant_accounts


@pytest.mark.parametrize(
    "value",
    [
        "Before [[PERSON_123]] after",
        "[[x]][[y]]",
        "a [[unfinished",
        "a <script>bad</script> b",
        "a <|assistant|>b",
        "a [INST]b[/INST] c",
        "Score < 70% and > 30%.",
    ],
)
def test_every_chunk_boundary(value: str) -> None:
    whole = streaming.OutputGuard("you")
    expected = whole.feed(value) + whole.finish()
    for boundary in range(len(value) + 1):
        guard = streaming.OutputGuard("you")
        chunks = [guard.feed(value[:boundary]), guard.feed(value[boundary:]), guard.finish()]
        assert "".join(chunks) == expected, boundary
        assert "[[" not in "".join(chunks)
        assert "PERSON" not in "".join(chunks)
        if "Score" not in value:
            assert "<" not in "".join(chunks)
    guard = streaming.OutputGuard("you")
    assert "".join(guard.feed(char) for char in value) + guard.finish() == expected


def test_nine_application_events_plus_heartbeat_and_whitelist() -> None:
    expected = {"route", "status", "token", "citations", "card", "ui_action", "notice", "final", "error", "heartbeat"}
    assert streaming.EVENTS == expected
    encoder = streaming.EventEncoder("run", "conversation")
    for index, name in enumerate(sorted(expected), start=1):
        wire = encoder.encode(name, {"value": "line\nnext"})
        assert wire.startswith(f"id: {index}\nevent: {name}\n")
        assert json.loads(wire.split("data: ")[1])["run_id"] == "run"
    with pytest.raises(ValueError):
        encoder.encode("reasoning_content", {})


def test_unmatched_placeholder_is_held_until_close() -> None:
    guard = streaming.OutputGuard("you")
    assert guard.feed("Hello [[PER") == "Hello "
    assert guard.feed("SON_abc]") == ""
    assert guard.feed("]!") == "you!"


def test_score_comparisons_are_preserved() -> None:
    guard = streaming.OutputGuard()
    assert guard.feed("Score < 70% and > 30%.") + guard.finish() == "Score < 70% and > 30%."


class Connection:
    disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def reserved(user_id: str):
    body = ChatRequest.model_validate(payload())
    with SessionLocal() as db:
        user = db.get(User, user_id)
        conversation = AssistantConversation(id=uuid4().hex, user_id=user_id, role="student", title="stream")
        run, _ = runs.reserve(db, body, user, conversation)
        return body, run.id, conversation.id


def frame(wire):
    return wire.split("event: ")[1].splitlines()[0], json.loads(wire.split("data: ")[1])


@pytest.mark.asyncio
@pytest.mark.parametrize("threaded", [False, True])
async def test_token_burst_commits_once_and_preserves_full_text(assistant_accounts, monkeypatch, threaded) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    monkeypatch.setattr(get_settings(), "assistant_stream_checkpoint_seconds", 60)
    with SessionLocal() as db:
        turn_id = db.query(AssistantTurn).filter_by(run_id=run_id).one().id
    commits = []

    def committed(session):
        commits.append(1)

    async def respond(sink):
        def produce():
            for _ in range(1000):
                sink("token", {"text": "word "})
            assert not commits, "Streaming tokens must not perform synchronous database writes"

        if threaded:
            await asyncio.to_thread(produce)
        else:
            produce()
        return ChatResponse(
            conversation_id=conversation_id, turn_id=turn_id, run_id=run_id, message="word " * 1000, intent="qa"
        )

    event.listen(SessionLocal.class_, "after_commit", committed)
    try:
        wires = [wire async for wire in runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator]
    finally:
        event.remove(SessionLocal.class_, "after_commit", committed)
    events = [frame(wire) for wire in wires]
    text = "".join(data["text"] for name, data in events if name == "token")
    assert text == "word " * 1000
    assert events[-1][0] == "final" and events[-1][1]["message"] == text
    assert len(commits) == 1
    with SessionLocal() as db:
        assert db.get(AssistantTurn, turn_id).assistant_message == text


@pytest.mark.asyncio
async def test_idle_stream_checkpoints_before_completion(assistant_accounts, monkeypatch) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    monkeypatch.setattr(get_settings(), "assistant_stream_checkpoint_seconds", 0.01)
    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)

    async def respond(sink):
        sink("token", {"text": "Checkpointed [[PERSON_x]] text"})
        await asyncio.Event().wait()

    iterator = runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator
    try:
        async with asyncio.timeout(5):
            while frame(await anext(iterator))[0] != "heartbeat":
                pass
        with SessionLocal() as db:
            run = db.get(AssistantRun, run_id)
            turn = db.query(AssistantTurn).filter_by(run_id=run_id).one()
            assert run.status == "running"
            assert turn.assistant_message == "Checkpointed you text"
    finally:
        await iterator.aclose()
    assert run_id not in runs._tasks


@pytest.mark.asyncio
async def test_transient_checkpoint_failure_keeps_stream_alive_and_retries(assistant_accounts, monkeypatch) -> None:
    from src.db.database import engine

    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    monkeypatch.setattr(get_settings(), "assistant_stream_checkpoint_seconds", 0.01)
    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)
    failed = False
    closed = asyncio.Event()

    def fail_first_write(conn, cursor, statement, parameters, context, executemany):
        nonlocal failed
        if not failed and statement.upper().startswith("UPDATE ASSISTANT_TURNS"):
            failed = True
            raise OperationalError("update", {}, RuntimeError("private database error"))

    async def respond(sink):
        try:
            sink("token", {"text": "Keep streaming"})
            await asyncio.Event().wait()
        finally:
            closed.set()

    iterator = runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator
    event.listen(engine, "before_cursor_execute", fail_first_write)
    try:
        async with asyncio.timeout(5):
            while frame(await anext(iterator))[0] != "heartbeat":
                pass
            assert failed and not closed.is_set()
            while frame(await anext(iterator))[0] != "heartbeat":
                pass
        with SessionLocal() as db:
            assert db.query(AssistantTurn).filter_by(run_id=run_id).one().assistant_message == "Keep streaming"
    finally:
        event.remove(engine, "before_cursor_execute", fail_first_write)
        await iterator.aclose()
    assert closed.is_set() and run_id not in runs._tasks


@pytest.mark.asyncio
async def test_failure_flushes_uncheckpointed_sanitized_text(assistant_accounts, monkeypatch) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    monkeypatch.setattr(get_settings(), "assistant_stream_checkpoint_seconds", 60)

    async def respond(sink):
        sink("token", {"text": "Saved [[PERSON_x]] partial"})
        raise RuntimeError("private provider error")

    wires = [wire async for wire in runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator]
    assert frame(wires[-1])[0] == "error"
    assert "private provider error" not in "".join(wires)
    with SessionLocal() as db:
        assert db.get(AssistantRun, run_id).status == "failed"
        turn = db.query(AssistantTurn).filter_by(run_id=run_id).one()
        assert turn.interrupted and turn.assistant_message == "Saved you partial"


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix_size, terminal_event", [(10, "final"), (15999, "error")])
async def test_guard_tail_is_saved_and_respects_response_limit(assistant_accounts, prefix_size, terminal_event) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    with SessionLocal() as db:
        turn_id = db.query(AssistantTurn).filter_by(run_id=run_id).one().id

    async def respond(sink):
        sink("token", {"text": "x" * prefix_size + "[[PERSON_unfinished"})
        return ChatResponse(
            conversation_id=conversation_id, turn_id=turn_id, run_id=run_id, message="unused", intent="qa"
        )

    wires = [wire async for wire in runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator]
    events = [frame(wire) for wire in wires]
    assert events[-1][0] == terminal_event
    with SessionLocal() as db:
        saved = db.get(AssistantTurn, turn_id).assistant_message
        assert len(saved) <= 16000 and "[[" not in saved
        if terminal_event == "final":
            assert saved == events[-1][1]["message"] == "x" * prefix_size + "you"


@pytest.mark.asyncio
@pytest.mark.parametrize("midstream", [False, True])
@pytest.mark.parametrize("disconnect", [False, True])
async def test_cancel_and_disconnect_persist_partial(assistant_accounts, midstream, disconnect) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    entered = asyncio.Event()
    closed = asyncio.Event()
    connection = Connection()

    async def respond(sink):
        try:
            sink("route", {"route": "howto"})
            if midstream:
                sink("token", {"text": "Saved [[PERSON_x]] partial"})
            entered.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    response = runs.stream(run_id, conversation_id, body, connection, respond)
    iterator = response.body_iterator
    assert frame(await anext(iterator))[0] == "status"
    await entered.wait()
    if midstream:
        while frame(await anext(iterator))[0] != "token":
            pass
    if disconnect:
        connection.disconnected = True
    else:
        await runs.cancel(run_id)
    async for _ in iterator:
        pass
    assert closed.is_set()
    with SessionLocal() as db:
        assert db.get(AssistantRun, run_id).status == "cancelled"
        turn = db.query(AssistantTurn).filter_by(run_id=run_id).one()
        assert turn.interrupted is True
        assert turn.assistant_message == ("Saved you partial" if midstream else "")
    assert run_id not in runs._tasks


@pytest.mark.asyncio
async def test_generator_teardown_cancels_upstream(assistant_accounts) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    closed = asyncio.Event()

    async def respond(sink):
        try:
            sink("token", {"text": "partial"})
            await asyncio.Event().wait()
        finally:
            closed.set()

    iterator = runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator
    await anext(iterator)
    await iterator.aclose()
    assert closed.is_set()
    with SessionLocal() as db:
        turn = db.query(AssistantTurn).filter_by(run_id=run_id).one()
        assert turn.interrupted and turn.assistant_message == "partial"


@pytest.mark.asyncio
async def test_disconnect_before_producer_starts(assistant_accounts) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    connection = Connection()
    connection.disconnected = True
    called = False

    async def respond(sink):
        nonlocal called
        called = True

    assert [wire async for wire in runs.stream(run_id, conversation_id, body, connection, respond).body_iterator] == []
    assert not called
    with SessionLocal() as db:
        run = db.get(AssistantRun, run_id)
        turn = db.query(AssistantTurn).filter_by(run_id=run_id).one()
        assert run.status == "cancelled"
        assert turn.interrupted and turn.assistant_message == ""


@pytest.mark.asyncio
async def test_running_sse_duplicate_conflict_and_http_stop(assistant_accounts) -> None:
    client, headers, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])

    async def respond(sink):
        await asyncio.Event().wait()

    iterator = runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator
    await anext(iterator)
    duplicate = await client.post(
        "/api/v1/assistant/chat",
        headers={**headers["a"], "Accept": "text/event-stream"},
        json=body.model_dump(mode="json"),
    )
    assert duplicate.json()["id"] == run_id
    assert duplicate.json()["status"] == "running"
    conflict = await client.post("/api/v1/assistant/chat", headers=headers["a"], json=payload(conversation_id))
    assert conflict.status_code == 409
    cancelled = await client.post(f"/api/v1/assistant/runs/{run_id}/cancel", headers=headers["a"])
    assert cancelled.json()["status"] == "cancelled"
    await iterator.aclose()


@pytest.mark.asyncio
async def test_real_asgi_disconnect_cancels_producer(assistant_accounts) -> None:
    from src.main import app
    from src.models.assistant import AssistantResponse
    from src.services.assistant.agent import get_assistant_agent

    _, headers, users = assistant_accounts
    body = payload()
    closed = asyncio.Event()
    disconnect = asyncio.Event()
    sent_body = False
    captured = []

    class Agent:
        async def respond(self, *args, **kwargs):
            try:
                kwargs["event_sink"]("token", {"text": "Saved partial"})
                await asyncio.Event().wait()
                return AssistantResponse(message="unreachable", intent="qa")
            finally:
                closed.set()

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            captured.append(message.get("body", b""))
            if b"event: token" in message.get("body", b""):
                disconnect.set()

    app.dependency_overrides[get_assistant_agent] = lambda: Agent()
    try:
        await asyncio.wait_for(
            app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/v1/assistant/chat",
                    "raw_path": b"/api/v1/assistant/chat",
                    "query_string": b"",
                    "root_path": "",
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"accept", b"text/event-stream"),
                        (b"cookie", headers["a"]["Cookie"].encode()),
                    ],
                    "server": ("test", 80),
                    "client": ("test", 123),
                },
                receive,
                send,
            ),
            timeout=10,
        )
        await asyncio.wait_for(closed.wait(), timeout=2)
        with SessionLocal() as db:
            run = (
                db.query(AssistantRun).filter_by(user_id=users["a"], client_request_id=body["client_request_id"]).one()
            )
            turn = db.query(AssistantTurn).filter_by(run_id=run.id).one()
            assert run.status == "cancelled"
            assert turn.interrupted and turn.assistant_message == "Saved partial"
    finally:
        app.dependency_overrides.pop(get_assistant_agent, None)


@pytest.mark.asyncio
async def test_http_sse_headers_templates_route_and_duplicate(assistant_accounts) -> None:
    client, headers, _ = assistant_accounts
    body = payload()
    first = await client.post(
        "/api/v1/assistant/chat", headers={**headers["a"], "Accept": "text/event-stream"}, json=body
    )
    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("text/event-stream")
    assert first.headers["cache-control"] == "no-cache"
    assert first.headers["x-accel-buffering"] == "no"
    events = [frame(wire) for wire in first.text.strip().split("\n\n")]
    assert [name for name, _ in events] == ["status", "route", "token", "final"]
    assert events[1][1]["route"] == "smalltalk"
    final = events[-1][1]
    duplicate = await client.post(
        "/api/v1/assistant/chat", headers={**headers["a"], "Accept": "text/event-stream"}, json=body
    )
    assert duplicate.json()["id"] == final["run_id"]
    history = await client.get(
        f"/api/v1/assistant/conversations/{final['conversation_id']}/history", headers=headers["a"]
    )
    assert history.json()[-1]["content"] == final["message"]


@pytest.mark.asyncio
async def test_heartbeat_and_error_are_sanitized(assistant_accounts, monkeypatch) -> None:
    _, _, users = assistant_accounts
    body, run_id, conversation_id = reserved(users["a"])
    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)

    async def respond(sink):
        await asyncio.sleep(0.25)
        raise RuntimeError("private provider body")

    wires = [wire async for wire in runs.stream(run_id, conversation_id, body, Connection(), respond).body_iterator]
    events = [frame(wire) for wire in wires]
    assert "heartbeat" in [name for name, _ in events]
    assert events[-1][0] == "error"
    assert "private provider body" not in "".join(wires)
    with SessionLocal() as db:
        assert db.get(AssistantRun, run_id).status == "failed"


@pytest.mark.asyncio
async def test_recorded_howto_stream_citations_actions_and_notice(assistant_accounts, tmp_path) -> None:
    from src.main import app
    from src.services.assistant.agent import AssistantAgent, get_assistant_agent
    from tests import test_assistant_howto as howto_tests
    from tests.test_assistant_howto import recorded_howto_client

    # The same retriever fixture, gateway, and graph used by the how-to suite.
    retriever = howto_tests.guide_retriever.__wrapped__()
    provider = recorded_howto_client(tmp_path, ["Select your PDF file. Open the upload control."])
    app.dependency_overrides[get_assistant_agent] = lambda: AssistantAgent(retriever, provider)
    client, headers, _ = assistant_accounts
    body = payload()
    body["message"] = "How do I upload a CV?"
    try:
        response = await client.post(
            "/api/v1/assistant/chat", headers={**headers["a"], "Accept": "text/event-stream"}, json=body
        )
        events = [frame(wire) for wire in response.text.strip().split("\n\n")]
        names = [name for name, _ in events]
        assert {"route", "status", "token", "citations", "notice", "ui_action", "final"} <= set(names)
        tokens = [data["text"] for name, data in events if name == "token"]
        assert len(tokens) > 1
        assert "".join(tokens) == events[-1][1]["message"]
        ids = [int(block.splitlines()[0].split(": ")[1]) for block in response.text.strip().split("\n\n")]
        assert ids == list(range(1, len(ids) + 1))
    finally:
        app.dependency_overrides.pop(get_assistant_agent, None)
        await provider.aclose()


@pytest.mark.asyncio
async def test_card_chips_history_and_structured_choice(assistant_accounts, monkeypatch) -> None:
    from src.main import app
    from src.models.assistant import AssistantCard, AssistantResponse
    from src.services.assistant.agent import get_assistant_agent
    from src.services.assistant.router.rules import clarify

    decision = clarify("open CV or JD", "student", "en")

    class Agent:
        async def respond(self, *args, **kwargs):
            return AssistantResponse(
                message=decision.clarify_question,
                intent="qa",
                chips=[chip.model_dump(mode="json") for chip in decision.chips],
                cards=[AssistantCard(ref="guide", label="CV", route_id="cv_list")],
            )

    app.dependency_overrides[get_assistant_agent] = lambda: Agent()
    client, headers, _ = assistant_accounts
    try:
        first = await client.post(
            "/api/v1/assistant/chat", headers={**headers["a"], "Accept": "text/event-stream"}, json=payload()
        )
        events = [frame(wire) for wire in first.text.strip().split("\n\n")]
        cards = [data for name, data in events if name == "card"]
        assert len(cards) == 2
        final = events[-1][1]
        history = await client.get(
            f"/api/v1/assistant/conversations/{final['conversation_id']}/history", headers=headers["a"]
        )
        assert history.json()[-1]["cards"] == final["cards"]
        assert history.json()[-1]["chips"] == final["chips"]
    finally:
        app.dependency_overrides.pop(get_assistant_agent, None)
    body = payload(final["conversation_id"])
    body["message"] = final["chips"][0]["label"]
    body["chip"] = final["chips"][0]
    chosen = await client.post(
        "/api/v1/assistant/chat", headers={**headers["a"], "Accept": "text/event-stream"}, json=body
    )
    events = [frame(wire) for wire in chosen.text.strip().split("\n\n")]
    assert next(data for name, data in events if name == "route")["route"] == body["chip"]["route"]
    bad = payload(final["conversation_id"])
    bad["chip"] = {**body["chip"], "label": "Forged choice"}
    assert (await client.post("/api/v1/assistant/chat", headers=headers["a"], json=bad)).status_code == 422


@pytest.mark.asyncio
async def test_gateway_live_text_before_done_and_cancel_closes_transport(tmp_path, monkeypatch) -> None:
    from openai.types.chat import ChatCompletionChunk

    from src.services.providers.gateway import provider_scope
    from src.services.providers.llm_client import ContentDelta, LlmClient
    from tests.test_llm_client import USER, chunk, record, settings

    provider = LlmClient(settings=settings(), recorded=record(tmp_path, [{"chunks": []}]))
    closed = asyncio.Event()
    finished = False

    async def upstream():
        nonlocal finished
        try:
            for value in ["Select ", "a PDF", " file. "]:
                yield ChatCompletionChunk.model_validate(chunk({"content": value}))
            await asyncio.Event().wait()
            finished = True
        finally:
            closed.set()

    async def create(_):
        class SDKStream:
            def __init__(self):
                self.iterator = upstream()

            def __aiter__(self):
                return self.iterator

            async def close(self):
                await self.iterator.aclose()

        return SDKStream()

    monkeypatch.setattr(provider._transport, "create", create)
    try:
        with provider_scope(mask_only=True):
            iterator = provider.chat_stream(USER, stream_text=True)
            assert isinstance(await anext(iterator), ContentDelta)
            assert not finished
            await iterator.aclose()
            assert closed.is_set()
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_private_text_stream_masks_identifiers_split_character_by_character(tmp_path) -> None:
    from src.services.providers.gateway import provider_scope
    from src.services.providers.llm_client import ContentDelta, Done, LlmClient
    from tests.test_llm_client import USER, chunk, record, settings

    text = "Contact an@example.test or 0912345678. Select a PDF."
    provider = LlmClient(
        settings=settings(),
        recorded=record(
            tmp_path,
            [
                {
                    "chunks": [
                        chunk({"role": "assistant"}),
                        *[chunk({"content": char}) for char in text],
                        chunk({}, "stop"),
                    ]
                }
            ],
        ),
    )
    try:
        with provider_scope(mask_only=True):
            events = [event async for event in provider.chat_stream(USER, stream_text=True)]
        visible = "".join(event.text for event in events if isinstance(event, ContentDelta))
        assert "an@example.test" not in visible
        assert "0912345678" not in visible
        assert "[[" not in visible
        assert "Select a PDF." in visible
        assert isinstance(events[-1], Done)
        assert events[-1].message["content"] == visible
    finally:
        await provider.aclose()
