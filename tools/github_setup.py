"""Create the private GitHub repo and set the iOS workflow's Actions secrets via the REST API (no gh CLI).

Inputs come from the environment; secret values are read from files and never printed:
  GITHUB_TOKEN        token with repo + secrets write access for the sshaner account
  P12_PATH            distribution .p12 (default C:\\Dev\\.Apple\\shanr-distribution.p12)
  P12_PASSWORD        its password
  PROFILE_PATH        provisioning profile (default C:\\Dev\\.Apple\\ArbScanner.mobileprovision)
  ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH   App Store Connect API key

Usage:  python tools/github_setup.py [--repo sshaner/kalshi-arb] [--skip-create]
"""
import argparse
import base64
import os
import sys
from pathlib import Path

import httpx
from nacl import encoding, public

API = "https://api.github.com"


def gh() -> httpx.Client:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set GITHUB_TOKEN")
    return httpx.Client(base_url=API, timeout=30, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})


def ensure_repo(c: httpx.Client, full: str) -> None:
    if c.get(f"/repos/{full}").status_code == 200:
        print(f"repo {full} exists")
        return
    owner, name = full.split("/")
    r = c.post("/user/repos", json={"name": name, "private": True,
                                    "description": "Kalshi <-> Polymarket US arbitrage scanner + iOS app"})
    if r.status_code >= 300:
        sys.exit(f"create repo failed: HTTP {r.status_code} {r.text[:200]}")
    print(f"created private repo {full}")


def set_secret(c: httpx.Client, full: str, key: dict, name: str, value: str) -> None:
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    encrypted = base64.b64encode(box.encrypt(value.encode())).decode()
    r = c.put(f"/repos/{full}/actions/secrets/{name}", json={"encrypted_value": encrypted, "key_id": key["key_id"]})
    if r.status_code not in (201, 204):
        sys.exit(f"secret {name}: HTTP {r.status_code} {r.text[:200]}")
    print(f"set secret {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="sshaner/kalshi-arb")
    ap.add_argument("--skip-create", action="store_true")
    args = ap.parse_args()
    env = os.environ
    p12 = Path(env.get("P12_PATH", r"C:\Dev\.Apple\shanr-distribution.p12"))
    profile = Path(env.get("PROFILE_PATH", r"C:\Dev\.Apple\ArbScanner.mobileprovision"))
    missing = [k for k in ("P12_PASSWORD", "ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_PATH") if not env.get(k)]
    missing += [str(f) for f in (p12, profile) if not f.exists()]
    if missing:
        sys.exit(f"missing: {', '.join(missing)}")

    c = gh()
    if not args.skip_create:
        ensure_repo(c, args.repo)
    key = c.get(f"/repos/{args.repo}/actions/secrets/public-key").json()
    secrets = {
        "BUILD_CERTIFICATE_BASE64": base64.b64encode(p12.read_bytes()).decode(),
        "P12_PASSWORD": env["P12_PASSWORD"],
        "PROVISIONING_PROFILE_BASE64": base64.b64encode(profile.read_bytes()).decode(),
        "ASC_KEY_ID": env["ASC_KEY_ID"],
        "ASC_ISSUER_ID": env["ASC_ISSUER_ID"],
        "ASC_API_KEY_P8": Path(env["ASC_KEY_PATH"]).read_text(),
    }
    for name, value in secrets.items():
        set_secret(c, args.repo, key, name, value)


if __name__ == "__main__":
    main()
