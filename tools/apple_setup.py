"""One-shot App Store Connect setup for Arb Scanner, via the App Store Connect API.

Does what Apple's API allows:
  1. create the bundle ID org.shnr.arbscanner (if missing) and enable Push Notifications
  2. create/refresh the "Arb Scanner App Store" provisioning profile against the existing distribution cert,
     saving it to C:\\Dev\\.Apple\\ArbScanner.mobileprovision
  3. (--testflight, after the app record exists) create an internal TestFlight group and add a tester

Apple's API cannot create the App Store Connect app record or an APNs auth key; those are done in the web UI.

Credentials come from the environment and are never printed:
  ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH (path to the AuthKey_XXXX.p8)

Usage (Git Bash):
  python tools/apple_setup.py                      # steps 1-2
  python tools/apple_setup.py --testflight --tester-email you@example.com --first Shiloh --last Shaner
"""
import argparse
import base64
import os
import sys
import time
from pathlib import Path

import httpx
import jwt

API = "https://api.appstoreconnect.apple.com/v1"
BUNDLE_ID = "org.shnr.arbscanner"
APP_NAME = "Arb Scanner"
PROFILE_NAME = "Arb Scanner App Store"
PROFILE_OUT = Path(r"C:\Dev\.Apple\ArbScanner.mobileprovision")
GROUP_NAME = "Internal"


def client() -> httpx.Client:
    key_id, issuer, key_path = (os.environ.get(k) for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_PATH"))
    if not (key_id and issuer and key_path):
        sys.exit("Set ASC_KEY_ID, ASC_ISSUER_ID and ASC_KEY_PATH")
    token = jwt.encode(
        {"iss": issuer, "iat": int(time.time()), "exp": int(time.time()) + 15 * 60, "aud": "appstoreconnect-v1"},
        Path(key_path).read_text(), algorithm="ES256", headers={"kid": key_id, "typ": "JWT"},
    )
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        errors = r.json().get("errors", [{}]) if r.headers.get("content-type", "").startswith("application/json") else []
        detail = "; ".join(f"{e.get('title')}: {e.get('detail')}" for e in errors) or r.text[:300]
        sys.exit(f"{r.request.method} {r.request.url.path} -> HTTP {r.status_code}: {detail}")
    return r.json() if r.content else {}


def ensure_bundle_id(c: httpx.Client) -> str:
    data = check(c.get("/bundleIds", params={"filter[identifier]": BUNDLE_ID}))["data"]
    match = [b for b in data if b["attributes"]["identifier"] == BUNDLE_ID]
    if match:
        bid = match[0]["id"]
        print(f"bundle ID {BUNDLE_ID} exists")
    else:
        bid = check(c.post("/bundleIds", json={"data": {"type": "bundleIds", "attributes": {
            "identifier": BUNDLE_ID, "name": APP_NAME, "platform": "IOS"}}}))["data"]["id"]
        print(f"created bundle ID {BUNDLE_ID}")
    caps = check(c.get(f"/bundleIds/{bid}/bundleIdCapabilities"))["data"]
    if any(x["attributes"]["capabilityType"] == "PUSH_NOTIFICATIONS" for x in caps):
        print("push capability already enabled")
    else:
        check(c.post("/bundleIdCapabilities", json={"data": {
            "type": "bundleIdCapabilities", "attributes": {"capabilityType": "PUSH_NOTIFICATIONS"},
            "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bid}}}}}))
        print("enabled push capability")
    return bid


def distribution_cert(c: httpx.Client) -> str:
    certs = check(c.get("/certificates", params={"limit": 200}))["data"]
    dist = [x for x in certs if x["attributes"]["certificateType"] in ("DISTRIBUTION", "IOS_DISTRIBUTION")]
    if not dist:
        sys.exit("No Apple Distribution certificate on the account")
    best = max(dist, key=lambda x: x["attributes"].get("expirationDate") or "")
    print(f"using distribution cert '{best['attributes'].get('name')}' expiring {best['attributes'].get('expirationDate')}")
    return best["id"]


def ensure_profile(c: httpx.Client, bundle_pk: str, cert_id: str) -> None:
    existing = check(c.get("/profiles", params={"filter[name]": PROFILE_NAME, "limit": 50}))["data"]
    for p in existing:
        # Profiles are bound to the cert/capabilities at creation; recreate so it always matches the current ones.
        check(c.delete(f"/profiles/{p['id']}"))
        print("deleted old profile")
    prof = check(c.post("/profiles", json={"data": {
        "type": "profiles", "attributes": {"name": PROFILE_NAME, "profileType": "IOS_APP_STORE"},
        "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle_pk}},
                          "certificates": {"data": [{"type": "certificates", "id": cert_id}]}}}}))["data"]
    PROFILE_OUT.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_OUT.write_bytes(base64.b64decode(prof["attributes"]["profileContent"]))
    print(f"created profile '{PROFILE_NAME}' -> {PROFILE_OUT}")


def testflight(c: httpx.Client, email: str, first: str, last: str) -> None:
    apps = check(c.get("/apps", params={"filter[bundleId]": BUNDLE_ID}))["data"]
    if not apps:
        sys.exit(f"No App Store Connect app for {BUNDLE_ID} yet — create the app record first")
    app_id = apps[0]["id"]
    groups = check(c.get(f"/apps/{app_id}/betaGroups"))["data"]
    group = next((g for g in groups if g["attributes"]["name"] == GROUP_NAME), None)
    if group is None:
        group = check(c.post("/betaGroups", json={"data": {
            "type": "betaGroups", "attributes": {"name": GROUP_NAME, "isInternalGroup": True,
                                                 "hasAccessToAllBuilds": True},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}}))["data"]
        print(f"created internal TestFlight group '{GROUP_NAME}'")
    testers = check(c.get("/betaTesters", params={"filter[email]": email}))["data"]
    if testers:
        check(c.post(f"/betaGroups/{group['id']}/relationships/betaTesters",
                     json={"data": [{"type": "betaTesters", "id": testers[0]["id"]}]}))
    else:
        check(c.post("/betaTesters", json={"data": {
            "type": "betaTesters", "attributes": {"email": email, "firstName": first, "lastName": last},
            "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": group["id"]}]}}}}))
    print(f"tester {email} is in '{GROUP_NAME}' (internal testers must be App Store Connect users)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testflight", action="store_true")
    ap.add_argument("--tester-email")
    ap.add_argument("--first", default="")
    ap.add_argument("--last", default="")
    args = ap.parse_args()
    c = client()
    if args.testflight:
        if not args.tester_email:
            sys.exit("--tester-email is required with --testflight")
        testflight(c, args.tester_email, args.first, args.last)
        return
    bundle_pk = ensure_bundle_id(c)
    ensure_profile(c, bundle_pk, distribution_cert(c))


if __name__ == "__main__":
    main()
