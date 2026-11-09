"""Latest relevant (person / vehicle / delivery) capture per camera — CAM-4/5
(dthomas946 fork). Private files under <config>/jarvis/relevant_captures/; the
panel reads them over the authenticated websocket."""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)


def _dir() -> str:
    from .paths import config_path_str
    return config_path_str("jarvis", "relevant_captures")


def _stem(entity_id: str) -> str:
    return "".join(c for c in (entity_id or "").replace(".", "_") if c.isalnum() or c in "_-")[:80]


def save(entity_id: str, image_b64: str, category: str, summary: str,
         video_url: Optional[str]) -> None:
    """Executor only. Never raises."""
    try:
        stem = _stem(entity_id)
        if not stem or not image_b64:
            return
        os.makedirs(_dir(), exist_ok=True)
        raw = base64.b64decode(image_b64)
        jpg = os.path.join(_dir(), stem + ".jpg")
        with open(jpg + ".tmp", "wb") as f:
            f.write(raw)
        os.replace(jpg + ".tmp", jpg)
        meta = {"entity_id": entity_id, "ts": time.time(), "category": category,
                "summary": summary or "", "video_url": video_url or ""}
        with open(os.path.join(_dir(), stem + ".json"), "w") as f:
            json.dump(meta, f)
    except Exception as exc:
        _LOGGER.debug("relevant_captures.save failed: %s", exc)


def load(entity_id: str) -> Optional[dict]:
    """Meta + data-URL image, or None. Executor only."""
    try:
        stem = _stem(entity_id)
        with open(os.path.join(_dir(), stem + ".json")) as f:
            meta = json.load(f)
        with open(os.path.join(_dir(), stem + ".jpg"), "rb") as f:
            raw = f.read()
        meta["image"] = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
        return meta
    except Exception:
        return None
