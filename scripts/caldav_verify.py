"""CalDAV AP 0: prüft die 13 offenen Fakten aus §12 der Kalender-Provider-Spec
(docs/superpowers/specs/2026-10-14-kalender-provider-caldav-design.md) gegen ein echtes
iCloud-Konto und gibt einen Bericht aus.

Aufruf (Zugangsdaten nur aus der Umgebung, nie als Argument):

    export ICLOUD_USERNAME='apple-id@example.com'
    export ICLOUD_APP_PASSWORD='xxxx-xxxx-xxxx-xxxx'
    uv run --with caldav==3.5.0 python scripts/caldav_verify.py

Optionale Umgebungsvariablen:
    CALDAV_TEST_CALENDAR  URL, Pfad oder Anzeigename eines vorhandenen, beschreibbaren
                          Kalenders; ohne sie legt das Skript einen eigenen Testkalender an
    CALDAV_SERVER_URL     Default https://caldav.icloud.com

Das Skript schreibt nur Wegwerf-Termine (UID endet auf "-kairos-ap0") in den Testkalender
und einen zweiten, eigenen Hilfskalender, verändert keine bestehenden Termine und räumt am
Ende alles auf, was es angelegt hat. Gespeicherte Antworten werden anonymisiert (keine
Namen, keine Apple-ID, keine numerische Konto-ID) und landen in tests/fixtures/caldav/.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx

NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "cs": "http://calendarserver.org/ns/",
    "ical": "http://apple.com/ns/ical/",
}
for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)

TZ_NAME = "Europe/Berlin"
UID_SUFFIX = "-kairos-ap0"
SUMMARY_PREFIX = "Kairos AP0"
INVITE_MARKER = "KAIROS-AP0-EINLADUNG"
DEFAULT_SERVER = "https://caldav.icloud.com"
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "caldav"
SAVED_HEADERS = ("etag", "location", "content-type", "dav", "retry-after", "www-authenticate")
XML = "application/xml; charset=utf-8"
ICS = "text/calendar; charset=utf-8"

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""

QUESTIONS = {
    1: "Discovery: Principal-Pfad, Home-Set-Host, Redirects, python-caldav",
    2: "Kalenderliste: Komponenten, Schreibrecht, geteilte/abonnierte Kalender",
    3: "time-range liefert Serie mit Master vor dem Fenster",
    4: "<C:expand>: Instanzen, Overrides, RECURRENCE-ID der Erstinstanz",
    5: "sync-collection und getctag",
    6: "PUT mit If-None-Match: *, Location, ETag",
    7: "DELETE mit If-Match: 412 und 404",
    8: "Löschen eines eingeladenen Termins: Absage an den Organisator",
    9: "Gleiche UID in zwei Kalendern",
    10: "Ganztags-, TZID- und schwebende Termine; calendar-timezone",
    11: "Fehlercodes: falsches/widerrufenes Passwort, Drosselung",
    12: "Instanz löschen per EXDATE",
    13: "python-caldav-Version, Abhängigkeiten, sync oder aio",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URN_RE = re.compile(r"(?i)urn:uuid:[0-9a-f-]{36}")
_TEL_RE = re.compile(r"(?i)tel:\+?[0-9][0-9 ()-]{4,}[0-9]")
_CN_RE = re.compile(r'(?i)CN=(?:"[^"]*"|[^;:\r\n]+)')


@functools.cache
def _tz() -> ZoneInfo:
    return ZoneInfo(TZ_NAME)


# --- Anonymisierung -----------------------------------------------------------------


class Redactor:
    def __init__(self, username: str, password: str) -> None:
        self._literal: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._account_ids: set[str] = set()
        for variant in {username, quote(username), quote(username, safe="")}:
            self._add(variant, "user@example.com")
        self._add(password, "<redacted>")

    def _add(self, value: str, replacement: str) -> None:
        if value and len(value) >= 3:
            self._literal[value] = replacement

    def account_id(self, value: str) -> None:
        self._account_ids.add(value)

    def label(self, value: str, prefix: str) -> str:
        """Ersetzt einen Kalendernamen oder ein Collection-Segment stabil durch prefix-N."""
        if value not in self._labels:
            n = sum(1 for v in self._labels.values() if v.startswith(prefix)) + 1
            self._labels[value] = f"{prefix}-{n}"
            self._add(value, self._labels[value])
        return self._labels[value]

    def __call__(self, text: str) -> str:
        for value in sorted(self._literal, key=len, reverse=True):
            text = text.replace(value, self._literal[value])
        for acc in self._account_ids:
            text = re.sub(rf"(?<![0-9]){re.escape(acc)}(?![0-9])", "1234567890", text)
        text = _EMAIL_RE.sub("user@example.com", text)
        text = _URN_RE.sub("urn:uuid:00000000-0000-0000-0000-000000000000", text)
        text = _TEL_RE.sub("tel:+490000000", text)
        return _CN_RE.sub("CN=Redacted", text)


class Recorder:
    """Puffert Fixtures bis zum Ende, damit alle Namen und IDs bekannt sind."""

    def __init__(self) -> None:
        self.items: dict[str, str | dict[str, Any] | list[Any]] = {}

    def add(self, name: str, content: str | dict[str, Any] | list[Any]) -> None:
        self.items[name] = content

    def response(self, name: str, resp: httpx.Response, body: bool = True) -> None:
        self.add(name, exchange_dict(resp, body=body))

    def flush(self, redact: Redactor, target: Path) -> list[Path]:
        target.mkdir(parents=True, exist_ok=True)
        written = []
        for name, content in sorted(self.items.items()):
            text = content if isinstance(content, str) else json.dumps(content, indent=2)
            path = target / name
            path.write_text(redact(text).replace("\r\n", "\n"), encoding="utf-8")
            written.append(path)
        return written


def exchange_dict(resp: httpx.Response, body: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "request": {"method": resp.request.method, "path": urlsplit(str(resp.request.url)).path},
        "status": resp.status_code,
        "headers": {k: resp.headers[k] for k in SAVED_HEADERS if k in resp.headers},
    }
    if body:
        out["body"] = resp.text
    return out


# --- HTTP und XML -------------------------------------------------------------------


@dataclass
class DavEntry:
    href: str
    status: int | None
    props: dict[str, ET.Element]
    prop_status: dict[str, int | None]


def tag(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def status_code(line: str | None) -> int | None:
    match = re.search(r"\s(\d{3})(?:\s|$)", line or "")
    return int(match.group(1)) if match else None


def parse_multistatus(text: str) -> tuple[list[DavEntry], str | None]:
    root = ET.fromstring(text)
    entries = []
    for resp in root.findall("d:response", NS):
        props: dict[str, ET.Element] = {}
        prop_status: dict[str, int | None] = {}
        for propstat in resp.findall("d:propstat", NS):
            code = status_code(propstat.findtext("d:status", None, NS))
            prop = propstat.find("d:prop", NS)
            for el in list(prop) if prop is not None else []:
                props[el.tag] = el
                prop_status[el.tag] = code
        entries.append(
            DavEntry(
                href=unquote(resp.findtext("d:href", "", NS).strip()),
                status=status_code(resp.findtext("d:status", None, NS)),
                props=props,
                prop_status=prop_status,
            )
        )
    return entries, root.findtext("d:sync-token", None, NS)


def filter_multistatus(text: str, keep: Callable[[str], bool]) -> str:
    """Entfernt alle d:response-Einträge, deren href nicht zu den eigenen Terminen gehört."""
    root = ET.fromstring(text)
    for resp in list(root.findall("d:response", NS)):
        if not keep(unquote(resp.findtext("d:href", "", NS).strip())):
            root.remove(resp)
    return ET.tostring(root, encoding="unicode")


def prop_ok(entry: DavEntry, key: str) -> ET.Element | None:
    el = entry.props.get(key)
    return el if el is not None and entry.prop_status.get(key) == 200 else None


def href_text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    href = el.findtext("d:href", None, NS)
    return unquote(href.strip()) if href else None


class Dav:
    def __init__(self, username: str, password: str, timeout: float = 30.0) -> None:
        self.client = httpx.Client(
            auth=(username, password),
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "kairos-caldav-ap0/1"},
        )
        self.redirects: list[tuple[str, int, str]] = []
        self.statuses: list[tuple[str, int, str | None]] = []

    def request(
        self,
        method: str,
        url: str,
        body: str | None = None,
        *,
        content_type: str = XML,
        depth: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        h: dict[str, str] = {}
        if body is not None:
            h["Content-Type"] = content_type
        if depth is not None:
            h["Depth"] = str(depth)
        h.update(headers or {})
        data = body.encode("utf-8") if body is not None else None
        resp = self.client.request(method, url, content=data, headers=h)
        for _ in range(5):
            if resp.status_code not in (301, 302, 307, 308) or "location" not in resp.headers:
                break
            target = urljoin(url, resp.headers["location"])
            self.redirects.append((url, resp.status_code, target))
            url = target
            resp = self.client.request(method, url, content=data, headers=h)
        self.statuses.append((method, resp.status_code, resp.headers.get("retry-after")))
        return resp

    def propfind(self, url: str, props: list[str], depth: int = 0) -> httpx.Response:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:cs="http://calendarserver.org/ns/" xmlns:ical="http://apple.com/ns/ical/">'
            f"<d:prop>{''.join(f'<{p}/>' for p in props)}</d:prop></d:propfind>"
        )
        return self.request("PROPFIND", url, body, depth=depth)

    def query(
        self, url: str, start: datetime, end: datetime, expand: bool = False
    ) -> httpx.Response:
        s, e = ical_utc(start), ical_utc(end)
        exp = f'<c:expand start="{s}" end="{e}"/>' if expand else ""
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:prop><d:getetag/><c:calendar-data>{exp}</c:calendar-data></d:prop>"
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{s}" end="{e}"/>'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        return self.request("REPORT", url, body, depth=1)

    def sync_collection(self, url: str, token: str) -> httpx.Response:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:sync-collection xmlns:d="DAV:">'
            f"<d:sync-token>{token}</d:sync-token><d:sync-level>1</d:sync-level>"
            "<d:prop><d:getetag/></d:prop></d:sync-collection>"
        )
        return self.request("REPORT", url, body)

    def put_ics(self, url: str, ics: str, headers: dict[str, str]) -> httpx.Response:
        return self.request("PUT", url, ics, content_type=ICS, headers=headers)


# --- iCalendar ----------------------------------------------------------------------


def ical_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def ical_local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def vcalendar(*components: str, tz: bool = False) -> str:
    parts = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kairos//CalDAV AP0//DE"]
    if tz:
        parts.append(VTIMEZONE)
    parts.extend(components)
    parts.append("END:VCALENDAR")
    return "\r\n".join("\r\n".join(parts).splitlines()) + "\r\n"


def vevent(uid: str, summary: str, *lines: str) -> str:
    return "\n".join(
        [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{ical_utc(datetime.now(UTC))}",
            f"SUMMARY:{SUMMARY_PREFIX} – {summary}",
            *lines,
            "END:VEVENT",
        ]
    )


def unfold(ics: str) -> list[str]:
    lines: list[str] = []
    for raw in ics.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def vevents(ics: str) -> list[dict[str, list[str]]]:
    """VEVENTs als {Eigenschaftsname: [ganze Zeilen]}; reicht für die Prüfungen hier."""
    out: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    depth = 0
    for line in unfold(ics):
        if line == "BEGIN:VEVENT":
            current, depth = {}, 0
        elif line == "END:VEVENT" and current is not None:
            out.append(current)
            current = None
        elif current is not None:
            if line.startswith("BEGIN:"):
                depth += 1
            elif line.startswith("END:"):
                depth -= 1
            elif depth == 0:
                name = re.split(r"[;:]", line, maxsplit=1)[0].upper()
                current.setdefault(name, []).append(line)
    return out


def calendar_data(entry: DavEntry) -> str:
    el = prop_ok(entry, tag("c", "calendar-data"))
    return (el.text or "") if el is not None else ""


# --- Verifikation -------------------------------------------------------------------


@dataclass
class Finding:
    number: int
    verdict: str = "offen"
    summary: str = ""
    details: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        self.details.append(text)


@dataclass
class Calendar:
    url: str
    name: str
    label: str
    components: list[str]
    writable: bool
    kinds: list[str]
    timezone: str | None
    ctag: str | None
    sync_token: str | None


class Verifier:
    def __init__(self, args: argparse.Namespace, username: str, password: str) -> None:
        self.args = args
        self.username = username
        self.password = password
        self.server = os.environ.get("CALDAV_SERVER_URL", DEFAULT_SERVER).rstrip("/") + "/"
        self.redact = Redactor(username, password)
        self.rec = Recorder()
        self.dav = Dav(username, password)
        self.findings = {n: Finding(n) for n in QUESTIONS}
        self.principal_url = ""
        self.home_url = ""
        self.calendars: list[Calendar] = []
        self.test_cal: Calendar | None = None
        self.second_cal_url: str | None = None
        self.created_calendars: list[str] = []
        self.created_hrefs: dict[str, str] = {}
        self.cleanup_notes: list[str] = []
        self.started = time.monotonic()
        today = datetime.now(_tz()).date()
        self.day0 = today + timedelta(days=14)
        self.window_start = datetime.combine(self.day0, datetime.min.time(), _tz())
        self.window_end = self.window_start + timedelta(days=21)
        self.series_start = datetime.combine(self.day0 - timedelta(days=28), _t(10), _tz())
        self.series_uid = f"{uuid.uuid4()}{UID_SUFFIX}"
        self.tzid_uid = ""
        self.initial_sync_token: str | None = None
        self.single: tuple[str, str, str, str | None] = ("", "", "", None)
        self.series_href = ""

    # -- Ablauf

    def run(self) -> int:
        steps: list[tuple[int, Callable[[], None]]] = [
            (1, self.check_discovery),
            (2, self.check_calendars),
            (13, self.check_library_versions),
            (5, self.sync_initial),
            (6, self.check_put),
            (7, self.check_delete),
            (3, self.check_series_query),
            (4, self.check_expand),
            (10, self.check_time_kinds),
            (5, self.check_sync_delta),
            (9, self.check_duplicate_uid),
            (13, self.check_library_behaviour),
            (12, self.check_exdate),
            (11, self.check_errors),
            (8, self.check_invite),
            (5, self.check_sync_token_lifetime),
        ]
        try:
            for number, step in steps:
                if number > 2 and self.test_cal is None:
                    self._fail(number, "übersprungen: kein beschreibbarer Testkalender")
                    continue
                self._guard(number, step)
            if self.args.iphone_check and self.test_cal is not None:
                self._iphone_pause()
        except KeyboardInterrupt:
            print("\nAbgebrochen, räume auf …", file=sys.stderr)
        finally:
            self.cleanup()
        return self.report()

    def _guard(self, number: int, step: Callable[[], None]) -> None:
        try:
            step()
        except Exception as exc:
            self._fail(number, f"{step.__name__}: {type(exc).__name__}: {exc}")

    def _fail(self, number: int, text: str) -> None:
        f = self.findings[number]
        if f.verdict in ("offen", "geklärt"):
            f.verdict = "fehler" if f.verdict == "offen" else "teilweise"
        f.note(f"FEHLER {text}")

    def _ok(self, number: int, summary: str, verdict: str = "geklärt") -> None:
        f = self.findings[number]
        f.summary = f"{f.summary} {summary}".strip() if f.summary else summary
        if f.verdict == "offen":
            f.verdict = verdict

    # -- 1 Discovery

    def check_discovery(self) -> None:
        f = self.findings[1]
        wk = httpx.get(
            urljoin(self.server, "/.well-known/caldav"),
            auth=(self.username, self.password),
            follow_redirects=False,
            timeout=30,
        )
        self.rec.response("01_well_known.json", wk, body=False)
        f.note(f"/.well-known/caldav → {wk.status_code} {wk.headers.get('location', '')}")

        resp = self.dav.propfind(self.server, ["d:current-user-principal"])
        self.rec.response("01_propfind_current_user_principal.json", resp)
        if resp.status_code in (401, 403):
            raise RuntimeError(f"Anmeldung abgelehnt ({resp.status_code}), Abbruch")
        entries, _ = parse_multistatus(resp.text)
        principal = href_text(prop_ok(entries[0], tag("d", "current-user-principal")))
        if not principal:
            raise RuntimeError("kein current-user-principal in der Antwort")
        self.principal_url = urljoin(str(resp.url), principal)
        match = re.match(r"^/(\d+)/principal/?$", urlsplit(self.principal_url).path)
        if match:
            self.redact.account_id(match.group(1))
        f.note(
            f"current-user-principal → Status {resp.status_code}, Host "
            f"{urlsplit(self.principal_url).netloc}, Pfadform "
            f"{'/<numerische-id>/principal/' if match else urlsplit(self.principal_url).path}"
        )

        resp = self.dav.propfind(
            self.principal_url,
            ["c:calendar-home-set", "c:schedule-inbox-URL", "c:schedule-outbox-URL"],
        )
        self.rec.response("01_propfind_principal.json", resp)
        entries, _ = parse_multistatus(resp.text)
        home = href_text(prop_ok(entries[0], tag("c", "calendar-home-set")))
        if not home:
            raise RuntimeError("kein calendar-home-set")
        self.home_url = urljoin(self.principal_url, home)
        inbox = href_text(prop_ok(entries[0], tag("c", "schedule-inbox-URL")))
        outbox = href_text(prop_ok(entries[0], tag("c", "schedule-outbox-URL")))
        self.findings[8].note(
            f"Principal meldet schedule-inbox: {'ja' if inbox else 'nein'}, "
            f"schedule-outbox: {'ja' if outbox else 'nein'} (Hinweis auf serverseitiges Scheduling)"
        )
        home_host = urlsplit(self.home_url).netloc
        f.note(f"calendar-home-set → Host {home_host}, Pfad {urlsplit(self.home_url).path}")
        for src, code, dst in self.dav.redirects:
            f.note(f"Redirect {code}: {urlsplit(src).netloc} → {urlsplit(dst).netloc}")
        shard = re.fullmatch(r"p\d+-caldav\.icloud\.com(:443)?", home_host) is not None
        self._ok(
            1,
            f"Principal {'/<id>/principal/' if match else 'andere Pfadform'}; Home-Set auf "
            f"{'Shard-Host pNN-caldav.icloud.com' if shard else home_host}; "
            f"{len(self.dav.redirects)} Redirect(s).",
        )

    # -- 2 Kalenderliste

    def check_calendars(self) -> None:
        f = self.findings[2]
        resp = self.dav.propfind(
            self.home_url,
            [
                "d:resourcetype",
                "d:displayname",
                "c:supported-calendar-component-set",
                "d:current-user-privilege-set",
                "c:calendar-timezone",
                "cs:getctag",
                "d:sync-token",
                "cs:source",
                "d:supported-report-set",
            ],
            depth=1,
        )
        entries, _ = parse_multistatus(resp.text)
        home_path = urlsplit(self.home_url).path.rstrip("/")
        for entry in entries:
            if entry.href.rstrip("/") == home_path:
                continue
            self.calendars.append(self._calendar_from(entry))
        self.rec.add("02_calendar_list.xml", self._anonymised_listing(resp.text))
        self.rec.add(
            "02_calendar_summary.json",
            [
                {k: v for k, v in c.__dict__.items() if k not in ("url", "name", "ctag")}
                for c in self.calendars
            ],
        )
        vevent_cals = [c for c in self.calendars if "VEVENT" in c.components]
        todo_only = [c for c in self.calendars if c.components == ["VTODO"]]
        for c in self.calendars:
            f.note(
                f"{c.label}: Typ {','.join(c.kinds) or '-'}; Komponenten "
                f"{','.join(c.components) or '-'}; beschreibbar {'ja' if c.writable else 'nein'}; "
                f"calendar-timezone {'gesetzt' if c.timezone else 'fehlt'}"
            )
        reports = self._supported_reports(entries)
        f.note(f"supported-report-set (vereinigt): {', '.join(sorted(reports)) or '-'}")
        self._ok(
            2,
            f"{len(self.calendars)} Collections, davon {len(vevent_cals)} mit VEVENT, "
            f"{len(todo_only)} nur VTODO (Erinnerungen), "
            f"{sum(c.writable for c in vevent_cals)} VEVENT-Kalender beschreibbar; Typen: "
            f"{', '.join(sorted({k for c in self.calendars for k in c.kinds})) or '-'}.",
        )
        self._select_test_calendar()

    def _calendar_from(self, entry: DavEntry) -> Calendar:
        rtype = prop_ok(entry, tag("d", "resourcetype"))
        kinds = [] if rtype is None else [child.tag.split("}")[-1] for child in rtype]
        comps_el = prop_ok(entry, tag("c", "supported-calendar-component-set"))
        comps = [] if comps_el is None else [c.get("name", "") for c in comps_el]
        privs_el = prop_ok(entry, tag("d", "current-user-privilege-set"))
        privs = set() if privs_el is None else {p.tag.split("}")[-1] for p in privs_el.iter()}
        name_el = prop_ok(entry, tag("d", "displayname"))
        name = (name_el.text or "") if name_el is not None else ""
        tz_el = prop_ok(entry, tag("c", "calendar-timezone"))
        ctag_el = prop_ok(entry, tag("cs", "getctag"))
        sync_el = prop_ok(entry, tag("d", "sync-token"))
        segment = entry.href.rstrip("/").rsplit("/", 1)[-1]
        label = self.redact.label(segment, "cal")
        if name:
            self.redact.label(name, "Kalender")
        return Calendar(
            url=urljoin(self.home_url, entry.href),
            name=name,
            label=label,
            components=comps,
            writable=bool(privs & {"write", "write-content", "all"}),
            kinds=[k for k in kinds if k != "collection"],
            timezone=tz_el.text if tz_el is not None else None,
            ctag=ctag_el.text if ctag_el is not None else None,
            sync_token=sync_el.text if sync_el is not None else None,
        )

    def _supported_reports(self, entries: list[DavEntry]) -> set[str]:
        out: set[str] = set()
        for entry in entries:
            el = prop_ok(entry, tag("d", "supported-report-set"))
            if el is None:
                continue
            for report in el.iter(tag("d", "report")):
                out.update(child.tag.split("}")[-1] for child in report)
        return out

    def _anonymised_listing(self, text: str) -> str:
        root = ET.fromstring(text)
        for el in root.iter(tag("c", "calendar-timezone")):
            el.text = VTIMEZONE if el.text else el.text
        return ET.tostring(root, encoding="unicode")

    def _select_test_calendar(self) -> None:
        wanted = os.environ.get("CALDAV_TEST_CALENDAR")
        f = self.findings[2]
        if wanted:
            for c in self.calendars:
                path = urlsplit(c.url).path
                if wanted in (c.url, path, path.rstrip("/"), c.name):
                    if not (c.writable and "VEVENT" in c.components):
                        raise RuntimeError(
                            "CALDAV_TEST_CALENDAR ist nicht beschreibbar/kein VEVENT"
                        )
                    self.test_cal = c
                    f.note(f"Testkalender: vorhandener Kalender {c.label} (per Umgebung)")
                    return
            raise RuntimeError("CALDAV_TEST_CALENDAR nicht gefunden")
        url = self._make_calendar("Kairos AP0 Test")
        resp = self.dav.propfind(
            url,
            [
                "d:resourcetype",
                "d:displayname",
                "c:supported-calendar-component-set",
                "d:current-user-privilege-set",
                "c:calendar-timezone",
                "cs:getctag",
                "d:sync-token",
            ],
        )
        entries, _ = parse_multistatus(resp.text)
        self.test_cal = self._calendar_from(entries[0])
        self.test_cal.url = url
        f.note(
            f"Testkalender per MKCALENDAR angelegt ({self.test_cal.label}); calendar-timezone "
            f"{'gesetzt' if self.test_cal.timezone else 'fehlt'}"
        )

    def _make_calendar(self, name: str) -> str:
        url = urljoin(self.home_url, f"kairos-ap0-{uuid.uuid4().hex[:8]}/")
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:set><d:prop><d:displayname>{name}</d:displayname>"
            '<c:supported-calendar-component-set><c:comp name="VEVENT"/>'
            "</c:supported-calendar-component-set></d:prop></d:set></c:mkcalendar>"
        )
        resp = self.dav.request("MKCALENDAR", url, body)
        self.rec.response(f"02_mkcalendar_{len(self.created_calendars) + 1}.json", resp)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"MKCALENDAR → {resp.status_code}")
        self.created_calendars.append(url)
        return url

    # -- 13 Bibliothek (ohne Netz)

    def check_library_versions(self) -> None:
        f = self.findings[13]
        f.note(f"Python {sys.version.split()[0]}")
        for dist in (
            "caldav",
            "icalendar",
            "recurring-ical-events",
            "niquests",
            "urllib3-future",
            "urllib3",
            "lxml",
            "dnspython",
            "PyYAML",
            "httpx",
            "requests",
            "garminconnect",
            "litellm",
        ):
            try:
                f.note(f"{dist} {metadata.version(dist)}")
            except metadata.PackageNotFoundError:
                f.note(f"{dist} nicht installiert")
        shadow = _urllib3_shadowed()
        f.note(
            "urllib3 wird von urllib3-future überdeckt (gleicher Importname)"
            if shadow
            else "urllib3 wird nicht von urllib3-future überdeckt"
        )
        try:
            import kairos  # noqa: F401

            f.note("läuft in der Projektumgebung (kairos importierbar): Auflösung mit uv.lock ok")
        except ImportError:
            f.note("läuft außerhalb der Projektumgebung: Verträglichkeit nicht geprüft")
        check = subprocess.run(
            [sys.executable, "-m", "pip", "check"], capture_output=True, text=True, check=False
        )
        out = (check.stdout or check.stderr).strip().splitlines()
        f.note(f"pip check: {out[0] if out else 'keine Ausgabe'}" + (" …" if len(out) > 1 else ""))
        self.rec.add("13_pip_check.txt", "\n".join(out) + "\n")
        level = logging.getLogger("caldav").getEffectiveLevel()
        f.note(f"Logger 'caldav' auf {logging.getLevelName(level)}")

    # -- 5 sync-collection

    def sync_initial(self) -> None:
        assert self.test_cal is not None
        f = self.findings[5]
        opt = self.dav.request("OPTIONS", self.test_cal.url)
        self.rec.response("05_options.json", opt, body=False)
        f.note(f"OPTIONS DAV-Header: {opt.headers.get('dav', '-')}")
        f.note(f"getctag am Testkalender: {'vorhanden' if self.test_cal.ctag else 'fehlt'}")
        resp = self.dav.sync_collection(self.test_cal.url, "")
        self.rec.add("05_sync_initial.xml", self._own_only(resp.text, resp.status_code))
        if resp.status_code != 207:
            f.note(f"sync-collection (leerer Token) → {resp.status_code}")
            self._ok(5, "sync-collection nicht unterstützt.")
            return
        _, token = parse_multistatus(resp.text)
        self.initial_sync_token = token
        f.note(f"sync-collection (leerer Token) → 207, Token {'ja' if token else 'nein'}")

    def check_sync_delta(self) -> None:
        assert self.test_cal is not None
        f = self.findings[5]
        if not self.initial_sync_token:
            return
        resp = self.dav.sync_collection(self.test_cal.url, self.initial_sync_token)
        self.rec.add("05_sync_delta.xml", self._own_only(resp.text, resp.status_code))
        entries, token = parse_multistatus(resp.text) if resp.status_code == 207 else ([], None)
        own = [e for e in entries if UID_SUFFIX in e.href]
        gone = [e for e in own if e.status == 404]
        f.note(
            f"Delta nach Änderungen → {resp.status_code}, {len(own)} eigene Einträge, davon "
            f"{len(gone)} als gelöscht (404); neuer Token {'ja' if token else 'nein'}"
        )
        bad = self.dav.sync_collection(self.test_cal.url, "https://example.invalid/sync/0")
        self.rec.response("05_sync_invalid_token.json", bad)
        f.note(f"ungültiger Token → {bad.status_code}")
        resp = self.dav.propfind(self.test_cal.url, ["cs:getctag"])
        entries, _ = parse_multistatus(resp.text)
        ctag_el = prop_ok(entries[0], tag("cs", "getctag"))
        changed = ctag_el is not None and ctag_el.text != self.test_cal.ctag
        f.note(f"getctag nach Änderungen geändert: {'ja' if changed else 'nein'}")
        self._ok(
            5,
            f"sync-collection {'liefert Deltas inkl. Löschungen' if gone else 'liefert Deltas'}"
            f"; getctag {'ändert sich' if changed else 'unverändert/fehlt'}.",
        )

    def check_sync_token_lifetime(self) -> None:
        assert self.test_cal is not None
        if not self.initial_sync_token:
            return
        minutes = (time.monotonic() - self.started) / 60
        resp = self.dav.sync_collection(self.test_cal.url, self.initial_sync_token)
        self.findings[5].note(
            f"erster Token nach {minutes:.1f} min erneut benutzt → {resp.status_code} "
            "(Lebensdauer über Stunden/Tage hier nicht messbar)"
        )

    # -- 6 PUT

    def check_put(self) -> None:
        assert self.test_cal is not None
        f = self.findings[6]
        uid = f"{uuid.uuid4()}{UID_SUFFIX}"
        start = datetime.combine(self.day0 + timedelta(days=3), _t(18), _tz())
        ics = vcalendar(
            vevent(uid, "Einzeltermin", *_tz_lines(start, start + timedelta(hours=1))), tz=True
        )
        href = urljoin(self.test_cal.url, f"{uid}.ics")
        resp = self.dav.put_ics(href, ics, {"If-None-Match": "*"})
        self.rec.response("06_put_create.json", resp)
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"PUT → {resp.status_code}")
        location = resp.headers.get("location")
        actual = urljoin(href, location) if location else href
        self.created_hrefs[actual] = uid
        etag = resp.headers.get("etag")
        f.note(f"PUT mit If-None-Match: * → {resp.status_code}")
        f.note(
            "Location-Header: "
            + ("fehlt" if not location else ("gleich" if actual == href else "umgeschrieben"))
        )
        f.note(
            "ETag im Header: "
            + ("fehlt" if not etag else ("schwach (W/)" if etag.startswith("W/") else "stark"))
        )
        prop = self.dav.propfind(actual, ["d:getetag"])
        entries, _ = parse_multistatus(prop.text)
        el = prop_ok(entries[0], tag("d", "getetag"))
        prop_etag = el.text if el is not None else None
        f.note(f"PROPFIND getetag gleich Header-ETag: {'ja' if prop_etag == etag else 'nein'}")
        again = self.dav.put_ics(href, ics, {"If-None-Match": "*"})
        self.rec.response("06_put_conflict.json", again)
        f.note(f"zweiter PUT auf dieselbe Ressource mit If-None-Match: * → {again.status_code}")
        get = self.dav.request("GET", actual)
        self.rec.add("06_event_as_stored.ics", get.text)
        self.single = (actual, uid, ics, etag or prop_etag)
        self._ok(
            6,
            f"PUT {resp.status_code}; Location {'umgeschrieben' if actual != href else 'nicht'}"
            f"; ETag {'stark' if etag and not etag.startswith('W/') else 'schwach/fehlt'}; "
            f"Wiederholung {again.status_code}.",
        )

    # -- 7 DELETE

    def check_delete(self) -> None:
        f = self.findings[7]
        href, uid, ics, etag1 = self.single
        updated = ics.replace("Einzeltermin", "Einzeltermin (geändert)")
        upd = self.dav.put_ics(href, updated, {"If-Match": etag1} if etag1 else {})
        self.rec.response("07_put_update.json", upd)
        etag2 = upd.headers.get("etag") or self._etag(href)
        f.note(f"Änderung per PUT mit If-Match → {upd.status_code}")
        stale = self.dav.request("DELETE", href, headers={"If-Match": etag1 or '"stale"'})
        self.rec.response("07_delete_stale_etag.json", stale)
        f.note(f"DELETE mit veralteter ETag → {stale.status_code}")
        ok = self.dav.request("DELETE", href, headers={"If-Match": etag2} if etag2 else {})
        self.rec.response("07_delete.json", ok)
        f.note(f"DELETE mit aktueller ETag → {ok.status_code}")
        if ok.status_code in (200, 204):
            self.created_hrefs.pop(href, None)
        gone = self.dav.request("DELETE", href, headers={"If-Match": etag2} if etag2 else {})
        self.rec.response("07_delete_again_if_match.json", gone)
        plain = self.dav.request("DELETE", href)
        self.rec.response("07_delete_again.json", plain)
        f.note(f"erneutes DELETE: mit If-Match → {gone.status_code}, ohne → {plain.status_code}")
        self._ok(
            7,
            f"veraltete ETag → {stale.status_code}, gültig → {ok.status_code}, "
            f"schon gelöscht → {plain.status_code} (mit If-Match {gone.status_code}).",
        )

    def _etag(self, href: str) -> str | None:
        resp = self.dav.propfind(href, ["d:getetag"])
        if resp.status_code != 207:
            return None
        entries, _ = parse_multistatus(resp.text)
        el = prop_ok(entries[0], tag("d", "getetag"))
        return el.text if el is not None else None

    # -- 3/4 Serien

    def _series_instance(self, k: int) -> datetime:
        return self.series_start + timedelta(weeks=k)

    def check_series_query(self) -> None:
        assert self.test_cal is not None
        f = self.findings[3]
        override = self._series_instance(5)
        master = vevent(
            self.series_uid,
            "Serie",
            *_tz_lines(self.series_start, self.series_start + timedelta(hours=1)),
            "RRULE:FREQ=WEEKLY;COUNT=12",
        )
        moved = override.replace(hour=12)
        exception = vevent(
            self.series_uid,
            "Serie (verschoben)",
            f"RECURRENCE-ID;TZID={TZ_NAME}:{ical_local(override)}",
            *_tz_lines(moved, moved + timedelta(hours=1)),
        )
        ics = vcalendar(master, exception, tz=True)
        href = urljoin(self.test_cal.url, f"{self.series_uid}.ics")
        resp = self.dav.put_ics(href, ics, {"If-None-Match": "*"})
        self.rec.response("03_put_series.json", resp)
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"PUT Serie → {resp.status_code}")
        self.series_href = (
            urljoin(href, resp.headers["location"]) if "location" in resp.headers else href
        )
        self.created_hrefs[self.series_href] = self.series_uid
        f.note(
            f"Serie: Master {self.series_start:%Y-%m-%d %H:%M} ({TZ_NAME}), wöchentlich, "
            f"Fenster {self.window_start:%Y-%m-%d} bis {self.window_end:%Y-%m-%d}, "
            f"überschriebene Instanz {override:%Y-%m-%d}"
        )
        q = self.dav.query(self.test_cal.url, self.window_start, self.window_end)
        self.rec.add("03_query_series_window.xml", self._own_only(q.text, q.status_code))
        entries, _ = parse_multistatus(q.text) if q.status_code == 207 else ([], None)
        hit = [e for e in entries if e.href.endswith(f"{self.series_uid}.ics")]
        events = vevents(calendar_data(hit[0])) if hit else []
        has_rrule = any("RRULE" in ev for ev in events)
        has_override = any("RECURRENCE-ID" in ev for ev in events)
        f.note(
            f"calendar-query ohne expand → {q.status_code}; Serie geliefert: "
            f"{'ja' if hit else 'nein'}; Inhalt: {len(events)} VEVENT(s), RRULE "
            f"{'ja' if has_rrule else 'nein'}, Override {'ja' if has_override else 'nein'}"
        )
        self._ok(
            3,
            "Serie mit Master vor dem Fenster wird geliefert (Master + Overrides)."
            if hit
            else "Serie mit Master vor dem Fenster wird NICHT geliefert.",
        )

    def check_expand(self) -> None:
        assert self.test_cal is not None
        f = self.findings[4]
        q = self.dav.query(self.test_cal.url, self.window_start, self.window_end, expand=True)
        self.rec.add("04_query_expand_window.xml", self._own_only(q.text, q.status_code))
        events = self._series_events(q)
        rids = [ev for ev in events if "RECURRENCE-ID" in ev]
        moved = [ev for ev in events if any("verschoben" in s for s in ev.get("SUMMARY", []))]
        rrule = [ev for ev in events if "RRULE" in ev]
        utc_only = all(line.endswith("Z") for ev in events for line in ev.get("DTSTART", []))
        f.note(
            f"expand im Fenster → {q.status_code}; {len(events)} VEVENT(s) (erwartet 3 Instanzen), "
            f"mit RECURRENCE-ID {len(rids)}, Override enthalten {'ja' if moved else 'nein'}, "
            f"RRULE noch vorhanden {'ja' if rrule else 'nein'}, Zeiten in UTC "
            f"{'ja' if utc_only and events else 'nein'}"
        )
        first_start = self.series_start - timedelta(hours=2)
        q2 = self.dav.query(
            self.test_cal.url, first_start, first_start + timedelta(hours=4), expand=True
        )
        self.rec.add("04_query_expand_first_instance.xml", self._own_only(q2.text, q2.status_code))
        first = self._series_events(q2)
        first_rid = bool(first) and "RECURRENCE-ID" in first[0]
        first_rrule = bool(first) and "RRULE" in first[0]
        f.note(
            f"expand um die Erstinstanz → {len(first)} VEVENT(s); RECURRENCE-ID "
            f"{'ja' if first_rid else 'nein'}, RRULE {'ja' if first_rrule else 'nein'}"
        )
        if len(events) >= 3 and moved and not rrule:
            summary = "Server expandiert serverseitig, inkl. überschriebener Instanz."
        elif len(events) == 1 and rrule:
            summary = "Server ignoriert <C:expand> und liefert nur den Master."
        else:
            summary = (
                f"uneinheitlich ({len(events)} VEVENTs, Override {'ja' if moved else 'nein'})."
            )
        summary += f" Erstinstanz mit RECURRENCE-ID: {'ja' if first_rid else 'nein'}."
        self._ok(4, summary)

    def _series_events(self, resp: httpx.Response) -> list[dict[str, list[str]]]:
        if resp.status_code != 207:
            return []
        entries, _ = parse_multistatus(resp.text)
        out: list[dict[str, list[str]]] = []
        for e in entries:
            if e.href.endswith(f"{self.series_uid}.ics"):
                out.extend(vevents(calendar_data(e)))
        return out

    # -- 10 Zeittypen

    def check_time_kinds(self) -> None:
        assert self.test_cal is not None
        f = self.findings[10]
        d1 = self.day0 + timedelta(days=1)
        d2 = self.day0 + timedelta(days=2)
        tz_start = datetime.combine(d1, _t(9), _tz())
        self.tzid_uid = self._put_single(
            "TZID", *_tz_lines(tz_start, tz_start + timedelta(hours=1))
        )
        floating = datetime.combine(d1, _t(0, 30))
        floating_uid = self._put_single(
            "schwebend",
            f"DTSTART:{ical_local(floating)}",
            f"DTEND:{ical_local(floating + timedelta(hours=1))}",
        )
        allday_uid = self._put_single(
            "ganztägig",
            f"DTSTART;VALUE=DATE:{d2:%Y%m%d}",
            f"DTEND;VALUE=DATE:{d2 + timedelta(days=1):%Y%m%d}",
        )
        no_end_uid = f"{uuid.uuid4()}{UID_SUFFIX}"
        no_end = self.dav.put_ics(
            urljoin(self.test_cal.url, f"{no_end_uid}.ics"),
            vcalendar(
                vevent(no_end_uid, "ganztägig ohne DTEND", f"DTSTART;VALUE=DATE:{d2:%Y%m%d}")
            ),
            {"If-None-Match": "*"},
        )
        self.rec.response("10_put_allday_without_dtend.json", no_end)
        if no_end.status_code in (200, 201, 204):
            self.created_hrefs[urljoin(self.test_cal.url, f"{no_end_uid}.ics")] = no_end_uid
        f.note(f"ganztägig ohne DTEND anlegen → {no_end.status_code}")

        for name, uid in (
            ("tzid", self.tzid_uid),
            ("floating", floating_uid),
            ("allday", allday_uid),
        ):
            get = self.dav.request("GET", urljoin(self.test_cal.url, f"{uid}.ics"))
            self.rec.add(f"10_event_{name}.ics", get.text)
            ev = vevents(get.text)
            f.note(
                f"{name} zurückgelesen: DTSTART {';'.join(ev[0].get('DTSTART', [])) if ev else '-'}"
                f"; VTIMEZONE {'ja' if 'BEGIN:VTIMEZONE' in get.text else 'nein'}"
            )
        get = self.dav.request("GET", self.series_href)
        self.rec.add("10_series_tzid.ics", get.text)

        def hit(start: datetime, end: datetime, uid: str) -> bool:
            q = self.dav.query(self.test_cal.url, start, end)  # type: ignore[union-attr]
            entries, _ = parse_multistatus(q.text) if q.status_code == 207 else ([], None)
            return any(e.href.endswith(f"{uid}.ics") for e in entries)

        utc = UTC
        fl_utc = hit(
            datetime.combine(d1, _t(1), utc), datetime.combine(d1, _t(1, 20), utc), floating_uid
        )
        fl_berlin = hit(
            datetime.combine(d1, _t(0), _tz()) - timedelta(minutes=25),
            datetime.combine(d1, _t(0), _tz()),
            floating_uid,
        )
        ad_berlin = hit(
            datetime.combine(d2, _t(0), _tz()) - timedelta(minutes=50),
            datetime.combine(d2, _t(0), _tz()) - timedelta(minutes=10),
            allday_uid,
        )
        ad_utc = hit(
            datetime.combine(d2, _t(23, 10), utc), datetime.combine(d2, _t(23, 50), utc), allday_uid
        )
        f.note(
            f"time-range für schwebenden Termin: als UTC bewertet {'ja' if fl_utc else 'nein'}, "
            f"als {TZ_NAME} bewertet {'ja' if fl_berlin else 'nein'}"
        )
        f.note(
            f"time-range für Ganztagstermin: als UTC-Tag {'ja' if ad_utc else 'nein'}, "
            f"als {TZ_NAME}-Tag {'ja' if ad_berlin else 'nein'}"
        )
        tz_cals = sum(1 for c in self.calendars if c.timezone)
        f.note(f"calendar-timezone gesetzt bei {tz_cals} von {len(self.calendars)} Collections")
        self._ok(
            10,
            f"schwebend bewertet als {'UTC' if fl_utc else TZ_NAME if fl_berlin else '?'}, "
            f"ganztägig als {'UTC-Tag' if ad_utc else TZ_NAME + '-Tag' if ad_berlin else '?'}; "
            f"ohne DTEND → {no_end.status_code}.",
        )

    def _put_single(self, summary: str, *lines: str) -> str:
        assert self.test_cal is not None
        uid = f"{uuid.uuid4()}{UID_SUFFIX}"
        tz = any("TZID=" in line for line in lines)
        href = urljoin(self.test_cal.url, f"{uid}.ics")
        resp = self.dav.put_ics(
            href, vcalendar(vevent(uid, summary, *lines), tz=tz), {"If-None-Match": "*"}
        )
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"PUT {summary} → {resp.status_code}")
        self.created_hrefs[href] = uid
        return uid

    # -- 9 Gleiche UID

    def check_duplicate_uid(self) -> None:
        assert self.test_cal is not None
        f = self.findings[9]
        self.second_cal_url = self._make_calendar("Kairos AP0 Test 2")
        d1 = self.day0 + timedelta(days=1)
        start = datetime.combine(d1, _t(9), _tz())
        ics = vcalendar(
            vevent(self.tzid_uid, "UID-Dublette", *_tz_lines(start, start + timedelta(hours=1))),
            tz=True,
        )
        href = urljoin(self.second_cal_url, f"{self.tzid_uid}.ics")
        resp = self.dav.put_ics(href, ics, {"If-None-Match": "*"})
        self.rec.response("09_put_duplicate_uid.json", resp)
        accepted = resp.status_code in (200, 201, 204)
        if accepted:
            self.created_hrefs[href] = self.tzid_uid
        precondition = re.search(r"<[^>]*no-uid-conflict", resp.text) is not None
        f.note(
            f"PUT derselben UID in einen zweiten Kalender → {resp.status_code}; "
            f"Precondition no-uid-conflict {'ja' if precondition else 'nein'}"
        )
        self._ok(9, "abgelehnt." if not accepted else "angenommen (UID kann doppelt vorkommen).")
        self._ok(9, f"Status {resp.status_code}.")

    # -- 13 Bibliotheksverhalten

    def check_library_behaviour(self) -> None:
        assert self.test_cal is not None
        f = self.findings[13]
        import caldav

        client = caldav.DAVClient(url=self.server, username=self.username, password=self.password)
        t0 = time.monotonic()
        principal = client.principal()
        cals = principal.calendars()
        home = principal.calendar_home_set
        f.note(
            f"sync DAVClient: {len(cals)} Kalender in {time.monotonic() - t0:.1f} s; "
            f"Home-Set-Host {urlsplit(str(home.url)).netloc}; Client-URL-Host danach "
            f"{urlsplit(str(client.url)).netloc}"
        )
        cal = client.calendar(url=self.test_cal.url)
        found = cal.search(start=self.window_start, end=self.window_end, event=True, expand=True)
        own = [ev for ev in found if self.series_uid in (ev.data or "")]
        f.note(
            f"python-caldav search(expand=True) im Fenster: {len(own)} Serieninstanzen "
            "(erwartet 3, clientseitig expandiert)"
        )
        self.rec.add("13_client_expand_instances.ics", "\n".join(ev.data for ev in own if ev.data))

        async def aio_probe() -> tuple[int, float]:
            from caldav import aio

            t = time.monotonic()
            async with aio.AsyncDAVClient(
                url=self.server, username=self.username, password=self.password
            ) as aclient:
                p = await aclient.get_principal()
                acals = await p.get_calendars()
            return len(acals), time.monotonic() - t

        try:
            n, secs = asyncio.run(aio_probe())
            f.note(f"aio AsyncDAVClient: {n} Kalender in {secs:.1f} s")
            aio_ok = True
        except Exception as exc:
            f.note(f"aio AsyncDAVClient fehlgeschlagen: {type(exc).__name__}: {exc}")
            aio_ok = False
        self._ok(
            13,
            f"caldav {metadata.version('caldav')}; sync ok, "
            f"aio {'ok' if aio_ok else 'fehlerhaft'}; "
            f"clientseitige Expansion {len(own)}/3"
            + ("; urllib3-future überdeckt urllib3" if _urllib3_shadowed() else "")
            + ".",
        )

    # -- 12 EXDATE

    def check_exdate(self) -> None:
        assert self.test_cal is not None
        f = self.findings[12]
        get = self.dav.request("GET", self.series_href)
        etag = get.headers.get("etag") or self._etag(self.series_href)
        k4, k5 = self._series_instance(4), self._series_instance(5)
        exdate = f"EXDATE;TZID={TZ_NAME}:{ical_local(k4)},{ical_local(k5)}"
        new_ics = _add_exdate_drop_override(get.text, self.series_uid, exdate)
        stale = self.dav.put_ics(self.series_href, new_ics, {"If-Match": '"kairos-ap0-stale"'})
        self.rec.response("12_put_stale_etag.json", stale)
        f.note(f"PUT der geänderten Serie mit falscher ETag → {stale.status_code}")
        put = self.dav.put_ics(self.series_href, new_ics, {"If-Match": etag} if etag else {})
        self.rec.response("12_put_exdate.json", put)
        f.note(
            f"PUT mit EXDATE ({k4:%Y-%m-%d}, {k5:%Y-%m-%d}) und ohne Override → {put.status_code}"
        )
        after = self.dav.request("GET", self.series_href)
        self.rec.add("12_series_after_exdate.ics", after.text)
        events = vevents(after.text)
        master = [ev for ev in events if "RECURRENCE-ID" not in ev]
        ex_lines = master[0].get("EXDATE", []) if master else []
        ex_text = " ".join(ex_lines)
        both = ical_local(k4) in ex_text and ical_local(k5) in ex_text
        override_left = any("RECURRENCE-ID" in ev for ev in events)
        f.note(
            f"zurückgelesen: EXDATE-Zeilen {len(ex_lines)}, beide Daten enthalten "
            f"{'ja' if both else 'nein'}, TZID erhalten {'ja' if 'TZID=' in ex_text else 'nein'}, "
            f"Override entfernt {'ja' if not override_left else 'nein'}"
        )
        q = self.dav.query(self.test_cal.url, self.window_start, self.window_end, expand=True)
        self.rec.add("12_query_expand_after_exdate.xml", self._own_only(q.text, q.status_code))
        remaining = self._series_events(q)
        f.note(f"expand im Fenster danach: {len(remaining)} Instanz(en) (erwartet 1)")
        f.note(
            f"iPhone-Prüfung: am {k4:%d.%m.%Y} und {k5:%d.%m.%Y} darf „{SUMMARY_PREFIX} – Serie“ "
            f"nicht erscheinen, am {self._series_instance(6):%d.%m.%Y} 10:00 schon "
            "(nur mit --iphone-check vor dem Aufräumen sichtbar)"
        )
        ok = put.status_code in (200, 201, 204) and both and not override_left
        self._ok(
            12,
            "Server übernimmt die per PUT geänderte Serie (EXDATE, Override entfernt)"
            if ok
            else "Server übernimmt die Änderung NICHT vollständig",
            verdict="geklärt" if ok and len(remaining) == 1 else "teilweise",
        )
        self._ok(12, f"Instanzen im Fenster danach: {len(remaining)}; iPhone manuell.")

    # -- 11 Fehlercodes

    def check_errors(self) -> None:
        f = self.findings[11]
        wrong = "nicht geprüft"
        if not self.args.skip_bad_auth:
            bad = httpx.request(
                "PROPFIND",
                self.principal_url,
                auth=(self.username, self.password + "-falsch"),
                headers={"Depth": "0", "Content-Type": XML},
                content=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
                b"<d:current-user-principal/></d:prop></d:propfind>",
                timeout=30,
            )
            self.rec.response("11_wrong_password.json", bad)
            f.note(
                f"falsches Passwort → {bad.status_code}; WWW-Authenticate: "
                f"{bad.headers.get('www-authenticate', '-')}"
            )
            wrong = str(bad.status_code)
        throttled = [(m, s, r) for m, s, r in self.dav.statuses if s in (429, 503)]
        f.note(
            f"{len(self.dav.statuses)} Anfragen, Drosselung (429/503) beobachtet: "
            + (", ".join(f"{m} {s} Retry-After {r}" for m, s, r in throttled) or "nein")
        )
        f.note(
            "widerrufenes App-Passwort: manuell mit --auth-probe prüfen (Passwort unter "
            "appleid.apple.com widerrufen, Skript erneut mit dem alten Passwort aufrufen)"
        )
        f.note(
            "Konto ohne 2FA: nicht prüfbar, app-spezifische Passwörter setzen 2FA voraus "
            "(support.apple.com/102654)"
        )
        self._ok(
            11,
            f"falsches Passwort → {wrong}; "
            f"Drosselung {'beobachtet' if throttled else 'nicht beobachtet'}; Widerruf manuell.",
            verdict="teilweise",
        )

    # -- 8 Einladung

    def check_invite(self) -> None:
        assert self.test_cal is not None
        f = self.findings[8]
        f.note("Google (ohne sendUpdates) wird hier nicht geprüft, separat testen")
        if not self.args.invite_test:
            f.note(
                "nicht ausgeführt: Einladung von einem anderen Konto mit Titel "
                f"„{INVITE_MARKER}“ annehmen, in den Testkalender legen (CALDAV_TEST_CALENDAR) "
                "und das Skript mit --invite-test aufrufen"
            )
            self._ok(
                8, "nicht ausgeführt (braucht eine echte Einladung, --invite-test).", "manuell"
            )
            return
        if self.test_cal.url in self.created_calendars:
            raise RuntimeError("--invite-test braucht CALDAV_TEST_CALENDAR mit der Einladung")
        q = self.dav.query(
            self.test_cal.url,
            datetime.now(UTC) - timedelta(days=30),
            datetime.now(UTC) + timedelta(days=365),
        )
        entries, _ = parse_multistatus(q.text) if q.status_code == 207 else ([], None)
        invites = [
            e
            for e in entries
            if INVITE_MARKER in calendar_data(e) and "ORGANIZER" in calendar_data(e)
        ]
        if len(invites) != 1:
            raise RuntimeError(f"{len(invites)} Termine mit {INVITE_MARKER} gefunden, erwartet 1")
        invite = invites[0]
        data = calendar_data(invite)
        self.rec.add("08_invite_before_delete.ics", data)
        etag_el = prop_ok(invite, tag("d", "getetag"))
        href = urljoin(self.test_cal.url, invite.href)
        resp = self.dav.request(
            "DELETE",
            href,
            headers={"If-Match": etag_el.text} if etag_el is not None and etag_el.text else {},
        )
        self.rec.response("08_delete_invite.json", resp)
        f.note(
            f"eingeladenen Termin gelöscht → {resp.status_code}; SCHEDULE-AGENT im Termin "
            f"{'ja' if 'SCHEDULE-AGENT' in data else 'nein'}; Teilnehmer {data.count('ATTENDEE')}"
        )
        f.note("bitte im Postfach des Organisators prüfen, ob eine Absage ankam")
        self._ok(
            8, f"DELETE → {resp.status_code}; Absage beim Organisator manuell prüfen.", "manuell"
        )

    # -- Hilfen

    def _own_only(self, text: str, status: int) -> str:
        if status != 207:
            return text
        own_cal = self.test_cal is not None and self.test_cal.url in self.created_calendars
        if own_cal:
            return text
        return filter_multistatus(text, lambda href: UID_SUFFIX in href)

    def _iphone_pause(self) -> None:
        print(
            "\n[iPhone] Die Testserie liegt jetzt im Testkalender. Prüfe in der Kalender-App:\n"
            + "\n".join(f"  {line}" for line in self.findings[12].details if "iPhone" in line)
            + "\nEnter drückt das Aufräumen an …",
            file=sys.stderr,
        )
        with contextlib.suppress(EOFError):
            input()

    def cleanup(self) -> None:
        for href in list(self.created_hrefs):
            if any(href.startswith(c) for c in self.created_calendars):
                continue
            resp = self.dav.request("DELETE", href)
            if resp.status_code in (200, 204, 404):
                self.created_hrefs.pop(href)
            else:
                self.cleanup_notes.append(f"Termin nicht gelöscht ({resp.status_code})")
        for url in reversed(self.created_calendars):
            resp = self.dav.request("DELETE", url)
            check = self.dav.propfind(url, ["d:resourcetype"])
            if check.status_code != 404:
                self.cleanup_notes.append(
                    f"Kalender nicht entfernt (DELETE {resp.status_code}, "
                    f"danach {check.status_code})"
                )
        if self.test_cal is not None and self.test_cal.url not in self.created_calendars:
            q = self.dav.query(
                self.test_cal.url,
                self.series_start - timedelta(days=1),
                self.window_end + timedelta(days=60),
            )
            entries, _ = parse_multistatus(q.text) if q.status_code == 207 else ([], None)
            left = [e for e in entries if UID_SUFFIX in e.href]
            if left:
                self.cleanup_notes.append(f"{len(left)} eigene Termine noch vorhanden")

    def report(self) -> int:
        self.rec.add(
            "report.json",
            {
                "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                "findings": [f.__dict__ for f in self.findings.values()],
                "cleanup": self.cleanup_notes or ["ok"],
            },
        )
        if not self.args.no_fixtures:
            written = self.rec.flush(self.redact, Path(self.args.fixtures_dir))
        else:
            written = []
        lines = [
            f"# CalDAV AP 0 — Bericht ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)",
            "",
            "| # | Frage | Ergebnis | Befund |",
            "|---|---|---|---|",
        ]
        for n, f in self.findings.items():
            lines.append(f"| {n} | {QUESTIONS[n]} | {f.verdict} | {f.summary or '-'} |")
        lines += ["", "## Details", ""]
        for n, f in self.findings.items():
            lines.append(f"### {n}. {QUESTIONS[n]}")
            lines += [f"- {d}" for d in f.details] or ["- keine"]
            lines.append("")
        lines.append("## Aufräumen")
        lines += [f"- {n}" for n in self.cleanup_notes] or ["- alles Angelegte entfernt"]
        lines.append("")
        lines.append(
            f"Fixtures: {len(written)} Dateien in {self.args.fixtures_dir}"
            if written
            else "Fixtures: keine geschrieben"
        )
        print(self.redact("\n".join(lines)))
        failed = any(f.verdict == "fehler" for f in self.findings.values()) or self.cleanup_notes
        return 1 if failed else 0


def _t(hour: int, minute: int = 0) -> Any:
    return datetime.min.replace(hour=hour, minute=minute).time()


def _tz_lines(start: datetime, end: datetime) -> tuple[str, str]:
    return (
        f"DTSTART;TZID={TZ_NAME}:{ical_local(start)}",
        f"DTEND;TZID={TZ_NAME}:{ical_local(end)}",
    )


def _add_exdate_drop_override(ics: str, uid: str, exdate: str) -> str:
    out: list[str] = []
    block: list[str] = []
    in_event = False
    for line in unfold(ics):
        if line == "BEGIN:VEVENT":
            in_event, block = True, [line]
            continue
        if in_event:
            block.append(line)
            if line == "END:VEVENT":
                in_event = False
                if any(b.startswith("RECURRENCE-ID") for b in block):
                    continue
                if any(b == f"UID:{uid}" for b in block):
                    block.insert(-1, exdate)
                out.extend(block)
            continue
        out.append(line)
    return "\r\n".join(out) + "\r\n"


def _urllib3_shadowed() -> bool:
    try:
        files = metadata.files("urllib3-future") or []
    except metadata.PackageNotFoundError:
        return False
    return any(str(p).replace("\\", "/") == "urllib3/__init__.py" for p in files)


def auth_probe(username: str, password: str, args: argparse.Namespace) -> int:
    server = os.environ.get("CALDAV_SERVER_URL", DEFAULT_SERVER).rstrip("/") + "/"
    resp = Dav(username, password).propfind(server, ["d:current-user-principal"])
    redact = Redactor(username, password)
    rec = Recorder()
    rec.response("11_auth_probe.json", resp)
    if not args.no_fixtures:
        rec.flush(redact, Path(args.fixtures_dir))
    print(
        redact(
            f"Anmeldeprobe → {resp.status_code}; WWW-Authenticate: "
            f"{resp.headers.get('www-authenticate', '-')}"
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CalDAV AP 0 gegen iCloud")
    parser.add_argument("--fixtures-dir", default=str(FIXTURE_DIR))
    parser.add_argument("--no-fixtures", action="store_true", help="nichts speichern")
    parser.add_argument(
        "--skip-bad-auth", action="store_true", help="kein Test mit falschem Passwort"
    )
    parser.add_argument(
        "--iphone-check", action="store_true", help="vor dem Aufräumen auf Enter warten"
    )
    parser.add_argument(
        "--invite-test", action="store_true", help=f"Termin „{INVITE_MARKER}“ löschen (Punkt 8)"
    )
    parser.add_argument(
        "--auth-probe", action="store_true", help="nur Anmeldestatus prüfen (Punkt 11, Widerruf)"
    )
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if "PYTHON_CALDAV_COMMDUMP" in os.environ:
        sys.exit(
            "PYTHON_CALDAV_COMMDUMP ist gesetzt; das schreibt Zugangsdaten in Dateien. Abbruch."
        )
    missing = [n for n in ("ICLOUD_USERNAME", "ICLOUD_APP_PASSWORD") if not os.environ.get(n)]
    if missing:
        sys.exit(f"Fehlende Umgebungsvariablen: {', '.join(missing)}")
    for name in ("caldav", "httpx", "httpcore", "niquests", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    username = os.environ["ICLOUD_USERNAME"]
    password = os.environ["ICLOUD_APP_PASSWORD"]
    if args.auth_probe:
        return auth_probe(username, password, args)
    try:
        import caldav  # noqa: F401
    except ImportError:
        sys.exit("python-caldav fehlt: uv run --with caldav==3.5.0 python scripts/caldav_verify.py")
    return Verifier(args, username, password).run()


if __name__ == "__main__":
    sys.exit(main())
