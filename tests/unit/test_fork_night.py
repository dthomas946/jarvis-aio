"""Fork NIGHT-1/NIGHT-2 — quiet-hours entry rule and intrusion night window."""
import importlib.util
import sys
import types
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "custom_components" / "jarvis"


def _in_quiet_hours_factory(now_dt):
    """Extract sleep_detection._in_quiet_hours with dt_util.now() stubbed."""
    import datetime as _dt
    import logging
    src = (_SRC / "sleep_detection.py").read_text()
    start = src.index("def _in_quiet_hours(")
    end = src.index("\n\n\n", start)
    ns = {"time": _dt.time, "_LOGGER": logging.getLogger("t"),
          "dt_util": types.SimpleNamespace(now=lambda: now_dt)}
    exec(src[start:end], ns)
    return ns["_in_quiet_hours"]


def test_night_window_crosses_midnight():
    import datetime as _dt
    assert _in_quiet_hours_factory(_dt.datetime(2026, 1, 1, 23, 30))("19:00", "07:00")
    assert _in_quiet_hours_factory(_dt.datetime(2026, 1, 1, 6, 59))("19:00", "07:00")
    assert not _in_quiet_hours_factory(_dt.datetime(2026, 1, 1, 12, 0))("19:00", "07:00")
    assert _in_quiet_hours_factory(_dt.datetime(2026, 1, 1, 19, 0))("19:00", "07:00")
    assert not _in_quiet_hours_factory(_dt.datetime(2026, 1, 1, 7, 0))("19:00", "07:00")


def test_entry_verb():
    src = (_SRC / "observer.py").read_text()
    ns = {}
    start = src.index("def _entry_verb(")
    end = src.index("\n\n\n", start)
    exec(src[start:end], ns)
    v = ns["_entry_verb"]
    assert v("on") == "opened"
    assert v("off") == "closed"
    assert v("unlocked") == "unlocked"
    assert v("open") == "opened"
    assert v("weird") == "changed to weird"


def test_config_keys_registered():
    src = (_SRC / "websocket.py").read_text()
    for k in ("quiet_hours_entry_critical", "intrusion_night_start",
              "intrusion_night_end", "briefing_push_phone"):
        assert f'"{k}"' in src
