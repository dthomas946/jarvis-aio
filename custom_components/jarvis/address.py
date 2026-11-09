"""How JARVIS addresses people (dthomas946 fork, ID-1 / ID-2).

``person_honorifics`` (panel config, JSON object) maps a household member's
name to how JARVIS addresses them, e.g.
``{"Darin": "Sir", "Paula": "Ma'am", "Albert": "Mr. Albert"}``.

When it is empty, nothing changes: the single global honorific is used
everywhere, as upstream.

When it is set:
* A conversation turn uses the speaker's own form of address. The speaker is
  the logged-in HA user who typed it (ID-2) or, failing that, the only mapped
  household member who is home. Otherwise JARVIS uses no title at all.
* Spoken announcements to the house use no title, unless exactly one mapped
  household member is home, in which case they are addressed.
* Push notifications are left alone (they go to one person's phone).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

_LOGGER = logging.getLogger(__name__)


def person_honorifics() -> dict[str, str]:
    """The configured map, keyed by lower-cased name. {} when unset."""
    try:
        from . import jarvis_config
        raw = jarvis_config.get("person_honorifics", {})
        data = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
        if not isinstance(data, dict):
            return {}
        return {str(k).strip().lower(): str(v).strip()
                for k, v in data.items() if str(k).strip()}
    except Exception:
        return {}


def _lookup(mapping: dict[str, str], name: Optional[str]) -> Optional[str]:
    """Match a display name against the map: full name, then first word."""
    if not name:
        return None
    low = name.strip().lower()
    if low in mapping:
        return mapping[low]
    first = low.split()[0] if low.split() else ""
    return mapping.get(first)


def _mapped_people_home(hass, mapping: dict[str, str]) -> list[str]:
    """Names (as mapped) of person entities that are home."""
    home = []
    try:
        for st in hass.states.async_all("person"):
            if st.state != "home":
                continue
            name = str(st.attributes.get("friendly_name") or st.name or "")
            if _lookup(mapping, name) is not None:
                home.append(name)
    except Exception:
        pass
    return home


async def speaker_name(hass, user_id: Optional[str]) -> Optional[str]:
    """Display name of the HA user who sent a request (ID-2): their linked
    person's name, else the user's own name. None for voice/system requests."""
    if not user_id:
        return None
    try:
        for st in hass.states.async_all("person"):
            if st.attributes.get("user_id") == user_id:
                return str(st.attributes.get("friendly_name") or st.name or "") or None
    except Exception:
        pass
    try:
        user = await hass.auth.async_get_user(user_id)
        if user is not None and not user.system_generated:
            return user.name or None
    except Exception:
        pass
    return None


async def honorific_for_request(hass, user_id: Optional[str]) -> Optional[str]:
    """The form of address for one conversation turn, or None when the feature
    is off (caller keeps the global honorific). "" means: no title."""
    mapping = person_honorifics()
    if not mapping:
        return None
    name = await speaker_name(hass, user_id)
    hit = _lookup(mapping, name)
    if hit is not None:
        return hit
    if name:
        return ""                      # a known user who isn't in the map
    home = _mapped_people_home(hass, mapping)
    if len(home) == 1:
        return _lookup(mapping, home[0]) or ""
    return ""


def honorific_for_announcement(hass) -> Optional[str]:
    """Form of address for a whole-house announcement, or None when off."""
    mapping = person_honorifics()
    if not mapping:
        return None
    home = _mapped_people_home(hass, mapping)
    if len(home) == 1:
        return _lookup(mapping, home[0]) or ""
    return ""


def rewrite_announcement(hass, text: str, global_honorific: str) -> str:
    """Swap the global honorific in an announcement for the right one (or
    none). No-op when the feature is off or the text doesn't contain it."""
    try:
        target = honorific_for_announcement(hass)
        if target is None or not text or not global_honorific:
            return text
        if target.strip().lower() == global_honorific.strip().lower():
            return text
        pat = re.compile(r"\b" + re.escape(global_honorific.strip()) + r"\b", re.IGNORECASE)

        def _sub(m: re.Match) -> str:
            if not target:
                return ""
            word = m.group(0)
            return target[0].upper() + target[1:] if word[:1].isupper() else target
        out = pat.sub(_sub, text)
        out = re.sub(r"\s+([.,!?;:])", r"\1", out)
        out = re.sub(r"([.!?])\s*,\s*", r"\1 ", out)
        out = re.sub(r"\s{2,}", " ", out).strip()
        try:
            from .text_tidy import tidy_address
            out = tidy_address(out)
        except Exception:
            pass
        return out
    except Exception:
        return text
