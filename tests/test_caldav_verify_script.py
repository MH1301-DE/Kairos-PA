from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "caldav_verify.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("caldav_verify", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["caldav_verify"] = module
    spec.loader.exec_module(module)
    return module


cv = _load()


def test_redactor_removes_account_identifiers() -> None:
    redact = cv.Redactor("max.muster@icloud.com", "abcd-efgh-ijkl-mnop")
    redact.account_id("17345678901")
    redact.label("A1B2C3D4-0000-1111-2222-333344445555", "cal")
    redact.label("Familie Muster", "Kalender")
    text = (
        "https://p42-caldav.icloud.com/17345678901/calendars/A1B2C3D4-0000-1111-2222-333344445555/"
        " <d:displayname>Familie Muster</d:displayname> max.muster%40icloud.com"
        " ORGANIZER;CN=Erika Muster:mailto:erika@example.org pw=abcd-efgh-ijkl-mnop"
        " urn:uuid:12345678-1234-1234-1234-123456789abc tel:+49 170 9876543"
        " DTSTAMP:20261017T117345678901Z"
    )
    out = redact(text)
    for secret in (
        "17345678901/",
        "A1B2C3D4",
        "Familie Muster",
        "max.muster",
        "Erika",
        "erika@example.org",
        "abcd-efgh",
        "12345678-1234",
        "9876543",
    ):
        assert secret not in out
    assert "/1234567890/calendars/cal-1/" in out
    assert "Kalender-1" in out
    # digits inside a longer number are not an account id
    assert "117345678901Z" in out


def test_redactor_keeps_own_test_uids() -> None:
    redact = cv.Redactor("someone@icloud.com", "pw-pw-pw")
    uid = "0f8e3c3a-8a2b-4c1e-9d55-2c8f1b9a7e10-kairos-ap0"
    assert redact(f"UID:{uid}\nhref /cal/{uid}.ics") == f"UID:{uid}\nhref /cal/{uid}.ics"


def test_filter_multistatus_keeps_only_own_events() -> None:
    xml = (
        '<d:multistatus xmlns:d="DAV:">'
        "<d:response><d:href>/c/abc-kairos-ap0.ics</d:href></d:response>"
        "<d:response><d:href>/c/private.ics</d:href></d:response>"
        "</d:multistatus>"
    )
    out = cv.filter_multistatus(xml, lambda href: cv.UID_SUFFIX in href)
    assert "abc-kairos-ap0.ics" in out
    assert "private.ics" not in out


def test_parse_multistatus_reads_sync_token_and_status() -> None:
    xml = (
        '<d:multistatus xmlns:d="DAV:"><d:response><d:href>/c/x%20y.ics</d:href>'
        "<d:status>HTTP/1.1 404 Not Found</d:status></d:response>"
        "<d:sync-token>tok-2</d:sync-token></d:multistatus>"
    )
    entries, token = cv.parse_multistatus(xml)
    assert token == "tok-2"
    assert entries[0].href == "/c/x y.ics"
    assert entries[0].status == 404


def test_exdate_is_added_to_master_and_override_removed() -> None:
    uid = "s-kairos-ap0"
    ics = cv.vcalendar(
        cv.vevent(uid, "Serie", "DTSTART;TZID=Europe/Berlin:20261003T100000", "RRULE:FREQ=WEEKLY"),
        cv.vevent(
            uid,
            "verschoben",
            "RECURRENCE-ID;TZID=Europe/Berlin:20261107T100000",
            "DTSTART;TZID=Europe/Berlin:20261107T120000",
        ),
        tz=True,
    )
    exdate = "EXDATE;TZID=Europe/Berlin:20261031T100000,20261107T100000"
    events = cv.vevents(cv._add_exdate_drop_override(ics, uid, exdate))
    assert len(events) == 1
    assert events[0]["EXDATE"] == [exdate]
    assert "RRULE" in events[0]


def test_vevents_ignores_nested_alarm_properties() -> None:
    ics = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nSUMMARY:lang\r\n er Titel\r\n"
        "BEGIN:VALARM\r\nTRIGGER:-PT5M\r\nSUMMARY:Alarm\r\nEND:VALARM\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = cv.vevents(ics)
    assert events[0]["SUMMARY"] == ["SUMMARY:langer Titel"]
    assert "TRIGGER" not in events[0]
