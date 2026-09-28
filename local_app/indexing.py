"""Per-vault incremental vectors; every retrieval revalidates its source file."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import threading
from typing import Callable

from .jobs import JobNotReady
from .workspaces import (
    atomic_json,
    hidden_component,
    in_scope,
    is_link,
    private_dir,
    read_json,
    safe_note_path,
    vault_id,
)


_FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S | re.M
)
_FRONTMATTER_START = re.compile(r"\A---[ \t]*(?:\r?\n|\Z)")
MAX_NOTE_BYTES = 8 * 1024 * 1024


def parse_note(content: str, include_existing: bool) -> tuple[str, str, str] | None:
    """No-status legacy import is explicit; invalid/unknown/staged never passes."""
    import yaml

    match = _FRONTMATTER.match(content)
    if match:
        try:
            node = yaml.compose(match.group(1), Loader=yaml.SafeLoader)
            if not isinstance(node, yaml.MappingNode):
                return None
            keys = []
            for key, _ in node.value:
                # Duplicate keys and YAML merge aliases can obscure which
                # explicit status a reader intended. Imported notes fail closed.
                if (
                    not isinstance(key, yaml.ScalarNode)
                    or key.value in keys
                    or key.value == "<<"
                ):
                    return None
                keys.append(key.value)
            metadata = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None
        if not isinstance(metadata, dict):
            return None
        body = match.group(2)
    elif _FRONTMATTER_START.match(content):
        return None
    else:
        metadata, body = {}, content
    if metadata.get("status") == "promoted":
        return body, "promoted", "reviewed"
    if "status" not in metadata and include_existing:
        return body, "legacy", "explicit_import"
    return None


def read_note(root: Path, relative: str, policy: dict) -> dict | None:
    if not in_scope(relative, policy):
        return None
    try:
        path = safe_note_path(root, relative)
        before = path.stat()
        if before.st_size > MAX_NOTE_BYTES or not path.is_file():
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            actual = os.fstat(stream.fileno())
            data = stream.read(MAX_NOTE_BYTES + 1)
            after = os.fstat(stream.fileno())
        # Recheck the path too: replacement/deletion during the read is excluded.
        current = path.stat()

        def signature(stat):
            return stat.st_ino, stat.st_mtime_ns, stat.st_size

        if len(data) > MAX_NOTE_BYTES or not (
            signature(before)
            == signature(actual)
            == signature(after)
            == signature(current)
        ):
            return None
        safe_note_path(root, relative)
        parsed = parse_note(
            data.decode("utf-8-sig"), bool(policy.get("include_existing"))
        )
        if parsed is None:
            return None
        body, status, provenance = parsed
        return {
            "body": body,
            "status": status,
            "provenance": provenance,
            "source_path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "mtime_ns": after.st_mtime_ns,
            "size": after.st_size,
        }
    except (OSError, UnicodeError, ValueError):
        return None


def scan_notes(root: Path, policy: dict):
    for directory, children, files in os.walk(root, topdown=True, followlinks=False):
        here = Path(directory)
        children[:] = sorted(
            name
            for name in children
            if not hidden_component(name)
            and not is_link(here / name)
            and (here / name).resolve().is_relative_to(root)
        )
        for name in sorted(files):
            if hidden_component(name) or Path(name).suffix.lower() != ".md":
                continue
            relative = (here / name).relative_to(root).as_posix()
            note = read_note(root, relative, policy)
            if note is not None:
                yield note


def chunks(body: str, length: int = 900, overlap: int = 120) -> list[dict]:
    """Retain section headings and use bounded overlapping text windows."""
    sections: list[tuple[str, str]] = []
    headings: dict[int, str] = {}
    lines: list[str] = []
    label = ""
    for line in body.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            if lines:
                sections.append((label, "\n".join(lines)))
            level = len(match.group(1))
            headings = {key: val for key, val in headings.items() if key < level}
            headings[level] = match.group(2).strip()
            label = " > ".join(headings[key] for key in sorted(headings))
            lines = [line]
        else:
            lines.append(line)
    if lines:
        sections.append((label, "\n".join(lines)))
    result = []
    for heading, text in sections:
        text = text.strip()
        start = 0
        while start < len(text):
            end = min(start + length, len(text))
            if end < len(text):
                boundary = text.rfind("\n", start + length // 2, end)
                if boundary > start:
                    end = boundary
            piece = text[start:end].strip()
            if piece:
                result.append({"content": piece, "header_path": heading})
            if end == len(text):
                break
            start = max(start + 1, end - overlap)
    return result


def default_embeddings(data_dir: Path):
    features = read_json(data_dir / "features.json", {})
    semantic = features.get("semantic", {})
    value = semantic.get("model_path")
    if (
        semantic.get("ready") is not True
        or not isinstance(value, str)
        or not Path(value).is_absolute()
    ):
        raise JobNotReady("semantic not ready")
    model = Path(value)
    # Never call the old downloader unless files are already present. An
    # installation marker is necessary but not sufficient after manual deletion.
    if not (model / "config.json").is_file() or not any(
        (model / name).is_file()
        for name in (
            "pytorch_model.bin",
            "model.safetensors",
            "pytorch_model.safetensors",
        )
    ):
        raise JobNotReady("model files absent")
    from config.settings import Settings
    from core.tools.embeddings import get_local_embeddings

    settings = Settings(
        _env_file=None,
        embed_model_cache_dir=str(model),
        embed_device="cpu",
        vault_autodiscover=False,
    )
    return get_local_embeddings(settings)


class VaultIndex:
    def __init__(self, data_dir: Path, embedding_factory: Callable | None = None):
        self.data_dir = Path(data_dir)
        self.embedding_factory = embedding_factory or (
            lambda: default_embeddings(self.data_dir)
        )
        self._clients: dict[str, object] = {}
        self._collections: dict[str, object] = {}
        self._lock = threading.RLock()
        self._embedding = None

    def _manifest_path(self, root: Path) -> Path:
        return self.data_dir / "indexes" / vault_id(root) / "manifest.json"

    def _collection(self, root: Path):
        identity = vault_id(root)
        if identity not in self._collections:
            try:
                import chromadb
                from chromadb.config import Settings as ChromaSettings
            except ImportError:
                raise JobNotReady("vector components absent") from None
            directory = private_dir(self.data_dir / "indexes" / identity / "chroma")
            client = chromadb.PersistentClient(
                path=str(directory), settings=ChromaSettings(anonymized_telemetry=False)
            )
            collection = client.get_or_create_collection(
                name="notes", metadata={"hnsw:space": "cosine"}, embedding_function=None
            )
            self._clients[identity], self._collections[identity] = client, collection
        return self._collections[identity]

    def _embeddings(self):
        if self._embedding is None:
            self._embedding = self.embedding_factory()
        return self._embedding

    def sync(
        self,
        root: Path,
        policy: dict,
        progress: Callable,
        still_authorized: Callable | None = None,
    ) -> dict:
        with self._lock:
            progress({"phase": "scanning", "message": "扫描已指定范围内的 Markdown"})
            current = {note["source_path"]: note for note in scan_notes(root, policy)}
            path = self._manifest_path(root)
            stored = read_json(path, {"notes": {}})
            previous = stored.get("notes", {})

            def unchanged(rel):
                return (
                    previous.get(rel, {}).get("sha256") == current[rel]["sha256"]
                    and previous.get(rel, {}).get("status") == current[rel]["status"]
                    and previous.get(rel, {}).get("provenance")
                    == current[rel]["provenance"]
                )

            changed = [rel for rel in current if not unchanged(rel)]
            removed = [rel for rel in previous if rel not in current]
            if still_authorized and not still_authorized():
                return {"status": "superseded"}
            if not changed and not removed:
                if not path.exists():
                    atomic_json(path, {"notes": {}, "vault_id": vault_id(root)})
                return {
                    "status": "ready",
                    "added": 0,
                    "updated": 0,
                    "removed": 0,
                    "total": len(current),
                    "changed": False,
                }
            # Embeddings are not loaded for removals or a no-op refresh.
            embedding = self._embeddings() if changed else None
            collection = self._collection(root)
            manifest = dict(previous)
            total = len(changed) + len(removed)
            complete = 0
            for relative in removed:
                if still_authorized and not still_authorized():
                    return {"status": "superseded"}
                # If deletion fails, no success manifest is written. Query-time
                # source/policy checks still suppress every obsolete record.
                ids = previous[relative].get("chunk_ids", [])
                if ids:
                    collection.delete(ids=ids)
                manifest.pop(relative, None)
                complete += 1
                progress({"phase": "indexing", "completed": complete, "total": total})
            for relative in changed:
                if still_authorized and not still_authorized():
                    return {"status": "superseded"}
                note = current[relative]
                pieces = chunks(note["body"])
                ids = [
                    hashlib.sha256(
                        f"{relative}\0{note['sha256']}\0{i}".encode()
                    ).hexdigest()
                    for i in range(len(pieces))
                ]
                if pieces:
                    texts = [piece["content"] for piece in pieces]
                    vectors = embedding.embed_documents(texts)
                    metadatas = [
                        {
                            "source_path": relative,
                            "path": relative,
                            "status": note["status"],
                            "provenance": note["provenance"],
                            "vault_id": vault_id(root),
                            "sha256": note["sha256"],
                            "header_path": piece["header_path"],
                        }
                        for piece in pieces
                    ]
                    # Fingerprinted deterministic IDs make retry safe after a
                    # crash between upsert and manifest replacement.
                    collection.upsert(
                        ids=ids,
                        documents=texts,
                        embeddings=vectors,
                        metadatas=metadatas,
                    )
                old_ids = [
                    item
                    for item in previous.get(relative, {}).get("chunk_ids", [])
                    if item not in ids
                ]
                if old_ids:
                    collection.delete(ids=old_ids)
                manifest[relative] = {
                    key: note[key]
                    for key in ("sha256", "mtime_ns", "size", "status", "provenance")
                }
                manifest[relative]["chunk_ids"] = ids
                complete += 1
                progress({"phase": "indexing", "completed": complete, "total": total})
            if still_authorized and not still_authorized():
                return {"status": "superseded"}
            atomic_json(path, {"notes": manifest, "vault_id": vault_id(root)})
            return {
                "status": "ready",
                "added": sum(rel not in previous for rel in changed),
                "updated": sum(rel in previous for rel in changed),
                "removed": len(removed),
                "total": len(current),
                "changed": True,
            }

    def query(
        self,
        question: str,
        root: Path,
        policy: dict,
        folders: list[str] | None,
        top_k: int,
    ) -> list[dict]:
        with self._lock:
            path = self._manifest_path(root)
            if not path.exists():
                return []
            manifest = read_json(path, {"notes": {}}).get("notes", {})
            if not manifest:
                return []
            allowed_paths = [
                relative for relative in manifest if in_scope(relative, policy, folders)
            ]
            if not allowed_paths:
                return []
            embedding = self._embeddings()
            collection = self._collection(root)
            count = collection.count()
            if not count:
                return []
            # Filter before ranking so out-of-scope high-scoring notes cannot
            # consume the candidate budget of a narrowly scoped query.
            result = collection.query(
                query_embeddings=[embedding.embed_query(question)],
                n_results=min(count, max(top_k * 8, 32)),
                where={"source_path": {"$in": allowed_paths}},
                include=["documents", "metadatas", "distances"],
            )
            hits, checked = [], {}
            for identity, text, metadata, distance in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            ):
                relative = metadata.get("source_path", "")
                saved = manifest.get(relative)
                if (
                    not saved
                    or identity not in saved.get("chunk_ids", [])
                    or not in_scope(relative, policy, folders)
                ):
                    continue
                if relative not in checked:
                    checked[relative] = read_note(root, relative, policy)
                current = checked[relative]
                if (
                    current is None
                    or current["sha256"] != saved.get("sha256")
                    or current["sha256"] != metadata.get("sha256")
                ):
                    continue
                if (
                    metadata.get("vault_id") != vault_id(root)
                    or current["status"] != metadata.get("status")
                    or current["provenance"] != metadata.get("provenance")
                ):
                    continue
                hits.append(
                    {
                        "content": text,
                        "path": relative,
                        "source_path": relative,
                        "status": current["status"],
                        "provenance": current["provenance"],
                        "vault_id": vault_id(root),
                        "sha256": current["sha256"],
                        "header_path": metadata.get("header_path", ""),
                        "score": 1.0 - distance,
                    }
                )
                if len(hits) >= top_k:
                    break
            return hits

    def summary(self, root: Path) -> dict:
        manifest = read_json(self._manifest_path(root), {"notes": {}})
        notes = manifest.get("notes", {})
        return {
            "indexed_notes": len(notes),
            "indexed_chunks": sum(
                len(note.get("chunk_ids", [])) for note in notes.values()
            ),
        }
