"""Exercise real HTTP sessions and every existing resource access route."""

import hashlib
from functools import lru_cache
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.documents import Document

from src.db.database import SessionLocal, init_db
from src.db.models import AdvisorAssignment, GapAnalysis, InterviewSession, JobDescription, ShareGrant, User, utcnow
from src.main import app
from tests.helpers import make_docx


@lru_cache
def isolation_password_hash() -> str:
    salt = b"isolated-test-salt"
    digest = hashlib.scrypt(b"Isolation-dev-only!", salt=salt, n=32768, r=8, p=3, maxmem=67108864)
    return f"scrypt$32768$8$3${salt.hex()}${digest.hex()}"


async def login(client, email: str) -> dict[str, str]:
    client.cookies.clear()
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "Isolation-dev-only!"})
    assert response.status_code == 200, response.text
    cookie = {"Cookie": response.headers["set-cookie"].split(";", 1)[0]}
    client.cookies.clear()
    return cookie


@pytest_asyncio.fixture(scope="module")
async def isolation_client():
    init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(scope="module")
async def identities(isolation_client):
    client = isolation_client
    suffix = uuid4().hex[:12]
    ids = {role: f"isolation-{role}-{suffix}" for role in ("a", "b", "advisor")}
    emails = {key: f"{value}@example.test" for key, value in ids.items()}
    with SessionLocal() as db:
        for key, user_id in ids.items():
            db.add(
                User(
                    id=user_id,
                    email=emails[key],
                    role="advisor" if key == "advisor" else "student",
                    full_name=f"Individual {key}",
                    password_hash=isolation_password_hash(),
                )
            )
        db.flush()
        db.add(AdvisorAssignment(id=f"assignment-{suffix}", advisor_id=ids["advisor"], student_id=ids["a"]))
        db.commit()
    headers = {key: await login(client, email) for key, email in emails.items()}
    resources = {}
    for key in ("a", "b"):
        response = await client.post(
            "/api/v1/cv/upload",
            headers=headers[key],
            files={
                "file": (
                    f"{key}.docx",
                    make_docx(
                        [
                            f"PRIVATE-{key}-{suffix}",
                            "Python SQL projects: built and tested personal software applications.",
                        ]
                    ),
                )
            },
        )
        assert response.status_code == 201, response.text
        cv_id = response.json()["id"]
        jd_id, analysis_id = f"private-jd-{key}-{suffix}", f"analysis-{key}-{suffix}"
        with SessionLocal() as db:
            db.add(
                JobDescription(
                    id=jd_id,
                    source="pasted",
                    owner_id=ids[key],
                    title=f"PRIVATE-JD-{key}",
                    content=f"PRIVATE-JD-{key} Python",
                    skills=[],
                )
            )
            db.flush()
            db.add(
                GapAnalysis(
                    id=analysis_id,
                    owner_id=ids[key],
                    cv_version_id=cv_id,
                    cv_file_name=f"{key}.docx",
                    cv_label="v1.0",
                    jd_id=jd_id,
                    status="completed",
                    completed_at=utcnow(),
                    result={"requirements": [], "suggestions": [], "breakdown": []},
                )
            )
            db.commit()
        response = await client.post(
            "/api/v1/interviews", headers=headers[key], json={"jd_id": jd_id, "cv_version_id": cv_id}
        )
        assert response.status_code == 201, response.text
        session_id = response.json()["id"]
        with SessionLocal() as db:
            session = db.get(InterviewSession, session_id)
            session.status = "completed"
            session.completed_at = utcnow()
            session.question_deadline = None
            session.overall_score = 3.0
            session.star = dict.fromkeys(("situation", "task", "action", "result"), 3.0)
            db.add_all(
                [
                    ShareGrant(id=f"share-cv-{key}-{suffix}", owner_id=ids[key], kind="cv", item_id=cv_id),
                    ShareGrant(
                        id=f"share-interview-{key}-{suffix}", owner_id=ids[key], kind="interview", item_id=session_id
                    ),
                ]
            )
            db.commit()
        resources[key] = {"cv": cv_id, "jd": jd_id, "analysis": analysis_id, "interview": session_id}
    return ids, headers, resources


# All identifier-bearing student endpoints. Unknown foreign IDs must reveal no content
# and mutations must fail before any work. JD compare retains its existing public 403.
STUDENT_CASES = [
    ("GET", "/cv/{cv}/versions", None, 404),
    ("GET", "/cv/{cv}/text", None, 404),
    ("GET", "/cv/{cv}/file", None, 404),
    ("POST", "/cv/{cv}/export", {"format": "text", "integrity_confirmed": True}, 404),
    ("POST", "/cv/{cv}/restore", None, 404),
    ("POST", "/cv/{cv}/activate", None, 404),
    ("DELETE", "/cv/{cv}", None, 404),
    ("GET", "/gap-analysis/{analysis}", None, 404),
    ("GET", "/gap-analysis/{analysis}/optimizer", None, 404),
    ("POST", "/gap-analysis/{analysis}/optimizer/finalize", None, 404),
    ("POST", "/gap-analysis/{analysis}/optimizer/suggestions/unknown", {"decision": "reject"}, 404),
    ("POST", "/gap-analysis/{analysis}/optimizer/capability-checks/unknown", {"has_experience": False}, 404),
    ("GET", "/interviews/{interview}", None, 404),
    ("GET", "/interviews/{interview}/report", None, 404),
    ("POST", "/interviews/{interview}/pause", None, 404),
    ("POST", "/interviews/{interview}/resume", None, 404),
    (
        "POST",
        "/interviews/{interview}/answers",
        {"question_index": 1, "text": "My private interview answer with enough characters."},
        404,
    ),
    ("DELETE", "/interviews/{interview}", None, 404),
    ("GET", "/interviews/quota?jd_id={jd}", None, 404),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("caller,target", [("a", "b"), ("b", "a")])
@pytest.mark.parametrize("method,path,body,status", STUDENT_CASES)
async def test_foreign_resources_are_inaccessible(client, identities, caller, target, method, path, body, status):
    _, headers, resources = identities
    response = await client.request(
        method,
        f"/api/v1{path.format(**resources[target])}",
        json=body,
        headers={**headers[caller], "X-Demo-Role": "advisor"},
    )
    assert response.status_code == status, response.text
    assert "PRIVATE-" not in response.text


@pytest.mark.asyncio
async def test_students_see_only_their_own_lists_and_documents(client, identities):
    ids, headers, resources = identities
    for key, other in (("a", "b"), ("b", "a")):
        assert (await client.get("/api/v1/me", headers=headers[key])).json()["id"] == ids[key]
        for endpoint, foreign in (
            ("cv", resources[other]["cv"]),
            ("jd", resources[other]["jd"]),
            ("interviews", resources[other]["interview"]),
        ):
            response = await client.get(f"/api/v1/{endpoint}", headers=headers[key])
            assert response.status_code == 200
            assert foreign not in {item["id"] for item in response.json()}
        for path in (
            "/cv/{cv}/text",
            "/cv/{cv}/file",
            "/cv/{cv}/versions",
            "/gap-analysis/{analysis}",
            "/gap-analysis/{analysis}/optimizer",
            "/interviews/{interview}",
            "/interviews/{interview}/report",
        ):
            response = await client.get(f"/api/v1{path.format(**resources[key])}", headers=headers[key])
            assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/gap-analysis", "/interviews", "/jd/compare", "/gap-analysis/compare", "/jd/recommend"]
)
async def test_foreign_cv_or_jd_cannot_be_used(client, identities, path):
    _, headers, resources = identities
    for kind in ("cv", "jd"):
        body = {
            "cv_version_id": resources["b" if kind == "cv" else "a"]["cv"],
            "jd_id": resources["b" if kind == "jd" else "a"]["jd"],
        }
        if "compare" in path:
            body = {"cv_version_id": body["cv_version_id"], "jd_ids": [body["jd_id"], "jd-da-intern"]}
        if path == "/jd/recommend":
            if kind == "jd":
                continue  # This endpoint accepts no JD identity.
            body = {"cv_version_id": body["cv_version_id"], "generate_advice": False}
        response = await client.post(f"/api/v1{path}", json=body, headers=headers["a"])
        assert response.status_code in (403, 404), response.text
        assert "PRIVATE-" not in response.text


@pytest.mark.asyncio
async def test_recommendations_cannot_leak_private_vector_candidates(client, identities, monkeypatch):
    _, headers, resources = identities
    candidates = [
        (Document(page_content="PRIVATE-JD-b", metadata={"jd_id": resources["b"]["jd"], "title": "PRIVATE-JD-b"}), 0.9)
    ]
    from src.services import jd_recommendation

    class Store:
        def search_candidates(self, **kwargs):
            return candidates

    monkeypatch.setattr(jd_recommendation, "get_jd_store", lambda: Store())
    response = await client.post(
        "/api/v1/jd/recommend",
        headers=headers["a"],
        json={"cv_version_id": resources["a"]["cv"], "generate_advice": False},
    )
    assert response.status_code == 200, response.text
    # Gợi ý chấm cả thư viện JD công khai; JD riêng của người khác (ứng viên từ kho vector) không được lọt vào
    assert all(r["jd_id"] != resources["b"]["jd"] for r in response.json()["recommendations"])
    assert "PRIVATE-" not in response.text


ADVISOR_PATHS = [
    "/advisor/students/{student}",
    "/advisor/students/{student}/progress",
    "/advisor/students/{student}/cvs/{cv}/text",
    "/advisor/students/{student}/cvs/{cv}/file",
    "/advisor/students/{student}/interviews/{interview}",
    "/conversations/{student}",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ADVISOR_PATHS)
async def test_advisor_access_requires_live_assignment(client, identities, path):
    ids, headers, resources = identities
    allowed = path.format(student=ids["a"], **resources["a"])
    denied = path.format(student=ids["b"], **resources["b"])
    assert (await client.get(f"/api/v1{allowed}", headers=headers["advisor"])).status_code == 200
    response = await client.get(f"/api/v1{denied}", headers=headers["advisor"])
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        assignment = db.query(AdvisorAssignment).filter_by(student_id=ids["a"]).one()
        db.delete(assignment)
        db.commit()
    try:
        assert (await client.get(f"/api/v1{allowed}", headers=headers["advisor"])).status_code == 403
    finally:
        with SessionLocal() as db:
            db.add(AdvisorAssignment(id=f"restored-{uuid4().hex}", advisor_id=ids["advisor"], student_id=ids["a"]))
            db.commit()


@pytest.mark.asyncio
async def test_advisor_list_and_student_role_cannot_escalate(client, identities):
    ids, headers, _ = identities
    response = await client.get("/api/v1/advisor/students", headers=headers["advisor"])
    assert {student["id"] for student in response.json()} == {ids["a"]}
    response = await client.get("/api/v1/advisor/students", headers={**headers["a"], "X-Demo-Role": "advisor"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_advisor_cannot_substitute_foreign_resources_under_assigned_student(client, identities):
    ids, headers, resources = identities
    for path in ("/cvs/{cv}/text", "/cvs/{cv}/file", "/interviews/{interview}"):
        response = await client.get(
            f"/api/v1/advisor/students/{ids['a']}{path.format(**resources['b'])}", headers=headers["advisor"]
        )
        assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_assistant_context_cannot_select_client_identity(client, identities):
    ids, headers, _ = identities
    body = {
        "message": "Xin chào",
        "context": {
            "current_url": "http://localhost:3000/student/cv",
            "route": "/student/cv",
            "user_role": "student",
            "user_id": ids["b"],
        },
    }
    response = await client.post("/api/v1/assistant/chat", json=body, headers=headers["a"])
    assert response.status_code == 403, response.text
    body["context"].update(
        user_id=ids["a"], user_role="advisor", route="/advisor", current_url="http://localhost:3000/advisor"
    )
    response = await client.post("/api/v1/assistant/chat", json=body, headers=headers["a"])
    assert response.status_code == 403, response.text
