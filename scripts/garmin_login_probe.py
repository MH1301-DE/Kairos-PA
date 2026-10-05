"""One-shot probe of Garmin's SSO login endpoints (same requests garminconnect sends).

Uses a dummy account by default so a real account can't get locked:
  429 -> rate-limited (JSON body with request-id = Garmin-side, not your IP)
  403 -> Cloudflare bot challenge (TLS fingerprint / IP reputation)
  mobile: 200/401 with JSON -> endpoint reachable
  widget: <title> "Success"/"invalid"/"locked" -> endpoint reachable

Usage: .venv/Scripts/python scripts/garmin_login_probe.py [--flow mobile|widget]
                                                          [--email x --password y]
"""

import argparse
import re
from typing import Any

from curl_cffi import requests

SSO = "https://sso.garmin.com"


def _report(r: Any) -> None:
    print(f"HTTP {r.status_code}  {r.request.method} {r.url.split('?')[0]}")
    for h in ("cf-ray", "cf-mitigated", "retry-after", "server", "content-type"):
        if h in r.headers:
            print(f"  {h}: {r.headers[h]}")


def probe_mobile(email: str, password: str, impersonate: str) -> None:
    sess = requests.Session(impersonate=impersonate)
    r = sess.post(
        f"{SSO}/mobile/api/login",
        params={
            "clientId": "GCM_IOS_DARK",
            "locale": "en-US",
            "service": "https://mobile.integration.garmin.com/gcm/ios",
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": SSO,
        },
        json={"username": email, "password": password, "rememberMe": True, "captchaToken": ""},
        timeout=30,
    )
    _report(r)
    print(r.text[:500])


def probe_widget(email: str, password: str) -> None:
    sess = requests.Session(impersonate="chrome", timeout=30)
    sso_base = f"{SSO}/sso"
    embed = f"{sso_base}/embed"
    embed_params = {"id": "gauth-widget", "embedWidget": "true", "gauthHost": sso_base}
    signin_params = {
        **embed_params,
        "gauthHost": embed,
        "service": embed,
        "source": embed,
        "redirectAfterAccountLoginUrl": embed,
        "redirectAfterAccountCreationUrl": embed,
    }

    r = sess.get(embed, params=embed_params)
    _report(r)
    if not r.ok:
        print(r.text[:500])
        return

    r = sess.get(f"{sso_base}/signin", params=signin_params, headers={"Referer": embed})
    _report(r)
    csrf = re.search(r'name="_csrf"\s+value="([^"]+)"', r.text)
    if not csrf:
        print("no CSRF token in signin page:")
        print(r.text[:500])
        return

    r = sess.post(
        f"{sso_base}/signin",
        params=signin_params,
        headers={"Referer": r.url},
        data={"username": email, "password": password, "embed": "true", "_csrf": csrf.group(1)},
        timeout=30,
    )
    _report(r)
    title = re.search(r"<title>(.*?)</title>", r.text, re.S)
    print(f"  <title>: {title.group(1).strip() if title else '(none)'}")
    if not title:
        print(r.text[:500])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow", choices=("mobile", "widget"), default="mobile")
    parser.add_argument("--impersonate", default="safari_ios", help="mobile flow only")
    parser.add_argument("--email", default="kairos-probe@example.invalid")
    parser.add_argument("--password", default="not-a-real-password")
    args = parser.parse_args()

    if args.flow == "mobile":
        probe_mobile(args.email, args.password, args.impersonate)
    else:
        probe_widget(args.email, args.password)


if __name__ == "__main__":
    main()
