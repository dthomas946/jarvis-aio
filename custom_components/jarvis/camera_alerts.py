"""JARVIS — phone alerts for camera events (dthomas946 fork, CAM-6).

After an automatic camera review, push a phone notification when:
  * a vehicle pulls into the driveway (category ``vehicle``, severity notable+),
    unless a resident arrived home in the last few minutes (their own car);
  * an unrecognised person comes onto the property / approaches a door
    (category ``person``, severity notable+), unless a resident was recognised
    on a camera moments ago;
  * a delivery person drops something off (``delivery`` / ``package`` / ``mail``,
    severity notable+).

Animals, empty scenes, recognised residents and passing street traffic never
alert — day or night. One alert per camera per kind inside the cooldown, so a
burst of Arlo clips doesn't send a burst of notifications.

Config keys (jarvis config): ``camera_push_alerts`` (default True) and
``camera_push_cooldown`` seconds (default 300). Uses ``notify_service``.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)

_SEVERE = ("notable", "urgent")
_KIND_BY_CATEGORY = {
    "vehicle": "vehicle",
    "person": "person",
    "delivery": "delivery",
    "package": "delivery",
    "mail": "delivery",
}
_TITLES = {
    "vehicle": "Vehicle in the driveway",
    "person": "Someone at the house",
    "delivery": "Delivery",
}
RESIDENT_ARRIVAL_WINDOW = 300.0
_last_sent: dict[tuple[str, str], float] = {}


def decide(category: str, severity: str, *, resident_seen: bool,
           resident_arrived: bool) -> Optional[str]:
    """Pure decision. Returns the alert kind ('vehicle'|'person'|'delivery') or
    None. Never alerts for animals, empty/other scenes or known residents."""
    kind = _KIND_BY_CATEGORY.get(str(category or "").strip().lower())
    if kind is None:
        return None
    if str(severity or "").strip().lower() not in _SEVERE:
        return None
    if kind == "vehicle" and resident_arrived:
        return None
    if kind == "person" and resident_seen:
        return None
    return kind


def resident_arrived_recently(hass, now: Optional[float] = None,
                              window: float = RESIDENT_ARRIVAL_WINDOW) -> bool:
    """True when any person.* entity turned 'home' within ``window`` seconds."""
    now = now if now is not None else time.time()
    try:
        for st in hass.states.async_all("person"):
            if st.state != "home":
                continue
            changed = st.last_changed.timestamp()
            if 0 <= now - changed <= window:
                return True
    except Exception:
        return False
    return False


def _cooldown_ok(entity_id: str, kind: str, cooldown: float, now: float) -> bool:
    last = _last_sent.get((entity_id, kind), 0.0)
    if now - last < cooldown:
        return False
    _last_sent[(entity_id, kind)] = now
    return True


def build_payload(kind: str, camera_name: str, entity_id: str, summary: str,
                  severity: str) -> dict:
    """Notification service payload for the HA companion app. The camera
    entity_id gives iOS a live/still preview; ``image`` is the authenticated
    camera proxy for Android. Tapping opens the JARVIS panel."""
    title = f"{_TITLES.get(kind, 'Camera')} — {camera_name}"
    message = (summary or "").strip() or _TITLES.get(kind, "Camera event")
    data = {
        "entity_id": entity_id,
        "image": f"/api/camera_proxy/{entity_id}",
        "url": "/jarvis",
        "clickAction": "/jarvis",
        "group": "jarvis-camera",
        "tag": f"jarvis-cam-{entity_id}-{kind}",
    }
    if str(severity).lower() == "urgent":
        data["push"] = {"interruption-level": "time-sensitive"}
    return {"title": title, "message": message[:240], "data": data}


async def async_maybe_alert(hass, cfg_get, *, entity_id: str, camera_name: str,
                            category: str, severity: str, summary: str,
                            resident_seen: bool) -> Optional[str]:
    """Decide and, when warranted, send the push. Returns the kind sent or None.
    ``cfg_get(key, default)`` reads JARVIS config. Never raises."""
    try:
        if cfg_get("camera_push_alerts", True) is False:
            return None
        svc = str(cfg_get("notify_service", "") or "")
        if not svc.startswith("notify."):
            return None
        now = time.time()
        kind = decide(category, severity, resident_seen=resident_seen,
                      resident_arrived=resident_arrived_recently(hass, now))
        if not kind:
            return None
        try:
            cooldown = float(cfg_get("camera_push_cooldown", 300) or 300)
        except (TypeError, ValueError):
            cooldown = 300.0
        if not _cooldown_ok(entity_id, kind, cooldown, now):
            return None
        domain, name = svc.split(".", 1)
        if domain != "notify":
            return None
        await hass.services.async_call(
            "notify", name,
            build_payload(kind, camera_name, entity_id, summary, severity),
            blocking=False)
        try:
            from .websocket import jarvis_log
            jarvis_log("CAMERA", f"{camera_name}: phone alert sent ({kind})")
        except Exception:
            pass
        return kind
    except Exception as exc:  # never break the camera pipeline
        _LOGGER.debug("camera push alert failed: %s", exc)
        return None
