"""Fork Release 3 — CAM-6 camera phone alerts."""
import asyncio
import importlib.util
import sys
import time
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

_P = Path(__file__).resolve().parents[2] / "custom_components" / "jarvis" / "camera_alerts.py"
_spec = importlib.util.spec_from_file_location("jarvis_camera_alerts_t", _P)
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)


def test_animals_and_empty_never_alert():
    for cat in ("animal", "empty", "other", "known_resident", ""):
        for sev in ("routine", "notable", "urgent"):
            assert ca.decide(cat, sev, resident_seen=False, resident_arrived=False) is None


def test_routine_never_alerts():
    for cat in ("vehicle", "person", "delivery"):
        assert ca.decide(cat, "routine", resident_seen=False, resident_arrived=False) is None


def test_vehicle_and_person_alert():
    assert ca.decide("vehicle", "notable", resident_seen=False, resident_arrived=False) == "vehicle"
    assert ca.decide("person", "urgent", resident_seen=False, resident_arrived=False) == "person"
    assert ca.decide("package", "notable", resident_seen=False, resident_arrived=False) == "delivery"


def test_resident_suppression():
    assert ca.decide("vehicle", "notable", resident_seen=False, resident_arrived=True) is None
    assert ca.decide("person", "notable", resident_seen=True, resident_arrived=False) is None
    # a resident seen doesn't hide a car; a resident arriving doesn't hide a stranger
    assert ca.decide("vehicle", "notable", resident_seen=True, resident_arrived=False) == "vehicle"
    assert ca.decide("person", "notable", resident_seen=False, resident_arrived=True) == "person"


class _St:
    def __init__(self, state, ago):
        self.state = state
        self.last_changed = datetime.now(timezone.utc) - timedelta(seconds=ago)


class _Hass:
    def __init__(self, persons):
        self.calls = []
        self.states = types.SimpleNamespace(async_all=lambda d: persons)

        async def _call(domain, name, data, blocking=False):
            self.calls.append((domain, name, data))
        self.services = types.SimpleNamespace(async_call=_call)


def test_resident_arrived_recently():
    assert ca.resident_arrived_recently(_Hass([_St("home", 60)]))
    assert not ca.resident_arrived_recently(_Hass([_St("home", 900)]))
    assert not ca.resident_arrived_recently(_Hass([_St("not_home", 10)]))


def test_send_and_cooldown():
    ca._last_sent.clear()
    h = _Hass([])
    cfg = {"notify_service": "notify.mobile_app_x"}
    get = lambda k, d=None: cfg.get(k, d)
    kw = dict(entity_id="camera.aarlo_front", camera_name="Front", category="vehicle",
              severity="notable", summary="A truck pulled into the driveway.", resident_seen=False)
    assert asyncio.run(ca.async_maybe_alert(h, get, **kw)) == "vehicle"
    assert asyncio.run(ca.async_maybe_alert(h, get, **kw)) is None   # cooldown
    assert len(h.calls) == 1
    dom, name, data = h.calls[0]
    assert (dom, name) == ("notify", "mobile_app_x")
    assert data["data"]["entity_id"] == "camera.aarlo_front"
    assert data["data"]["url"] == "/jarvis"
    cfg["camera_push_alerts"] = False
    ca._last_sent.clear()
    assert asyncio.run(ca.async_maybe_alert(h, get, **kw)) is None


# ── ENERGY-1: yesterday's electricity cost in the morning briefing ───────────
import datetime as _dt




class _ESt:
    def __init__(self, state, attrs):
        self.state = state
        self.attributes = attrs


class _EHass:
    def __init__(self, st):
        self._st = st
        self.states = types.SimpleNamespace(get=lambda e: self._st if e == "sensor.x" else None)


_ATTRS = {"usage_date": "2026-11-07", "kwh": 66.2, "intervals": 96, "complete_day": True,
          "cycle_start": "2026-11-02", "cycle_kwh": 445.0, "cycle_cost_usd": 58.33}


def test_energy_cost_line(load):
    b = load("briefing")
    line = b._gather_energy_cost(_EHass(_ESt("8.68", dict(_ATTRS))), "sensor.x",
                                 today=_dt.date(2026, 11, 8))
    assert line == ("Electricity yesterday (Saturday): 66 kWh, $8.68. "
                    "Billing cycle since Nov 2: 445 kWh, $58.33.")


def test_energy_cost_partial_and_stale(load):
    b = load("briefing")
    a = dict(_ATTRS, complete_day=False, intervals=80)
    line = b._gather_energy_cost(_EHass(_ESt("7.10", a)), "sensor.x", today=_dt.date(2026, 11, 8))
    assert "partial" in line and "80 of 96" in line
    # a day older than yesterday is never reported as yesterday
    assert b._gather_energy_cost(_EHass(_ESt("8.68", dict(_ATTRS))), "sensor.x",
                                 today=_dt.date(2026, 11, 9)) == ""
    assert b._gather_energy_cost(_EHass(_ESt("unavailable", dict(_ATTRS))), "sensor.x",
                                 today=_dt.date(2026, 11, 8)) == ""
    assert b._gather_energy_cost(_EHass(None), "sensor.x", today=_dt.date(2026, 11, 8)) == ""
    assert b._gather_energy_cost(_EHass(None), "", today=_dt.date(2026, 11, 8)) == ""
