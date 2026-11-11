"""Session handling: read the OLAT cookies from the running Firefox and check that the session is valid.

Firefox keeps session cookies (no expiry date, e.g. JSESSIONID and the Shibboleth cookie) only in sessionstore-backups/recovery.jsonlz4,
not in cookies.sqlite. That file is mozLz4 (LZ4 block format); the 'lz4' module is not installed, so a small decoder is included.
Cookie values are never printed.
"""
import datetime
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.error

from . import client

OLAT_HOSTS = ("olat.vcrp.de", ".olat.vcrp.de")

# exit codes of `olat check`
OK, EXPIRED, BLOCKED, OTHER = 0, 10, 11, 12


# --- Firefox session store -------------------------------------------------------------------------------------------------------
def lz4_block_decompress(src, size):
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        literal = token >> 4
        if literal == 15:
            while True:
                b = src[i]
                i += 1
                literal += b
                if b != 255:
                    break
        out += src[i:i + literal]
        i += literal
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        match = token & 15
        if match == 15:
            while True:
                b = src[i]
                i += 1
                match += b
                if b != 255:
                    break
        match += 4
        start = len(out) - offset
        for k in range(match):                    # byte-wise copy handles overlapping matches
            out.append(out[start + k])
    return bytes(out)


def _session_file():
    return client.FIREFOX_PROFILE / "sessionstore-backups" / "recovery.jsonlz4"


def firefox_session_age():
    """Seconds since Firefox last wrote its session file (None if the file is missing)."""
    path = _session_file()
    return time.time() - os.path.getmtime(path) if path.exists() else None


def read_firefox_cookies():
    """{name: value} of the olat.vcrp.de cookies in Firefox's session store."""
    with tempfile.TemporaryDirectory() as tmp:     # copy first: Firefox keeps the original open
        local = os.path.join(tmp, "recovery.jsonlz4")
        shutil.copy(_session_file(), local)
        raw = open(local, "rb").read()
    if raw[:8] != b"mozLz40\0":
        raise RuntimeError("unexpected session store format")
    data = json.loads(lz4_block_decompress(raw[12:], struct.unpack("<I", raw[8:12])[0]))
    cookies = {}

    def collect(items):
        for c in items or []:
            if c.get("host") in OLAT_HOSTS:
                cookies[c["name"]] = c["value"]

    collect(data.get("cookies"))
    for window in data.get("windows", []) + data.get("_closedWindows", []):
        collect(window.get("cookies"))
    return cookies


def refresh_cookie():
    """Copies the current Firefox cookies into the credentials file. Returns the cookie NAMES (never the values)."""
    cookies = read_firefox_cookies()
    if not cookies:
        raise RuntimeError("no olat.vcrp.de cookies in the Firefox session store (log in to OLAT in Firefox first)")
    client.set_cookie("; ".join(f"{k}={v}" for k, v in cookies.items()))
    return sorted(cookies)


# --- session check ---------------------------------------------------------------------------------------------------------------
def network_state():
    """Names of the active Windows network adapters (virtual WSL/Hyper-V ones left out) - a VPN shows up here."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object { $_.Name }"],
            capture_output=True, text=True, timeout=20).stdout
        names = [n.strip() for n in out.replace("\r", "").splitlines() if n.strip() and "vEthernet" not in n]
        return ", ".join(names) if names else "none"
    except Exception:
        return "unknown"


def _log(verdict, adapters, age):
    """Appends to olat_check.log (no secrets) so that VPN/session patterns can be analysed later."""
    try:
        with open(client.LOG_FILE, "a") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {verdict} | adapters: {adapters} | "
                    f"session file age: {'' if age is None else f'{age:.0f}s'}\n")
    except OSError:
        pass


def check():
    """Refreshes the cookie and calls GET /users/me with a 10 s timeout. Prints one verdict line, returns the exit code.

    0 OK       session valid
    10 EXPIRED 401 -> the user must reload an OLAT page in Firefox (log in again), wait ~15 s, rerun
    11 BLOCKED timeout -> an earlier slow request still holds the session; wait a few minutes, do not retry in a loop
    12 OTHER   anything else (403, 5xx, network error, no cookies)
    """
    age = firefox_session_age()
    adapters = network_state()
    print(f"network adapters up: {adapters}")
    try:
        refresh_cookie()
    except Exception as err:
        print(f"COOKIE: could not read the Firefox cookies: {err}"[:200])
        return OTHER
    note = f", Firefox session file written {age:.0f}s ago" if age is not None else ""
    started = time.time()
    try:
        status, _ = client.request("GET", "/users/me", timeout=10)
    except Exception as err:
        if "timed out" in str(err).lower() or isinstance(err, TimeoutError):
            print(f"BLOCKED: timeout -> an earlier slow request holds the session; wait a few minutes{note}")
            _log("BLOCKED timeout", adapters, age)
            return BLOCKED
        print(f"OTHER: {type(err).__name__}{note}")
        return OTHER
    if status == 200:
        print(f"OK: session valid ({time.time() - started:.2f}s){note}")
        _log("OK", adapters, age)
        return OK
    if status == 401:
        print(f"EXPIRED: 401 -> reload an OLAT page in Firefox (log in), wait ~15 s, rerun{note}")
        _log("EXPIRED 401", adapters, age)
        return EXPIRED
    print(f"OTHER: HTTP {status}{note}")
    return OTHER
