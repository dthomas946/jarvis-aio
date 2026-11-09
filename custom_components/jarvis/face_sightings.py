"""Unknown-face sighting history and "This is…" labelling (dthomas946 fork, FACE-1).

Upstream keeps only the newest unknown sighting per camera, in memory. This
keeps a short persisted history of unknown sightings (frame + camera + time) so
each one can be labelled from the Faces tab:

* a household resident  → the frame becomes one more reference photo for them
* a regular visitor     → frame stored as their reference; they are matched by
                           name from then on, but never treated as a resident
* delivery / service    → logged as an expected visit; the face is NOT kept
* ignore                → deleted
* flag                  → kept and marked for attention (logged as high urgency)

Frames live privately in <config>/jarvis/face_sightings/<id>.jpg (NOT under
www, so never reachable at an unauthenticated /local URL); the panel reads them
over the authenticated websocket. The index is a small JSON file.
Nothing here feeds intrusion stand-down.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Optional

_LOGGER = logging.getLogger(__name__)

MAX_SIGHTINGS = 24
MAX_AGE_S = 7 * 24 * 3600
_lock = threading.Lock()


def _dir() -> str:
    from .paths import config_path_str
    return config_path_str("jarvis", "face_sightings")


def _index_path() -> str:
    from .paths import config_path_str
    return config_path_str("jarvis", "face_sightings.json")


def _load() -> list[dict]:
    try:
        with open(_index_path(), "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(rows: list[dict]) -> None:
    path = _index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f)
    os.replace(tmp, path)


def _jpg_path(sid: str) -> str:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:40]
    return os.path.join(_dir(), f"{safe}.jpg")


def _prune(rows: list[dict]) -> list[dict]:
    now = time.time()
    keep, drop = [], []
    for r in sorted(rows, key=lambda r: r.get("ts", 0), reverse=True):
        too_old = now - float(r.get("ts", 0)) > MAX_AGE_S and r.get("status") != "flagged"
        if too_old or len(keep) >= MAX_SIGHTINGS:
            drop.append(r)
        else:
            keep.append(r)
    for r in drop:
        try:
            os.remove(_jpg_path(r["id"]))
        except Exception:
            pass
    return keep


def add_sighting(camera_entity: str, jpeg: bytes) -> Optional[dict]:
    """Store one unknown sighting. Executor only (file I/O). Never raises."""
    try:
        if not jpeg:
            return None
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        os.makedirs(_dir(), exist_ok=True)
        with open(_jpg_path(sid), "wb") as f:
            f.write(jpeg)
        row = {"id": sid, "ts": time.time(), "camera_entity": camera_entity,
               "status": "new"}
        with _lock:
            rows = _load()
            rows.append(row)
            _save(_prune(rows))
        return row
    except Exception as exc:
        _LOGGER.debug("face_sightings.add failed: %s", exc)
        return None


def list_sightings() -> list[dict]:
    """Open sightings (new or flagged), newest first, with their served URL."""
    with _lock:
        rows = _prune(_load())
    now = time.time()
    out = []
    for r in rows:
        if r.get("status") not in ("new", "flagged"):
            continue
        out.append({**r, "age_seconds": int(now - float(r.get("ts", now)))})
    return out


def _pop(sid: str) -> Optional[dict]:
    with _lock:
        rows = _load()
        hit = next((r for r in rows if r.get("id") == sid), None)
        if hit is None:
            return None
        rows = [r for r in rows if r.get("id") != sid]
        _save(rows)
    return hit


def read_jpeg(sid: str) -> bytes:
    try:
        with open(_jpg_path(sid), "rb") as f:
            return f.read()
    except Exception:
        return b""


def delete(sid: str) -> bool:
    hit = _pop(sid)
    try:
        os.remove(_jpg_path(sid))
    except Exception:
        pass
    return hit is not None


def flag(sid: str) -> Optional[dict]:
    with _lock:
        rows = _load()
        hit = None
        for r in rows:
            if r.get("id") == sid:
                r["status"] = "flagged"
                hit = r
        _save(rows)
    return hit


def visitors() -> list[str]:
    """Named regular visitors (matched by name, never residents)."""
    try:
        from . import jarvis_config
        raw = jarvis_config.get("face_visitors", [])
        data = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
        return [str(x) for x in (data or []) if str(x).strip()]
    except Exception:
        return []


def add_visitor(name: str) -> None:
    from . import jarvis_config
    cur = visitors()
    if name.strip().lower() not in {v.lower() for v in cur}:
        cur.append(name.strip())
        jarvis_config.set("face_visitors", cur)
