"""Fork SENT-1 — Sentinel left-open reminder for garage doors exposed as cover entities."""
import sys
import types
from types import SimpleNamespace
from datetime import timedelta

import pytest


def _load_sentinel():
    """Import sentinel.py with its Home Assistant imports stubbed."""
    def stub(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    stub("homeassistant")
    stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    stub("homeassistant.config_entries", ConfigEntry=object)
    stub("homeassistant.helpers")
    stub("homeassistant.helpers.event",
         async_track_state_change_event=lambda *a, **k: (lambda: None),
         async_track_time_interval=lambda *a, **k: (lambda: None))
    stub("homeassistant.util")
    stub("homeassistant.util.dt", utcnow=lambda: None)

    pkg = types.ModuleType("custom_components")
    pkg.__path__ = []
    sys.modules["custom_components"] = pkg
    jarvis_pkg = types.ModuleType("custom_components.jarvis")
    import pathlib
    jarvis_pkg.__path__ = [str(pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "jarvis")]
    sys.modules["custom_components.jarvis"] = jarvis_pkg

    import importlib
    return importlib.import_module("custom_components.jarvis.sentinel")


class _State:
    def __init__(self, entity_id, state, **attrs):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attrs


class _States:
    def __init__(self, states):
        self._s = {s.entity_id: s for s in states}

    def async_all(self):
        return list(self._s.values())

    def get(self, entity_id):
        return self._s.get(entity_id)


@pytest.fixture
def sentinel_mod():
    try:
        return _load_sentinel()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"sentinel import unavailable here: {exc}")


def test_garage_cover_rule_present(sentinel_mod):
    rules = {r["id"]: r for r in sentinel_mod.DEFAULT_RULES}
    r = rules["garage_cover_left_open"]
    assert r["domain"] == "cover"
    assert r["device_class"] == "garage"
    assert r["state"] == "open"
    assert r["for_minutes"] == 10


def test_garage_covers_enrolled_other_covers_not(sentinel_mod):
    hass = SimpleNamespace(states=_States([
        _State("cover.garage_door_2", "closed", device_class="garage"),
        _State("cover.living_room_blind", "open", device_class="blind"),
        _State("cover.no_class", "open"),
    ]))
    s = sentinel_mod.JarvisSentinel(hass, None, "sir")
    ids = set(s._collect_entity_ids())
    assert "cover.garage_door_2" in ids
    assert "cover.living_room_blind" not in ids
    assert "cover.no_class" not in ids

    rule = next(r for r in sentinel_mod.DEFAULT_RULES if r["id"] == "garage_cover_left_open")
    assert s._entity_matches_rule("cover.garage_door_2", rule)
    assert not s._entity_matches_rule("cover.living_room_blind", rule)
