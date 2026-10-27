import io
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select

from app.material_extract import extract_job
from app.models import Material, MaterialFile, MaterialVersion

SOURCE = "姓名：张三\n学校：示例大学\n专业：计算机\n项目名称：求职助手\n个人职责：负责API\n项目内容：处理上传\n项目成果：完成测试\n专业技能：Python、MySQL"
JD = "岗位名称：后端开发工程师\n岗位方向：Python\n公司名称：示例公司\n岗位职责：开发API\n任职要求：掌握Python、MySQL"
SOURCE_BYTES = SOURCE.encode()


def upload(h, headers, content=SOURCE_BYTES, filename="resume.txt", key="upload-test-key-001", **params):
    return h.client.post("/api/v1/materials/resumes", params={"filename": filename, **params},
                         content=content, headers={**headers, "Idempotency-Key": key,
                                                   "Content-Type": "application/octet-stream"})


def setup(h):
    h.register()
    return h.login()


def test_resume_extract_confirm_version_rename_delete_and_original(h):
    headers = setup(h)
    response = upload(h, headers)
    assert response.status_code == 201, response.text
    row = response.json()["material"]
    assert row["fields"]["name"] == "张三"
    assert row["fields"]["projects"][0]["name"] == "求职助手"
    assert row["source"] == SOURCE and row["status"] == "pending"
    path = f'/api/v1/materials/resumes/{row["id"]}'
    original = h.client.get(path + "/file")
    assert original.content == SOURCE.encode()
    assert "attachment" in original.headers["content-disposition"]
    confirmed = h.client.put(path, json={"revision": row["revision"], "fields": row["fields"]}, headers=headers)
    assert confirmed.status_code == 200
    row = confirmed.json()["material"]
    assert row["version"] == 1 and row["status"] == "confirmed"
    assert row["projects"] == 1 and row["skills"] == ["Python", "MySQL"]
    first = h.client.get(path + "/versions").json()["items"][0]
    fields = row["fields"]
    fields["projects"] = []
    fields["skills"] = ""
    changed = h.client.put(path, json={"revision": row["revision"], "fields": fields}, headers=headers).json()["material"]
    assert changed["version"] == 2 and changed["projects"] == 0 and changed["skills"] == []
    assert h.client.get(path + "/versions").json()["items"][0] == first
    repeat = h.client.put(path, json={"revision": changed["revision"], "fields": fields}, headers=headers).json()["material"]
    assert repeat["version"] == 2
    rename = h.client.patch(path, json={"revision": repeat["revision"], "title": "校招简历"}, headers=headers).json()["material"]
    assert rename["title"] == "校招简历" and rename["version"] == 2
    assert h.client.request("DELETE", path, json={"revision": rename["revision"]}, headers=headers).status_code == 200
    assert h.client.get(path + "/file").status_code == 404
    assert h.client.get("/api/v1/materials/resumes").json()["total"] == 0
    with h.app.state.session_factory() as db:
        assert len(list(db.scalars(select(MaterialVersion)))) == 2
        assert len(list(db.scalars(select(MaterialFile)))) == 1


def test_empty_fields_conflict_and_upload_idempotency(h):
    headers = setup(h)
    first = upload(h, headers).json()["material"]
    assert upload(h, headers).json()["material"]["id"] == first["id"]
    assert upload(h, headers, b"different").status_code == 409
    path = f'/api/v1/materials/resumes/{first["id"]}'
    assert h.client.put(path, json={"revision": 1, "fields": {}}, headers=headers).status_code == 422
    assert h.client.put(path, json={"revision": 99, "fields": first["fields"]}, headers=headers).status_code == 409
    assert h.client.get("/api/v1/materials/resumes").json()["total"] == 1
    assert len(list(h.app.state.settings.material_directory.iterdir())) == 1


@pytest.mark.parametrize(("filename", "data", "status"), [
    ("a.txt", b"", 422), ("a.exe", b"x", 415), ("a.pdf", b"not-a-pdf", 415),
    ("a.docx", b"not-a-zip", 415), ("a.txt", b"\x00\x01", 415), ("../a.txt", b"x", 422),
])
def test_upload_rejects_invalid_files_without_orphans(h, filename, data, status):
    response = upload(h, setup(h), data, filename)
    assert response.status_code == status
    with h.app.state.session_factory() as db:
        assert not db.scalar(select(Material))
        assert not db.scalar(select(MaterialFile))
    root = h.app.state.settings.material_directory
    assert not root.exists() or not list(root.iterdir())


def test_size_boundary_and_csrf(h):
    headers = setup(h)
    h.app.state.settings.material_max_bytes = 1024
    assert upload(h, headers, b"x" * 1025).status_code == 413
    assert upload(h, {}, b"x").status_code == 403
    h.client.cookies.clear()
    assert upload(h, headers).status_code == 401


def test_blank_pdf_has_failed_state_and_replacement_keeps_identity(h):
    headers = setup(h)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    blob = io.BytesIO()
    writer.write(blob)
    row = upload(h, headers, blob.getvalue(), "scan.pdf").json()["material"]
    assert row["status"] == "failed" and row["errorCode"] == "NO_TEXT"
    replaced = upload(h, headers, replace_id=row["id"], revision=row["revision"]).json()["material"]
    assert replaced["id"] == row["id"] and replaced["status"] == "pending"
    assert h.client.get("/api/v1/materials/resumes").json()["total"] == 1


def test_pdf_text_is_extracted_and_encrypted_pdf_is_not_success(h):
    headers = setup(h)
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 250 Td (Actual resume source) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    blob = io.BytesIO()
    writer.write(blob)
    row = upload(h, headers, blob.getvalue(), "actual.pdf").json()["material"]
    assert "Actual resume source" in row["source"] and row["status"] == "pending"
    writer.encrypt("synthetic-test-password")
    encrypted = io.BytesIO()
    writer.write(encrypted)
    result = upload(h, headers, encrypted.getvalue(), "encrypted.pdf", "upload-test-key-003").json()["material"]
    assert result["status"] == "failed" and result["errorCode"] == "FILE_ENCRYPTED"


def docx(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def test_docx_unicode_extraction_and_zip_validation(h):
    headers = setup(h)
    row = upload(h, headers, docx("姓名：李四"), "中文.docx").json()["material"]
    assert row["source"] == "姓名：李四" and row["fields"]["name"] == "李四"
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("unrelated.txt", "hello")
    assert upload(h, headers, broken.getvalue(), "spoof.docx", "upload-test-key-002").status_code == 415


def test_small_compressed_pdf_cannot_expand_past_stream_limit(h):
    headers = setup(h)
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b" " * (9 * 1024 * 1024))
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    buffer = io.BytesIO()
    writer.write(buffer)
    assert len(buffer.getvalue()) < 20_000
    row = upload(h, headers, buffer.getvalue(), "compressed.pdf").json()["material"]
    assert row["status"] == "failed" and row["errorCode"] == "FILE_COMPLEX"


def test_jd_source_evidence_stale_analysis_and_immutable_versions(h):
    headers = setup(h)
    create = h.client.post("/api/v1/materials/jobs", json={"source": JD}, headers={**headers, "Idempotency-Key": "job-test-request-001"})
    assert create.status_code == 201
    row = create.json()["material"]
    assert row["role"] == "后端开发" and row["requirements"] == "掌握Python、MySQL"
    assert row["responsibilities"] == "开发API"
    assert row["inference"] == "" and row["useInference"] is False
    assert row["sourceEvidence"]["requirements"]["text"] in JD
    same = h.client.post("/api/v1/materials/jobs", json={"source": JD}, headers={**headers, "Idempotency-Key": "job-test-request-001"})
    assert same.json()["material"]["id"] == row["id"]
    path = f'/api/v1/materials/jobs/{row["id"]}'
    fields = {k: row[k] for k in extract_job(JD)}
    assert h.client.put(path, json={"revision": row["revision"], "source": JD + "changed", "fields": fields}, headers=headers).status_code == 409
    first = h.client.put(path, json={"revision": row["revision"], "source": JD, "fields": fields}, headers=headers).json()["material"]
    assert first["version"] == 1
    parsed = h.client.post(path + "/parse", json={"revision": first["revision"], "source": JD.replace("MySQL", "Redis")}, headers=headers).json()["material"]
    fields["requirements"] = "掌握Python、Redis"
    fields["inference"] = "用户补充的优先项"
    fields["useInference"] = False
    second = h.client.put(path, json={"revision": parsed["revision"], "source": parsed["source"], "fields": fields}, headers=headers).json()["material"]
    assert second["version"] == 2 and second["useInference"] is False
    versions = h.client.get(path + "/versions").json()["items"]
    assert "MySQL" in versions[0]["snapshot"]["source"]
    assert "Redis" in versions[1]["snapshot"]["source"]
    assert h.client.get("/api/v1/materials/jobs").json()["total"] == 1


def test_material_id_and_file_are_private_even_for_admin(h):
    headers = setup(h)
    row = upload(h, headers).json()["material"]
    h.make_admin()
    other = h.login("admin@example.org")
    path = f'/api/v1/materials/resumes/{row["id"]}'
    assert h.client.get("/api/v1/materials/resumes").json()["total"] == 0
    assert h.client.get(path + "/file").status_code == 404
    assert h.client.get(path + "/versions").status_code == 404
    assert h.client.patch(path, json={"revision": 1, "title": "x"}, headers=other).status_code == 404


def test_jd_missing_information_stays_blank_and_required_validation(h):
    headers = setup(h)
    row = h.client.post("/api/v1/materials/jobs", json={"source": "开发系统"}, headers={**headers, "Idempotency-Key": "job-test-request-002"}).json()["material"]
    assert not any(row[k] for k in ("name", "company", "role", "requirements", "inference"))
    path = f'/api/v1/materials/jobs/{row["id"]}'
    assert h.client.put(path, json={"revision": 1, "source": "开发系统", "fields": {}}, headers=headers).status_code == 422
    h.app.state.settings.jd_text_limit = 1000
    assert h.client.post(path + "/parse", json={"revision": 1, "source": "x" * 1001}, headers=headers).status_code == 422


def create_job(h, headers, source=JD):
    return h.client.post("/api/v1/materials/jobs", json={"source": source},
                         headers={**headers, "Idempotency-Key": "job-rename-request-001"}).json()["material"]


def test_job_rename_survives_refresh_reparse_and_save_without_changing_content_version(h):
    headers = setup(h)
    row = create_job(h, headers)
    path = f'/api/v1/materials/jobs/{row["id"]}'
    fields = {key: row[key] for key in extract_job(JD)}
    row = h.client.put(path, json={"revision": row["revision"], "source": JD,
                                  "fields": fields}, headers=headers).json()["material"]
    versions = h.client.get(path + "/versions").json()["items"]
    renamed = h.client.patch(path, json={"revision": row["revision"], "title": "  目标公司·后端实习  "},
                             headers=headers).json()["material"]
    assert renamed["title"] == "目标公司·后端实习"
    assert renamed["revision"] == row["revision"] + 1
    assert renamed["version"] == row["version"] and renamed["status"] == "confirmed"
    assert renamed["source"] == JD and renamed["name"] == fields["name"]
    assert h.client.get(path + "/versions").json()["items"] == versions
    assert h.client.get("/api/v1/materials/jobs").json()["items"][0]["title"] == renamed["title"]
    row = h.client.put(path, json={"revision": renamed["revision"], "source": JD,
                                  "fields": fields}, headers=headers).json()["material"]
    assert row["title"] == renamed["title"] and row["version"] == 1
    changed_source = JD.replace("后端开发工程师", "高级后端开发工程师")
    row = h.client.post(path + "/parse", json={"revision": row["revision"], "source": changed_source},
                        headers=headers).json()["material"]
    assert row["title"] == renamed["title"]
    fields["name"] = "高级后端开发工程师"
    row = h.client.put(path, json={"revision": row["revision"], "source": changed_source,
                                  "fields": fields}, headers=headers).json()["material"]
    assert row["title"] == renamed["title"] and row["version"] == 2
    assert h.client.get(path + "/versions").json()["items"][0] == versions[0]


def test_job_rename_checks_input_revision_csrf_and_owner(h):
    headers = setup(h)
    row = create_job(h, headers)
    path = f'/api/v1/materials/jobs/{row["id"]}'
    for title in ("  ", "x" * 181):
        assert h.client.patch(path, json={"revision": row["revision"], "title": title},
                              headers=headers).status_code == 422
    assert h.client.patch(path, json={"revision": 99, "title": "旧版本"}, headers=headers).status_code == 409
    assert h.client.patch(path, json={"revision": 1, "title": "缺少CSRF"}).status_code == 403
    h.make_admin()
    other = h.login("admin@example.org")
    assert h.client.patch(path, json={"revision": 1, "title": "越权"}, headers=other).status_code == 404
    h.client.cookies.clear()
    assert h.client.patch(path, json={"revision": 1, "title": "未登录"}, headers=headers).status_code == 401
    with h.app.state.session_factory() as db:
        assert db.get(Material, row["id"]).title == row["title"]


def test_manual_job_confirmation_fills_placeholder_title_and_follows_name_corrections(h):
    headers = setup(h)
    row = create_job(h, headers, "开发系统")
    assert row["title"] == "新增岗位 JD"
    path = f'/api/v1/materials/jobs/{row["id"]}'
    fields = {"name": "后端开发实习", "role": "后端开发", "direction": "Python", "requirements": "开发系统"}
    row = h.client.put(path, json={"revision": row["revision"], "source": row["source"],
                                  "fields": fields}, headers=headers).json()["material"]
    assert row["title"] == fields["name"] and row["version"] == 1
    fields["name"] = "后端开发校招"
    row = h.client.put(path, json={"revision": row["revision"], "source": row["source"],
                                  "fields": fields}, headers=headers).json()["material"]
    assert row["title"] == fields["name"] and row["version"] == 2
    fields["name"] = "后端开发" * 60
    row = h.client.put(path, json={"revision": row["revision"], "source": row["source"],
                                  "fields": fields}, headers=headers).json()["material"]
    assert row["title"] == fields["name"][:180] and row["name"] == fields["name"]


def test_model_organization_preserves_custom_job_title_and_late_results_are_stale(h):
    from app.material_ai import apply
    from app.models import GenerationJob, ModelSpend

    headers = setup(h)
    row = create_job(h, headers)
    path = f'/api/v1/materials/jobs/{row["id"]}'
    renamed = h.client.patch(path, json={"revision": row["revision"], "title": "收藏岗位"},
                             headers=headers).json()["material"]
    with h.app.state.session_factory() as db:
        material = db.get(Material, row["id"])
        job = GenerationJob(owner_id=material.owner_id, kind="material_parse", state="ready", step_key="rename-model",
                            input_snapshot={"material_id": row["id"], "revision": renamed["revision"]},
                            output={"fields": extract_job(JD)})
        db.add(job)
        db.commit()
        apply(db, job)
        db.commit()
        assert job.state == "succeeded"
        assert material.title == "收藏岗位"
        job = GenerationJob(owner_id=material.owner_id, kind="material_parse", state="ready", step_key="rename-late",
                            input_snapshot={"material_id": row["id"], "revision": material.revision - 1},
                            output={"fields": extract_job(JD)})
        db.add(job)
        db.commit()
        apply(db, job)
        db.commit()
        assert job.state == "stale" and material.title == "收藏岗位"
        assert not db.scalar(select(ModelSpend))
