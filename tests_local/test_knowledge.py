import json
from pathlib import Path
import time

import pytest
import yaml

from local_app.jobs import JobManager
from local_app.knowledge import KnowledgeBase


@pytest.fixture
def context(tmp_path):
    data, vault = tmp_path / "data", tmp_path / "vault"
    vault.mkdir()
    jobs = JobManager(data)
    kb = KnowledgeBase(data, jobs)
    yield kb, jobs, vault, data
    kb.close()
    jobs.close()


def test_installation_never_discovers_or_registers_a_vault(context):
    kb, jobs, vault, data = context
    assert kb.status()["scopes"] == []
    for value in ("", ".", "relative-vault"):
        with pytest.raises(ValueError):
            kb.prepare("text", value)
    assert list(vault.iterdir()) == []


def test_sessions_keep_distinct_destinations_and_authoritative_metadata(
    context, tmp_path
):
    kb, jobs, vault, data = context
    other = tmp_path / "other"
    other.mkdir()
    first = kb.prepare(
        "first", str(vault), "分类/技术", source_ref="original: true\nstatus: promoted"
    )
    second = kb.prepare("second", str(other), "分类")
    payload = "---\nstatus: promoted\nsource_ref: invented\n---\n# CON\n\nNotes"
    one = kb.finalize(first["prepare_id"], payload)
    two = kb.finalize(second["prepare_id"], payload)
    assert one["vault_id"] != two["vault_id"]
    assert Path(one["absolute_path"]).parent == vault / "分类" / "技术"
    assert Path(two["absolute_path"]).parent == other / "分类"
    metadata = yaml.safe_load(Path(one["absolute_path"]).read_text().split("---", 2)[1])
    assert metadata["status"] == "staged"
    assert metadata["source_ref"] == "original: true\nstatus: promoted"
    assert Path(one["absolute_path"]).name.startswith("笔记_CON-")
    assert kb.status()["scopes"] == []  # Saving did not authorize a scan.


def test_restart_and_duplicate_finalize_do_not_duplicate_or_overwrite(context):
    kb, jobs, vault, data = context
    prepared = kb.prepare("input", str(vault), "Inbox")
    restored = KnowledgeBase(data, jobs)
    first = restored.finalize(prepared["prepare_id"], "# Title\nBody")
    second = restored.finalize(prepared["prepare_id"], "# Title\nBody")
    assert first == second
    assert len(list(vault.rglob("*.md"))) == 1
    with pytest.raises(ValueError):
        restored.finalize(prepared["prepare_id"], "# Different\nBody")
    Path(first["absolute_path"]).write_text("user edited")
    with pytest.raises(ValueError):
        restored.finalize(prepared["prepare_id"], "# Title\nBody")
    assert Path(first["absolute_path"]).read_text() == "user edited"


def test_expiry_malformed_frontmatter_and_traversal_are_rejected(context, tmp_path):
    kb, jobs, vault, data = context
    for folder in ("../outside", ".obsidian", "a/../../b", "CON", "a|b"):
        with pytest.raises(ValueError):
            kb.prepare("input", str(vault), folder)
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        kb.prepare("input", str(vault), "linked/sub")
    prepared = kb.prepare("input", str(vault))
    with pytest.raises(ValueError):
        kb.finalize(prepared["prepare_id"], "---\n- scalar\n---\n# bad")
    path = data / "sessions" / f"{prepared['prepare_id']}.json"
    session = json.loads(path.read_text())
    session["created_at"] = time.time() - 3601
    path.write_text(json.dumps(session))
    with pytest.raises(ValueError, match="过期"):
        kb.finalize(prepared["prepare_id"], "# expired")
    assert list(vault.glob("*.md")) == []


def test_destination_cannot_turn_into_symlink_after_prepare(context, tmp_path):
    kb, jobs, vault, data = context
    prepared = kb.prepare("input", str(vault), "future")
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "future").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        kb.finalize(prepared["prepare_id"], "# title")
    assert list(outside.iterdir()) == []


def test_scope_registration_replaces_and_query_never_auto_registers(context):
    kb, jobs, vault, data = context
    assert kb.query("question", str(vault))["status"] == "not_indexed"
    initial = kb.start_index(
        str(vault), include_existing=True, include_dirs=["first"], auto_sync=False
    )
    newer = kb.start_index(str(vault), include_dirs=["second"], auto_sync=False)
    assert initial["scope_revision"] != newer["scope_revision"]
    scope = kb.status()["scopes"][0]
    assert scope["include_dirs"] == ["second"]
    assert scope["include_existing"] is False
    assert (
        kb._index_job(
            {"vault_id": initial["scope_id"], "revision": initial["scope_revision"]},
            lambda _: None,
        )["status"]
        == "superseded"
    )


def test_missing_semantic_features_are_actionable_without_importing_model(context):
    from local_app.indexing import default_embeddings
    from local_app.jobs import JobNotReady

    _, _, _, data = context
    with pytest.raises(JobNotReady):
        default_embeddings(data)


def test_background_sync_does_not_silently_retry_interrupted_work(context):
    kb, jobs, vault, data = context
    queued = kb.start_index(str(vault), auto_sync=True)
    path = data / "jobs" / f"{queued['job_id']}.json"
    persisted = json.loads(path.read_text())
    persisted["status"] = "running"
    path.write_text(json.dumps(persisted))
    restored_jobs = JobManager(data)
    restored = KnowledgeBase(data, restored_jobs)
    restored.SYNC_INTERVAL = 0.02
    restored.start_sync()
    try:
        time.sleep(0.08)
        assert len(restored_jobs.list()) == 1
        assert restored_jobs.get(queued["job_id"])["status"] == "interrupted"
    finally:
        restored.close()
        restored_jobs.close()


def _wait_job(jobs, identity):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = jobs.get(identity)
        if job["status"] in {"succeeded", "failed"}:
            assert job["status"] == "succeeded", job
            return job
        time.sleep(0.01)
    raise AssertionError("job did not complete")


@pytest.fixture
def indexed_context(tmp_path):
    pytest.importorskip("chromadb")

    class Embeddings:
        calls = 0

        def embed_documents(self, texts):
            self.calls += 1
            return [[1.0, 0.5, 0.2] for _ in texts]

        def embed_query(self, text):
            self.calls += 1
            return [1.0, 0.5, 0.2]

    data, vault = tmp_path / "data", tmp_path / "vault"
    vault.mkdir()
    (vault / "included").mkdir()
    source = vault / "included" / "source.md"
    source.write_text("---\nstatus: promoted\n---\n# Source\nalpha private fact")
    embedding = Embeddings()
    jobs = JobManager(data)
    kb = KnowledgeBase(data, jobs, lambda: embedding)
    jobs.register("query", lambda params, progress: kb.query(**params))
    index = kb.start_index(str(vault), include_existing=True, auto_sync=False)
    jobs.start()
    _wait_job(jobs, index["job_id"])
    yield kb, jobs, vault, data, source, embedding
    kb.close()
    jobs.close()


@pytest.mark.parametrize("mutation", ["demote", "delete", "edit", "shrink_scope"])
def test_completed_query_revalidated_before_get_job_delivery(indexed_context, mutation):
    kb, jobs, vault, data, source, embedding = indexed_context
    submitted = jobs.submit("query", {"question": "alpha", "vault_path": str(vault)})
    completed = _wait_job(jobs, submitted["job_id"])
    valid = kb.validate_job_result(jobs.get(submitted["job_id"]))
    assert valid["result"]["status"] == "ready"
    assert "_validation" not in valid["result"]
    assert valid["result"]["retrieved_chunks"][0]["sha256"]
    if mutation == "demote":
        source.write_text(
            source.read_text().replace("status: promoted", "status: staged")
        )
    elif mutation == "delete":
        source.unlink()
    elif mutation == "edit":
        source.write_text(source.read_text().replace("private fact", "changed fact"))
    else:
        kb.start_index(
            str(vault),
            include_existing=True,
            include_dirs=["different"],
            auto_sync=False,
        )
    before = embedding.calls
    delivery = kb.validate_job_result(jobs.get(submitted["job_id"]))
    assert embedding.calls == before
    assert delivery["result"]["status"] == "stale_result"
    assert delivery["result"]["retrieved_chunks"] == []
    assert delivery["result"]["prompt_for_host"] == ""
    assert "alpha private fact" not in json.dumps(delivery)
    retried_delivery = kb.validate_job_result(jobs.retry(submitted["job_id"]))
    assert retried_delivery["result"]["status"] == "stale_result"
    assert "alpha private fact" not in json.dumps(retried_delivery)
    assert completed["result"]["status"] == "ready"  # No mutation of stored history.


def test_restarted_query_job_is_checked_again_without_loading_embeddings(
    indexed_context,
):
    kb, jobs, vault, data, source, embedding = indexed_context
    submitted = jobs.submit("query", {"question": "alpha", "vault_path": str(vault)})
    _wait_job(jobs, submitted["job_id"])
    jobs.close()
    source.unlink()
    restored_jobs = JobManager(data)

    def forbidden():
        raise AssertionError("delivery validation must not load embeddings")

    restored = KnowledgeBase(data, restored_jobs, forbidden)
    try:
        result = restored.validate_job_result(restored_jobs.get(submitted["job_id"]))[
            "result"
        ]
        assert result["status"] == "stale_result"
        assert result["retrieved_chunks"] == []
    finally:
        restored.close()
        restored_jobs.close()


@pytest.mark.parametrize("mutation", ["demote", "delete", "edit"])
def test_correlation_target_revalidated_even_when_candidates_unchanged(
    indexed_context, mutation
):
    kb, jobs, vault, data, source, embedding = indexed_context
    target = vault / "target.md"
    target.write_text("---\nstatus: promoted\n---\n# Target\nalpha target")
    captured = kb.capture_correlation_target(str(vault), "target.md")
    result = kb.query("alpha", str(vault))
    correlation = {
        "candidates": result["retrieved_chunks"],
        "prompt_for_host": "alpha private fact association",
        "_validation": {
            **result["_validation"],
            "target": {
                key: captured[key]
                for key in ("vault_id", "source_path", "sha256", "scope_revision")
            },
        },
    }
    jobs.register("correlation", lambda params, progress: correlation)
    submitted = jobs.submit("correlation", {})
    _wait_job(jobs, submitted["job_id"])
    assert kb.validate_job_result(jobs.get(submitted["job_id"]))["result"]["candidates"]
    if mutation == "delete":
        target.unlink()
    elif mutation == "edit":
        target.write_text(target.read_text().replace("alpha target", "changed target"))
    else:
        target.write_text(target.read_text().replace("promoted", "staged"))
    before = embedding.calls
    result = kb.validate_job_result(jobs.get(submitted["job_id"]))["result"]
    assert embedding.calls == before
    assert result["status"] == "stale_result" and result["candidates"] == []
    assert result["prompt_for_host"] == ""


def test_old_cached_result_without_fingerprint_fails_closed(indexed_context):
    kb, jobs, vault, data, source, embedding = indexed_context
    old = {
        "retrieved_chunks": [
            {"path": "included/source.md", "content": "alpha private fact"}
        ],
        "prompt_for_host": "alpha private fact",
    }
    result = kb.validate_result(old)
    assert result["status"] == "stale_result"
    assert "alpha private fact" not in json.dumps(result)
