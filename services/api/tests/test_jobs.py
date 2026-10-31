# ruff: noqa: F811
from app import jobs
from tests.test_rbac import auth, env  # noqa: F401
from tests.test_uploads import reserve, upload_ok, world  # noqa: F401


def test_index_job_processes_the_waiting_queue(world):
    w = world
    upload_ok(w, w.emp)
    with w.engine.begin() as c:  # put it back in the queue, as a crashed worker would leave it
        c.exec_driver_sql(
            "UPDATE document_search SET extraction_status='pending', content_tsv=NULL"
        )
    counts = w.client.get("/api/v1/search/index/status", headers=w.admin).json()["counts"]
    waiting = counts.get("pending", 0)
    assert waiting == 1
    totals = jobs.run(["index-content"], engine=w.engine, storage=w.storage)
    assert totals["tenants"] >= 1 and totals["indexed"] + totals["index_failed"] == waiting
    counts = w.client.get("/api/v1/search/index/status", headers=w.admin).json()["counts"]
    assert counts.get("pending", 0) == 0
    again = jobs.run(["index-content"], engine=w.engine, storage=w.storage)
    assert again["indexed"] == 0 and again["index_failed"] == 0


def test_expire_job_abandons_unfinished_reservations(world):
    w = world
    r = reserve(w, w.emp, filename="late.txt", content_type="text/plain", size_bytes=5)
    assert r.status_code == 201
    with w.engine.begin() as c:
        c.exec_driver_sql("UPDATE document_versions SET expires_at = now() - interval '1 hour'")
    totals = jobs.run(["expire-uploads"], engine=w.engine, storage=w.storage)
    assert totals["abandoned"] == 1 and totals["delete_failures"] == 0
    assert jobs.run(["expire-uploads"], engine=w.engine, storage=w.storage)["abandoned"] == 0
    with w.engine.begin() as c:
        status = c.exec_driver_sql("SELECT status FROM document_versions").scalar()
    assert status == "abandoned"


def test_command_line_rejects_unknown_jobs(capsys):
    assert jobs.main(["nonsense"]) == 2
    assert jobs.main([]) == 2
    assert "usage" in capsys.readouterr().err
