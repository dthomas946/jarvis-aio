"""dthomas946 fork, Release 2: form of address (ID-1/ID-2), face sightings
(FACE-1) and conversation pairing for the activity feed (ACT-3)."""
import sys
import types

import pytest


class _St:
    def __init__(self, entity_id, state, **attrs):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attrs
        self.name = attrs.get("friendly_name", entity_id)


class _States:
    def __init__(self, items):
        self._items = items

    def async_all(self, domain=None):
        return [s for s in self._items if domain is None or s.entity_id.startswith(domain + ".")]


class _User:
    def __init__(self, name, system=False):
        self.name = name
        self.system_generated = system


class _Auth:
    def __init__(self, users):
        self._users = users

    async def async_get_user(self, uid):
        return self._users.get(uid)


class _Hass:
    def __init__(self, people, users=None):
        self.states = _States(people)
        self.auth = _Auth(users or {})


@pytest.fixture
def address(load, monkeypatch):
    mod = load("address")
    cfg = types.ModuleType("jc.jarvis_config")
    cfg.store = {"person_honorifics": {"Darin": "Sir", "Paula": "Ma'am", "Albert": "Mr. Albert"}}
    cfg.get = lambda k, d=None: cfg.store.get(k, d)
    monkeypatch.setitem(sys.modules, "jc.jarvis_config", cfg)
    monkeypatch.setattr(sys.modules["jc"], "jarvis_config", cfg, raising=False)
    mod._cfg = cfg
    return mod


def _people(darin="home", paula="home"):
    return [
        _St("person.darin", darin, friendly_name="Darin", user_id="u-darin"),
        _St("person.paula", paula, friendly_name="Paula", user_id="u-paula"),
    ]


@pytest.mark.asyncio
async def test_logged_in_user_gets_their_own_address(address):
    hass = _Hass(_people(), {"u-albert": _User("Albert")})
    assert await address.honorific_for_request(hass, "u-darin") == "Sir"
    assert await address.honorific_for_request(hass, "u-paula") == "Ma'am"
    # Albert has an HA login but no person entity: matched by user name.
    assert await address.honorific_for_request(hass, "u-albert") == "Mr. Albert"


@pytest.mark.asyncio
async def test_unknown_speaker_gets_no_title_unless_one_person_home(address):
    both = _Hass(_people())
    assert await address.honorific_for_request(both, None) == ""
    only_paula = _Hass(_people(darin="not_home"))
    assert await address.honorific_for_request(only_paula, None) == "Ma'am"


@pytest.mark.asyncio
async def test_a_known_user_not_in_the_map_gets_no_title(address):
    hass = _Hass(_people(), {"u-guest": _User("Beth")})
    assert await address.honorific_for_request(hass, "u-guest") == ""


@pytest.mark.asyncio
async def test_feature_off_keeps_the_global_honorific(address):
    address._cfg.store["person_honorifics"] = {}
    assert await address.honorific_for_request(_Hass(_people()), "u-darin") is None
    assert address.rewrite_announcement(_Hass(_people()), "sir, the door is open.", "sir") \
        == "sir, the door is open."


def test_announcement_drops_title_when_several_people_home(address):
    out = address.rewrite_announcement(
        _Hass(_people()), "sir, Front Door Sensor has been open for 10 minutes.", "sir")
    assert out.lower().startswith("front door sensor has been open")
    out2 = address.rewrite_announcement(
        _Hass(_people()), "Good evening sir. The garage is open.", "sir")
    assert out2 == "Good evening. The garage is open."


def test_announcement_addresses_the_only_person_home(address):
    out = address.rewrite_announcement(
        _Hass(_people(darin="not_home")), "sir, the garage is open.", "sir")
    assert out.startswith("Ma'am") or out.startswith("ma'am")


@pytest.fixture
def sightings(load, monkeypatch, tmp_path):
    mod = load("face_sightings")
    monkeypatch.setattr(mod, "_dir", lambda: str(tmp_path / "frames"))
    monkeypatch.setattr(mod, "_index_path", lambda: str(tmp_path / "idx.json"))
    # The in-memory sighting cache is module state: reset it so these sightings
    # don't leak into later tests' recent_faces() results.
    monkeypatch.setattr(mod, "_CACHE", None)
    yield mod
    mod._CACHE = None


def test_sightings_add_list_flag_delete(sightings):
    a = sightings.add_sighting("camera.front", b"\xff\xd8jpeg-a")
    b = sightings.add_sighting("camera.garage", b"\xff\xd8jpeg-b")
    rows = sightings.list_sightings()
    assert {r["id"] for r in rows} == {a["id"], b["id"]}
    assert sightings.read_jpeg(a["id"]) == b"\xff\xd8jpeg-a"
    sightings.flag(a["id"])
    assert next(r for r in sightings.list_sightings() if r["id"] == a["id"])["status"] == "flagged"
    assert sightings.delete(b["id"]) is True
    assert [r["id"] for r in sightings.list_sightings()] == [a["id"]]
    assert sightings.read_jpeg(b["id"]) == b""


def test_sightings_are_capped(sightings):
    for _ in range(sightings.MAX_SIGHTINGS + 5):
        sightings.add_sighting("camera.front", b"x")
    assert len(sightings.list_sightings()) == sightings.MAX_SIGHTINGS


@pytest.fixture
def recog(load, monkeypatch, tmp_path):
    mod = load("recognition")
    monkeypatch.setattr(mod, "FACE_REF_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "_ref_limit", lambda: 3)
    return mod


def test_reference_photos_are_added_not_replaced(recog):
    import os
    import time as _t
    assert recog.add_face_reference("Darin", b"one")
    _t.sleep(0.01)
    assert recog.add_face_reference("Darin", b"two")
    _t.sleep(0.01)
    assert recog.add_face_reference("Darin", b"three")
    assert len(recog.face_reference_paths("Darin")) == 3
    assert recog.list_face_references() == ["darin"]
    assert recog.reference_counts() == {"darin": 3}
    # Full: the oldest extra is replaced, the main photo is kept.
    _t.sleep(0.01)
    assert recog.add_face_reference("Darin", b"four")
    datas = sorted(open(p, "rb").read() for p in recog.face_reference_paths("Darin"))
    assert datas == [b"four", b"one", b"three"]
    # Removing the main photo promotes the newest extra.
    assert recog.remove_face_reference_slot("Darin", 0)
    assert len(recog.face_reference_paths("Darin")) == 2
    assert os.path.exists(os.path.join(recog.FACE_REF_DIR, "darin.jpg"))
    assert recog.remove_face_reference("Darin")
    assert recog.face_reference_paths("Darin") == []
