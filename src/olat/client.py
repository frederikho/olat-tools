"""Paths, constants and HTTP access to the OpenOlat REST API.

The API accepts the session cookie of a logged-in browser session (Basic auth with the VCRP-issued ClientID/Secret is rejected, see the
CLAUDE.md of the course folder). The cookie lives in the 'Cookie=' line of the credentials file in the repo root; it is never printed.
"""
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# --- paths (everything relative to the repo root = the folder that holds pyproject.toml) -------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS = ROOT / "OpenOlat API Credentials.env"      # git-ignored; the agent never reads it
PRIVATE_DIR = ROOT / "private_downloads"                 # full student data; the agent never reads it
ANON_DIR = ROOT / "anonymized"                           # anonymised copies; the agent may read these
LOG_FILE = ROOT / "olat_check.log"
FIREFOX_PROFILE = Path("/mnt/c/Users/frederik-msi/AppData/Roaming/Mozilla/Firefox/Profiles/40oesw6i.default-release")

# --- constants -------------------------------------------------------------------------------------------------------------------
BASE = "https://olat.vcrp.de/restapi"
ORG_KEY = 5      # organisation RPTU; without it imports land in the default organisation (key 1), where the user has no author role -> 403


class CookieMissing(RuntimeError):
    pass


# --- credentials file (only the Cookie line is used or written here) -------------------------------------------------------------
def _read_lines():
    if not CREDENTIALS.exists():
        return []
    return [line.rstrip("\n") for line in open(CREDENTIALS, encoding="utf-8-sig")]


def cookie():
    for line in _read_lines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip().lower() == "cookie" and value.strip():
            return value.strip().strip('"').strip("'")
    raise CookieMissing("No 'Cookie=' line in the credentials file (run: olat check).")


def set_cookie(value):
    """Replaces the Cookie line, keeps every other line of the file untouched."""
    lines = [l for l in _read_lines() if not l.strip().lower().startswith("cookie=")]
    lines.append("Cookie=" + value)
    CREDENTIALS.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- HTTP ------------------------------------------------------------------------------------------------------------------------
def request(method, path, data=None, content_type=None, accept="application/json", timeout=60):
    """Returns (status, body bytes). HTTP errors are returned, not raised; timeouts and network errors are raised.

    Requests are serialised per OLAT session: a slow call blocks every other call with the same cookie, so keep the timeouts short
    and never retry in a loop.
    """
    headers = {"Cookie": cookie(), "Accept": accept}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def get_json(path, timeout=60):
    status, body = request("GET", path, timeout=timeout)
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body[:200].decode("utf-8", "replace")


def multipart(fields, file_field, file_path):
    """Builds a multipart/form-data body. Returns (content_type_header, body bytes)."""
    boundary = "----olat" + uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    path = Path(file_path)
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 "Content-Type: application/zip\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)
