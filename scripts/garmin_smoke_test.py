"""
Interaktiver Smoke-Test: Garmin Login + neueste Aktivität als FIT-Datei herunterladen.

Verwendung:
    .venv/bin/python scripts/garmin_smoke_test.py
"""

from __future__ import annotations

import getpass
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path


def _require(module_name: str) -> object:
    import importlib

    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        sys.exit(f"[FEHLER] Modul '{module_name}' nicht gefunden. Bitte '.venv/bin/pip install {module_name}' ausführen.")


def _extract_fit_from_zip(data: bytes) -> bytes:
    """Return the first .fit file from a ZIP archive, or the raw bytes if not a ZIP."""
    if not data[:2] == b"PK":
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not fit_names:
            sys.exit("[FEHLER] ZIP enthält keine .fit-Datei.")
        return zf.read(fit_names[0])


def _fresh_login(gc: object) -> object:
    print("\n[1/3] Login …")
    email = input("E-Mail: ").strip()
    password = getpass.getpass("Passwort: ")
    garmin = gc.Garmin(email=email, password=password, return_on_mfa=True)  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory() as tmpdir:
        result = garmin.login(tmpdir)
        if isinstance(result, tuple) and result[0] == "needs_mfa":
            mfa_code = input("MFA-Code: ").strip()
            garmin.resume_login(result[1], mfa_code)
        garmin.client.dump(tmpdir)
        token_json = (Path(tmpdir) / "garmin_tokens.json").read_text()
    print(f"  Login OK  (Token-Länge: {len(token_json)} Zeichen)")
    return garmin


def main() -> None:
    gc = _require("garminconnect")
    fit_sdk = _require("garmin_fit_sdk")

    print("=== Garmin Smoke-Test ===\n")

    # ── Login oder gespeicherten Token wiederverwenden ───────────────────────
    saved_token = Path("garmin_tokens_smoke.json")
    if saved_token.exists():
        print(f"  Gespeicherter Token gefunden: {saved_token}")
        reuse = input("  Token wiederverwenden (kein erneuter Login)? [J/n] ").strip().lower()
        if reuse != "n":
            print("\n[1/3] Token-Login …")
            garmin = gc.Garmin()  # type: ignore[attr-defined]
            garmin.login(saved_token.read_text())
            print("  Token-Login OK")
        else:
            garmin = _fresh_login(gc)
    else:
        garmin = _fresh_login(gc)

    # ── Neueste Aktivität abrufen ─────────────────────────────────────────────
    print("\n[2/3] Neueste Aktivitäten abrufen …")
    activities = garmin.get_activities(0, 5)
    if not activities:
        print("  Keine Aktivitäten gefunden.")
        sys.exit(0)

    latest = activities[0]
    activity_id = latest.get("activityId") or latest.get("activity_id")
    name = latest.get("activityName", "<kein Name>")
    date = latest.get("startTimeLocal", "?")
    print(f"  Aktivität: {name}  |  Datum: {date}  |  ID: {activity_id}")

    # ── FIT-Datei herunterladen und decodieren ────────────────────────────────
    print("\n[3/3] FIT-Datei herunterladen und decodieren …")
    raw: bytes = garmin.download_activity(activity_id, dl_fmt=gc.Garmin.ActivityDownloadFormat.ORIGINAL)  # type: ignore[attr-defined]
    print(f"  Download: {len(raw)} Bytes")

    # ORIGINAL liefert eine ZIP-Datei, die eine oder mehrere .fit-Dateien enthält.
    fit_bytes = _extract_fit_from_zip(raw)
    print(f"  FIT extrahiert: {len(fit_bytes)} Bytes")

    stream = fit_sdk.Stream.from_byte_array(fit_bytes)  # type: ignore[attr-defined]
    decoder = fit_sdk.Decoder(stream)  # type: ignore[attr-defined]
    messages, errors = decoder.read()

    if errors:
        print(f"  [WARNUNG] Decode-Fehler: {errors}")

    record_count = len(messages.get("record_mesgs", []))
    session_msgs = messages.get("session_mesgs", [{}])
    sport = session_msgs[0].get("sport", "?") if session_msgs else "?"
    print(f"  Sport: {sport}  |  Records: {record_count}")
    print(f"\n  Verfügbare Message-Typen: {sorted(messages.keys())}\n")

    print("[OK] Smoke-Test abgeschlossen.")

    # Optional: frischen Token speichern (nach Token-Login nicht nötig)
    save = input("Token lokal speichern/aktualisieren? [j/N] ").strip().lower()
    if save == "j":
        out = Path("garmin_tokens_smoke.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            garmin.client.dump(tmpdir)  # type: ignore[attr-defined]
            token_json = (Path(tmpdir) / "garmin_tokens.json").read_text()
        out.write_text(token_json)
        print(f"  Gespeichert: {out.resolve()}")
        print("  (Nicht committen — steht in .gitignore)")


if __name__ == "__main__":
    main()
