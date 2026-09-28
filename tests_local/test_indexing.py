import os

import pytest

from local_app.indexing import VaultIndex, chunks, parse_note, scan_notes
from local_app.workspaces import vault_id


class Embeddings:
    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        lowered = text.lower()
        return [float(lowered.count(word)) for word in ("alpha", "beta", "gamma")] + [
            0.1
        ]


@pytest.fixture
def index(tmp_path):
    pytest.importorskip("chromadb")
    vault = tmp_path / "vault"
    vault.mkdir()
    embed = Embeddings()
    return VaultIndex(tmp_path / "data", lambda: embed), embed, vault


def promoted(text):
    return "---\nstatus: promoted\n---\n" + text


def policy(legacy=False, include=None, exclude=None):
    return {
        "include_existing": legacy,
        "include_dirs": include or [],
        "exclude_dirs": exclude or [],
    }


@pytest.mark.parametrize(
    "content",
    [
        "---\nstatus: staged\n---\nalpha",
        "---\nstatus: unknown\n---\nalpha",
        "---\nstatus: null\n---\nalpha",
        "---\n- scalar\n---\nalpha",
        "---\n[unclosed\n---\nalpha",
        "---\nstatus: promoted",
        "---\n\n---\nalpha",
        "---\nstatus: staged\nstatus: promoted\n---\nalpha",
        "---\nbase: &base {status: promoted}\n<<: *base\n---\nalpha",
    ],
)
def test_unreviewed_or_invalid_metadata_never_imports(content):
    assert parse_note(content, True) is None


def test_no_status_import_is_explicit():
    assert parse_note("# alpha", False) is None
    assert parse_note("# alpha", True)[1:] == ("legacy", "explicit_import")
    assert parse_note(promoted("alpha"), False)[1:] == ("promoted", "reviewed")
    assert parse_note("---\ntags: [alpha]\n---\nbody", True)[1] == "legacy"


def test_scope_and_links_are_excluded_during_scan(tmp_path):
    vault, outside = tmp_path / "vault", tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "good.md").write_text("alpha")
    (vault / ".hidden.md").write_text("alpha")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.md").write_text("alpha")
    (outside / "private.md").write_text("alpha")
    (vault / "link").symlink_to(outside, target_is_directory=True)
    (vault / "filelink.md").symlink_to(outside / "private.md")
    assert [note["source_path"] for note in scan_notes(vault, policy(True))] == [
        "good.md"
    ]


def test_incremental_index_and_noop_do_not_reembed(index):
    vectors, embed, vault = index
    (vault / "reviewed.md").write_text(promoted("# Alpha\nalpha facts"))
    (vault / "old.md").write_text("# Beta\nbeta facts")
    (vault / "draft.md").write_text("---\nstatus: staged\n---\nalpha draft")
    result = vectors.sync(vault, policy(True), lambda _: None)
    assert result["total"] == 2
    before = embed.calls
    path = vectors._manifest_path(vault)
    timestamp = path.stat().st_mtime_ns
    assert vectors.sync(vault, policy(True), lambda _: None)["changed"] is False
    assert embed.calls == before and path.stat().st_mtime_ns == timestamp
    hits = vectors.query("alpha", vault, policy(True), None, 6)
    assert {hit["path"] for hit in hits} == {"reviewed.md", "old.md"}
    assert {hit["provenance"] for hit in hits} == {"reviewed", "explicit_import"}


def test_same_relative_path_in_two_vaults_isolated(index, tmp_path):
    vectors, embed, first = index
    second = tmp_path / "second"
    second.mkdir()
    (first / "same.md").write_text(promoted("alpha first"))
    (second / "same.md").write_text(promoted("beta second"))
    for root in (first, second):
        vectors.sync(root, policy(), lambda _: None)
    hits = vectors.query("alpha", first, policy(), None, 6)
    assert len(hits) == 1 and "first" in hits[0]["content"]
    assert hits[0]["vault_id"] == vault_id(first)
    assert vectors._manifest_path(first) != vectors._manifest_path(second)


def test_stale_records_fail_closed_even_when_vector_deletion_fails(index, monkeypatch):
    vectors, embed, vault = index
    note = vault / "note.md"
    note.write_text(promoted("alpha original"))
    vectors.sync(vault, policy(), lambda _: None)
    collection = vectors._collection(vault)

    def fail_delete(*args, **kwargs):
        raise RuntimeError("simulated deletion failure")

    monkeypatch.setattr(collection, "delete", fail_delete)
    note.write_text("---\nstatus: staged\n---\nalpha original")
    with pytest.raises(RuntimeError):
        vectors.sync(vault, policy(), lambda _: None)
    assert vectors.query("alpha", vault, policy(), None, 6) == []
    note.unlink()
    assert vectors.query("alpha", vault, policy(), None, 6) == []


def test_content_fingerprint_detects_same_timestamp_changes(index):
    vectors, embed, vault = index
    note = vault / "note.md"
    note.write_text(promoted("alpha original"))
    vectors.sync(vault, policy(), lambda _: None)
    stat = note.stat()
    note.write_text(promoted("alpha modified"))
    os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert vectors.query("alpha", vault, policy(), None, 6) == []
    assert vectors.sync(vault, policy(), lambda _: None)["updated"] == 1
    assert "modified" in vectors.query("alpha", vault, policy(), None, 6)[0]["content"]


def test_current_policy_and_query_folders_can_only_narrow(index):
    vectors, embed, vault = index
    for folder in ("first", "second"):
        (vault / folder).mkdir()
        (vault / folder / "note.md").write_text("alpha " + folder)
    vectors.sync(vault, policy(True), lambda _: None)
    assert [
        hit["path"]
        for hit in vectors.query(
            "alpha", vault, policy(True, include=["first"]), [""], 6
        )
    ] == ["first/note.md"]
    assert vectors.query("alpha", vault, policy(False), None, 6) == []
    assert (
        vectors.query("alpha", vault, policy(True, include=["first"]), ["second"], 6)
        == []
    )


def test_section_chunks_preserve_headers_and_bounds():
    parts = chunks("# Topic\n" + "alpha " * 400 + "\n## Detail\nbeta")
    assert len(parts) > 2
    assert max(len(part["content"]) for part in parts) <= 900
    assert parts[-1]["header_path"] == "Topic > Detail"


def test_narrow_folder_search_not_starved_by_many_other_hits(index):
    vectors, embed, vault = index
    (vault / "chosen").mkdir()
    (vault / "chosen" / "note.md").write_text(promoted("alpha beta chosen"))
    for number in range(40):
        (vault / f"other-{number}.md").write_text(promoted("alpha"))
    vectors.sync(vault, policy(), lambda _: None)
    hits = vectors.query("alpha", vault, policy(), ["chosen"], 1)
    assert len(hits) == 1 and hits[0]["path"] == "chosen/note.md"
