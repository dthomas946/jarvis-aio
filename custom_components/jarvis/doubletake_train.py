"""JARVIS — send face labels to Double Take for training (dthomas946 fork, FACE-2).

When a person is named in JARVIS's Faces panel ("This is…" on a sighting, or a
reference photo added by hand), the same picture is also sent to Double Take's
training API, so CompreFace learns from JARVIS labels too. Everything stays on
the local network; nothing goes to a cloud service.

Configured with the ``doubletake_url`` option (e.g. http://192.168.5.11:3000).
Empty = off. Best-effort: a failure is logged and never blocks the JARVIS label.
"""
from __future__ import annotations

import logging
import uuid

_LOGGER = logging.getLogger(__name__)


def _base_url() -> str:
    try:
        from . import jarvis_config
        return str(jarvis_config.get("doubletake_url", "") or "").strip().rstrip("/")
    except Exception:
        return ""


async def async_train(hass, name: str, jpeg: bytes) -> bool:
    """POST one JPEG to Double Take as a training image for ``name``.

    Double Take keeps names lowercase (that's how they come back in matches),
    so the name is lowercased here too. Returns True on HTTP 2xx."""
    base = _base_url()
    name = (name or "").strip().lower()
    if not base or not name or not jpeg:
        return False
    try:
        import aiohttp
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        form = aiohttp.FormData()
        form.add_field(
            "files[]", jpeg,
            filename=f"jarvis-{uuid.uuid4().hex[:12]}.jpg",
            content_type="image/jpeg",
        )
        session = async_get_clientsession(hass)
        url = f"{base}/api/train/add/{name}"
        async with session.post(url, data=form,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            ok = 200 <= resp.status < 300
            if ok:
                _LOGGER.info("JARVIS: sent training photo for %s to Double Take", name)
            else:
                body = (await resp.text())[:200]
                _LOGGER.warning("JARVIS: Double Take training for %s failed (HTTP %s): %s",
                                name, resp.status, body)
            return ok
    except Exception as exc:
        _LOGGER.warning("JARVIS: Double Take training for %s failed: %s", name, exc)
        return False
