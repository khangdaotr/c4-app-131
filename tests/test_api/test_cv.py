import uuid

import pytest
from sqlalchemy import delete, select

from src.db.database import SessionLocal, init_db
from src.db.models import CvVersion, GapAnalysis, ShareGrant, utcnow
from src.db.seed import DEMO_STUDENT_ID
from src.services import cv_files, cv_versions
from src.services.cv_files import CV_MAX_BYTES, _split_diacritics
from tests.helpers import ADVISOR, STUDENT, make_docx, make_image, make_pdf, make_scanned_pdf, upload_cv

CV_TEXT = "Nguyen Minh Anh - Python FastAPI Docker SQL developer with REST API and data pipeline experience"


def upload(client, name: str, data: bytes, headers=STUDENT):
    return upload_cv(client, name, data, headers)


@pytest.fixture(autouse=True)
def clean_cvs():
    init_db()
    with SessionLocal() as db:
        for model in (ShareGrant, GapAnalysis, CvVersion):
            db.execute(delete(model))
        db.commit()


def add_optimized(base_id: str) -> str:
    """Một bản tối ưu của CV chứa base_id (như "Hoàn tất" ở Trình tối ưu)."""
    with SessionLocal() as db:
        base = db.get(CvVersion, base_id)
        cv = CvVersion(
            id=f"cv_{uuid.uuid4().hex[:8]}",
            owner_id=base.owner_id,
            file_name="cv_toi_uu.docx",
            file_type="docx",
            size_bytes=4,
            content_text=CV_TEXT,
            origin="optimized",
            uploaded_at=utcnow(),
        )
        cv_versions.append(db, base, cv, new_major=False)
        db.add(cv)
        db.commit()
        cv_files.save_file(cv.owner_id, cv.id, "docx", b"docx")
        return cv.id


@pytest.mark.asyncio
async def test_upload_creates_incrementing_versions_first_is_active(client):
    first = await upload(client, "cv_goc.pdf", make_pdf(CV_TEXT))
    assert first.status_code == 201
    data = first.json()
    assert data["version"] == 1
    assert data["label"] == "v1.0"
    assert data["file_type"] == "pdf"
    assert data["page_count"] == 1
    assert data["read_by_ocr"] is False
    assert data["is_active"] is True
    assert data["status"] == "ready"
    assert data["uploaded_at"].endswith("+00:00")

    second = await upload(client, "cv_moi.docx", make_docx(CV_TEXT.split(" - ")))
    assert second.status_code == 201
    # Mỗi file tải lên là một CV mới, bắt đầu từ v1.0
    assert second.json()["version"] == 2 and second.json()["label"] == "v1.0"
    assert second.json()["family_id"] == second.json()["id"] != data["family_id"]
    assert second.json()["is_active"] is False
    assert second.json()["page_count"] is None

    listed = (await client.get("/api/v1/cv", headers=STUDENT)).json()
    assert [cv["version"] for cv in listed] == [2, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("cv.txt", b"plain text", 415, "unsupported_file_type"),
        ("cv.pdf", b"x" * (CV_MAX_BYTES + 1), 413, "file_too_large"),
        ("scan.pdf", make_pdf(None), 422, "cv_not_extractable"),
        ("hong.pdf", b"%PDF-1.4 not really a pdf", 422, "cv_not_extractable"),
    ],
    ids=["wrong-type", "too-large", "scanned-pdf", "corrupted-pdf"],
)
async def test_upload_rejects_invalid_files_without_creating_version(client, name, data, status, code):
    response = await upload(client, name, data)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert (await client.get("/api/v1/cv", headers=STUDENT)).json() == []


@pytest.mark.asyncio
async def test_activate_switches_active_version(client):
    first = (await upload(client, "a.pdf", make_pdf(CV_TEXT))).json()
    second = (await upload(client, "b.pdf", make_pdf(CV_TEXT))).json()

    response = await client.post(f"/api/v1/cv/{second['id']}/activate", headers=STUDENT)
    assert response.status_code == 200
    active = {cv["id"]: cv["is_active"] for cv in (await client.get("/api/v1/cv", headers=STUDENT)).json()}
    assert active == {first["id"]: False, second["id"]: True}


@pytest.mark.asyncio
async def test_delete_rules(client):
    active = (await upload(client, "a.pdf", make_pdf(CV_TEXT))).json()
    other = (await upload(client, "b.pdf", make_pdf(CV_TEXT))).json()

    blocked = await client.delete(f"/api/v1/cv/{active['id']}", headers=STUDENT)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "cv_active"

    assert (await client.delete(f"/api/v1/cv/{other['id']}", headers=STUDENT)).status_code == 204
    # CV đang dùng xoá được khi là phiên bản duy nhất còn lại
    assert (await client.delete(f"/api/v1/cv/{active['id']}", headers=STUDENT)).status_code == 204
    assert (await client.get("/api/v1/cv", headers=STUDENT)).json() == []


@pytest.mark.asyncio
async def test_history_and_restore(client):
    pdf = make_pdf(CV_TEXT)
    root = (await upload(client, "cv.pdf", pdf)).json()
    other = (await upload(client, "khac.pdf", make_pdf(CV_TEXT))).json()
    v11, v12 = add_optimized(root["id"]), add_optimized(root["id"])

    history = (await client.get(f"/api/v1/cv/{root['id']}/versions", headers=STUDENT)).json()
    assert [(v["id"], v["label"]) for v in history] == [(v12, "v1.2"), (v11, "v1.1"), (root["id"], "v1.0")]
    # CV đang dùng: bản tối ưu mới nhất tự thành bản đang dùng
    assert [v["is_active"] for v in history] == [True, False, False]

    res = await client.post(f"/api/v1/cv/{root['id']}/restore", headers=STUDENT)
    assert res.status_code == 201
    restored = res.json()
    assert (restored["label"], restored["origin"], restored["restored_from_label"]) == ("v2.0", "restored", "v1.0")
    assert restored["family_id"] == root["id"] and restored["is_active"] is True and restored["version_count"] == 4
    assert (await client.get(f"/api/v1/cv/{restored['id']}/file", headers=STUDENT)).content == pdf

    # Không xoá bản nào; "CV của tôi" vẫn hai CV, CV vừa khôi phục đứng trước
    cvs = (await client.get("/api/v1/cv", headers=STUDENT)).json()
    assert [(c["id"], c["label"], c["version_count"]) for c in cvs] == [
        (restored["id"], "v2.0", 4),
        (other["id"], "v1.0", 1),
    ]

    # Tối ưu tiếp sau khi khôi phục: tăng số phụ trên nền bản khôi phục
    v21 = add_optimized(v11)
    history = (await client.get(f"/api/v1/cv/{v21}/versions", headers=STUDENT)).json()
    assert [v["label"] for v in history] == ["v2.1", "v2.0", "v1.2", "v1.1", "v1.0"]

    current = await client.post(f"/api/v1/cv/{v21}/restore", headers=STUDENT)
    assert current.status_code == 409 and current.json()["code"] == "cv_already_current"


@pytest.mark.asyncio
async def test_activate_uses_latest_version_of_cv(client):
    first = (await upload(client, "a.pdf", make_pdf(CV_TEXT))).json()
    second = (await upload(client, "b.pdf", make_pdf(CV_TEXT))).json()
    newest = add_optimized(second["id"])
    # CV chưa dùng thì bản tối ưu không tự thành bản đang dùng
    listed = (await client.get("/api/v1/cv", headers=STUDENT)).json()
    assert {c["id"]: c["is_active"] for c in listed} == {newest: False, first["id"]: True}

    res = await client.post(f"/api/v1/cv/{second['id']}/activate", headers=STUDENT)
    assert res.status_code == 200 and res.json()["id"] == newest and res.json()["is_active"] is True
    listed = (await client.get("/api/v1/cv", headers=STUDENT)).json()
    assert {c["id"]: c["is_active"] for c in listed} == {newest: True, first["id"]: False}


@pytest.mark.asyncio
async def test_delete_removes_all_versions_of_cv(client):
    kept = (await upload(client, "a.pdf", make_pdf(CV_TEXT))).json()
    other = (await upload(client, "b.pdf", make_pdf(CV_TEXT))).json()
    newest = add_optimized(other["id"])

    assert (await client.delete(f"/api/v1/cv/{other['id']}", headers=STUDENT)).status_code == 204
    assert [c["id"] for c in (await client.get("/api/v1/cv", headers=STUDENT)).json()] == [kept["id"]]
    assert (await client.get(f"/api/v1/cv/{newest}/file", headers=STUDENT)).status_code == 404
    assert not cv_files.stored_path(DEMO_STUDENT_ID, newest, "docx").exists()


def legacy_analysis(analysis_id: str, cv_id: str, cv_label: str) -> GapAnalysis:
    return GapAnalysis(
        id=analysis_id,
        owner_id=DEMO_STUDENT_ID,
        cv_version_id=cv_id,
        cv_file_name="goc.pdf",
        cv_label=cv_label,
        jd_id="jd-ba-intern",
        status="completed",
        current_step=None,
        match_score=60.0,
        result={},
        completed_at=utcnow(),
    )


@pytest.mark.asyncio
async def test_backfill_groups_versions_created_before_cv_history(client):
    """DB cũ: mỗi phiên bản là một dòng riêng (nhãn vN.0). Khởi động lại thì bản tối ưu về chung CV với bản gốc."""
    root = (await upload(client, "goc.pdf", make_pdf(CV_TEXT))).json()["id"]
    other = (await upload(client, "khac.pdf", make_pdf(CV_TEXT))).json()["id"]
    with SessionLocal() as db:
        for cv in db.scalars(select(CvVersion)):
            cv.family_id = cv.major = cv.minor = None
        db.add(legacy_analysis("ga_cu", root, "v1.0"))
        db.add(
            CvVersion(
                id="cv_toi_uu_cu",
                owner_id=DEMO_STUDENT_ID,
                version=3,
                file_name="goc_v3.docx",
                file_type="docx",
                size_bytes=4,
                content_text=CV_TEXT,
                origin="optimized",
                source_analysis_id="ga_cu",
                uploaded_at=utcnow(),
            )
        )
        db.add(legacy_analysis("ga_moi", "cv_toi_uu_cu", "v3.0"))
        # Quyền chia sẻ cũ gắn với từng phiên bản
        db.add(ShareGrant(id="sh_goc", owner_id=DEMO_STUDENT_ID, kind="cv", item_id=root))
        db.add(ShareGrant(id="sh_toi_uu", owner_id=DEMO_STUDENT_ID, kind="cv", item_id="cv_toi_uu_cu"))
        db.commit()

    init_db()
    cvs = {c["id"]: c for c in (await client.get("/api/v1/cv", headers=STUDENT)).json()}
    assert {cid: (c["label"], c["version_count"]) for cid, c in cvs.items()} == {
        "cv_toi_uu_cu": ("v1.1", 2),
        other: ("v1.0", 1),
    }
    # Bản gốc đang dùng nên bản mới nhất của CV đó thành bản đang dùng
    assert cvs["cv_toi_uu_cu"]["is_active"] is True and cvs[other]["is_active"] is False
    with SessionLocal() as db:
        assert db.get(GapAnalysis, "ga_moi").cv_label == "v1.1"
        assert [g.item_id for g in db.scalars(select(ShareGrant))] == [root]


@pytest.mark.asyncio
async def test_file_and_text_preview(client):
    pdf = make_pdf(CV_TEXT)
    cv = (await upload(client, "cv.pdf", pdf)).json()

    file_response = await client.get(f"/api/v1/cv/{cv['id']}/file", headers=STUDENT)
    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "application/pdf"
    assert file_response.headers["content-disposition"].startswith("inline")
    assert file_response.content == pdf

    text_response = await client.get(f"/api/v1/cv/{cv['id']}/text", headers=STUDENT)
    assert "FastAPI" in text_response.json()["text"]


@pytest.mark.asyncio
async def test_in_app_preview_pages_for_pdf_and_template_for_docx(client):
    """Xem CV trong app: PDF → ảnh từng trang (không dùng trình xem PDF của trình duyệt); DOCX → mẫu CV."""
    cv = (await upload(client, "cv.pdf", make_pdf(CV_TEXT))).json()
    preview = (await client.get(f"/api/v1/cv/{cv['id']}/preview", headers=STUDENT)).json()
    assert preview["kind"] == "pages" and preview["page_count"] == 1 and preview["document"] is None
    page = await client.get(f"/api/v1/cv/{cv['id']}/pages/1", headers=STUDENT)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert page.content.startswith(b"\x89PNG")
    assert page.headers["cache-control"] == "private, max-age=3600"
    missing = await client.get(f"/api/v1/cv/{cv['id']}/pages/2", headers=STUDENT)
    assert missing.status_code == 404 and missing.json()["code"] == "cv_page_not_found"
    assert missing.headers["cache-control"] == "no-store"

    docx = (await upload(client, "cv.docx", make_docx(["Nguyễn Minh Anh", "KỸ NĂNG", CV_TEXT]))).json()
    preview = (await client.get(f"/api/v1/cv/{docx['id']}/preview", headers=STUDENT)).json()
    assert preview["kind"] == "document" and preview["page_count"] is None
    assert preview["document"]["header"][0]["text"] == "Nguyễn Minh Anh"
    assert preview["document"]["header"][0]["kind"] == "name"
    no_pages = await client.get(f"/api/v1/cv/{docx['id']}/pages/1", headers=STUDENT)
    assert no_pages.status_code == 404


@pytest.mark.asyncio
async def test_advisor_cannot_use_student_cv_endpoints(client):
    response = await client.get("/api/v1/cv", headers=ADVISOR)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_unknown_cv_is_not_found(client):
    response = await client.post("/api/v1/cv/cv_khong_ton_tai/activate", headers=STUDENT)
    assert response.status_code == 404
    assert response.json()["code"] == "cv_not_found"


def test_restored_file_name_follows_new_label():
    assert cv_versions.restored_file_name("CV_MinhAnh_v1.1.docx", "v3.0") == "CV_MinhAnh_v3.0.docx"
    # File SV tự đặt tên (không có hậu tố phiên bản) giữ nguyên tên
    assert cv_versions.restored_file_name("CV_MinhAnh.pdf", "v2.0") == "CV_MinhAnh.pdf"


def test_detects_pdf_text_with_split_vietnamese_letters():
    """PDF xuất từ Chrome: chữ có dấu nằm ở font dự phòng, cách trích thường chèn khoảng trắng quanh chữ đó."""
    broken = (
        "PH Ạ M MINH NH Ậ T\nHà N ộ i, Vi ệ t Nam\nJunior Web Developer có n ề n t ả ng v ề  HTML ở  m ứ c c ơ  b ả n"
    )
    normal = (
        "Phạm Minh Nhật\nHà Nội, Việt Nam\nJunior Web Developer có nền tảng về HTML ở mức cơ bản, đã tham gia dự án"
    )
    assert _split_diacritics(broken) is True
    assert _split_diacritics(normal) is False


@pytest.mark.asyncio
async def test_upload_scanned_pdf_triggers_ocr(client):
    """PDF scan (chỉ có ảnh, không có text layer) được OCR tự động trích xuất nội dung."""
    scanned_data = make_scanned_pdf(CV_TEXT)
    res = await upload(client, "scanned_cv.pdf", scanned_data)
    assert res.status_code == 201
    data = res.json()
    assert data["file_type"] == "pdf"
    assert data["page_count"] == 1
    assert data["status"] == "ready"
    assert data["read_by_ocr"] is True

    # Kiểm tra nội dung trích xuất qua text endpoint
    text_res = await client.get(f"/api/v1/cv/{data['id']}/text", headers=STUDENT)
    assert text_res.status_code == 200
    assert "Python" in text_res.json()["text"]

    # Cờ "đọc bằng OCR" được lưu lại (Trình tối ưu dùng để nhắc sinh viên kiểm tra chữ), PDF có chữ thì không
    listed = {c["id"]: c for c in (await client.get("/api/v1/cv", headers=STUDENT)).json()}
    assert listed[data["id"]]["read_by_ocr"] is True
    text_pdf = (await upload(client, "text_cv.pdf", make_pdf(CV_TEXT))).json()
    assert text_pdf["read_by_ocr"] is False


def test_backfill_ocr_flags_for_old_versions():
    """CV tạo trước khi có cờ: PDF không có lớp chữ là bản OCR, bản khôi phục theo bản gốc, DOCX thì không."""
    from src.services.cv_versions import backfill_ocr_flags

    with SessionLocal() as db:
        scan = CvVersion(
            id="cv_scan_cu",
            owner_id=DEMO_STUDENT_ID,
            version=901,
            file_name="scan.pdf",
            file_type="pdf",
            size_bytes=1,
            content_text=CV_TEXT,
            uploaded_at=utcnow(),
            read_by_ocr=None,
        )
        restored = CvVersion(
            id="cv_scan_khoi_phuc",
            owner_id=DEMO_STUDENT_ID,
            version=902,
            file_name="scan_v2.pdf",
            file_type="pdf",
            size_bytes=1,
            content_text=CV_TEXT,
            origin="restored",
            restored_from_id="cv_scan_cu",
            uploaded_at=utcnow(),
            read_by_ocr=None,
        )
        docx = CvVersion(
            id="cv_docx_cu",
            owner_id=DEMO_STUDENT_ID,
            version=903,
            file_name="cv.docx",
            file_type="docx",
            size_bytes=1,
            content_text=CV_TEXT,
            uploaded_at=utcnow(),
            read_by_ocr=None,
        )
        db.add_all([scan, restored, docx])
        db.commit()
        cv_files.save_file(DEMO_STUDENT_ID, "cv_scan_cu", "pdf", make_scanned_pdf(CV_TEXT))
        try:
            backfill_ocr_flags(db)
            assert (scan.read_by_ocr, restored.read_by_ocr, docx.read_by_ocr) == (True, True, False)
        finally:
            cv_files.delete_file(DEMO_STUDENT_ID, "cv_scan_cu", "pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize("name, fmt", [("my_cv.png", "PNG"), ("my_cv.jpg", "JPEG")])
async def test_upload_image_cv_is_rejected(client, name, fmt):
    """Chỉ nhận PDF / DOCX; ảnh chụp CV hãy lưu thành PDF (PDF scan vẫn được OCR)."""
    res = await upload(client, name, make_image(CV_TEXT, fmt=fmt))
    assert res.status_code == 415
    assert res.json()["code"] == "unsupported_file_type"


@pytest.mark.asyncio
async def test_upload_blank_scanned_pdf_fails_extractable(client):
    """PDF scan trắng, OCR không đọc được chữ, bị từ chối với lỗi cv_not_extractable."""
    res = await upload(client, "blank_scan.pdf", make_scanned_pdf(None))
    assert res.status_code == 422
    assert res.json()["code"] == "cv_not_extractable"
