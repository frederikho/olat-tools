"""Test results with answer texts: course archive via REST, then an anonymised copy of each results Excel.

PRIVACY (the rules of the course-folder CLAUDE.md): student data goes from OLAT straight to disk and never through the chat.
 - The archive zip is processed in memory and never written to disk.
 - Only the per-test results Excel (<node>/Resultate/<test>.xlsx) is kept, in PRIVATE_DIR (mode 600). The agent must never read it.
 - The anonymised copies in ANON_DIR may be read by the agent. Everything here prints only status, counts and header names.

The archive covers EVERY test node of the course (no per-node choice) and is built asynchronously on the server (~1 min for EnvCBA).
The archive entry stays on the OLAT server afterwards (no delete endpoint) - the user removes it in the course.
"""
import io
import json
import os
import re
import time
import warnings
import zipfile
from pathlib import Path

from . import client

# Columns removed from the anonymised copy, matched by header text (not by position) in EVERY sheet ('Abdeckung Resultate' repeats them).
# The user named Anmeldename, Vorname, Nachname; Matrikelnummer, Homepage and E-Mail were added as further direct identifiers.
# 'Laufnummer' (column A) stays: it is the key back to the full file.
DROP_HEADERS = {"anmeldename", "vorname", "nachname", "matrikelnummer", "homepage", "e-mail", "email"}
HEADER_SEARCH_ROWS = 6        # the header row is row 2 on 'Resultate'; other sheets are searched in the first rows
FINISHED_STATES = (None,)     # taskStatus is null once the finished task has left the task table (seen: newTask -> inWork -> null)
FAILED_STATES = ("failed", "cancelled")


# --- course archive --------------------------------------------------------------------------------------------------------------
def _archives(course_id):
    status, body = client.request("GET", f"/repo/courses/{course_id}/archives")
    if status != 200:
        raise RuntimeError(f"archives -> HTTP {status}")
    return json.loads(body).get("exportMetadata") or []


def archive_list(course_id):
    """[{key, title, filename, taskStatus}] of the course archives on the server."""
    return [{k: a.get(k) for k in ("key", "title", "filename", "taskStatus")} for a in _archives(course_id)]


def archive_start(course_id, title="Test results archive"):
    """Starts an archive of the course: no logs, chat, course results or PDFs (they are not needed). Returns its key."""
    options = {"title": title, "resultsWithPDFs": False, "logFiles": False, "courseResults": False, "courseChat": False}
    status, body = client.request("POST", f"/repo/courses/{course_id}/archives", data=json.dumps(options).encode(),
                                  content_type="application/json")
    if status != 200:
        raise RuntimeError(f"start archive -> HTTP {status}")
    return json.loads(body)["key"]


def archive_wait(course_id, key, timeout=300, interval=10, log=lambda msg: None):
    """Polls until the archive task has finished. Raises on failure or timeout."""
    started, seen_active = time.time(), False
    while time.time() - started < timeout:
        entry = next((a for a in _archives(course_id) if a.get("key") == key), None)
        if entry is None:
            raise RuntimeError(f"archive {key} not in the list")
        state = entry.get("taskStatus")
        log(f"[{time.time() - started:3.0f}s] archive {key}: {state}")
        if state in FAILED_STATES:
            raise RuntimeError(f"archive {key} {state}")
        seen_active = seen_active or state is not None
        if state in FINISHED_STATES and seen_active:
            return
        time.sleep(interval)
    raise TimeoutError(f"archive {key} not finished after {timeout}s")


def archive_fetch(course_id, key):
    """Downloads the archive in memory, keeps only the results Excel files, writes the anonymised copies.

    Returns [(kept file name, anonymised file name, dropped columns, leak-check hits)].
    """
    status, body = client.request("GET", f"/repo/courses/{course_id}/archives/{key}/file", accept="application/zip")
    if status != 200 or not body:
        raise RuntimeError(f"archive file -> HTTP {status} (204 = not ready yet)")
    archive = zipfile.ZipFile(io.BytesIO(body))
    client.PRIVATE_DIR.mkdir(exist_ok=True)
    results = []
    for name in archive.namelist():
        parts = name.split("/")
        if len(parts) == 3 and parts[1] == "Resultate" and parts[2].lower().endswith(".xlsx"):
            target = client.PRIVATE_DIR / parts[2]
            target.write_bytes(archive.read(name))
            os.chmod(target, 0o600)
            anon, dropped, hits = anonymize(target)
            results.append((target.name, anon.name, dropped, hits))
    return results


def archive_run(course_id, title="Test results archive", log=print):
    """Start, wait, download, anonymise. Returns the archive key and the results of archive_fetch."""
    key = archive_start(course_id, title)
    log(f"archive started, key {key}")
    archive_wait(course_id, key, log=log)
    return key, archive_fetch(course_id, key)


# --- anonymisation ---------------------------------------------------------------------------------------------------------------
def _header(ws):
    """(header row, [columns to drop]) of a sheet; (None, []) if it has none of the identifier columns."""
    for row in range(1, HEADER_SEARCH_ROWS + 1):
        cols = [c for c in range(1, ws.max_column + 1) if str(ws.cell(row, c).value or "").strip().lower() in DROP_HEADERS]
        if cols:
            return row, cols
    return None, []


def _identifiers(ws, header_row, cols):
    """Strings from the identifier columns (logins, matriculation numbers, name parts) - memory only, for the leak check."""
    found = set()
    for c in cols:
        for r in range(header_row + 1, ws.max_row + 1):
            v = ws.cell(r, c).value
            s = str(v).strip().lower() if v is not None else ""
            if not s:
                continue
            if s.isdigit() or "@" in s or "/" in s or (len(s) >= 4 and " " not in s):
                found.add(s)
            found.update(tok for tok in re.split(r"[\s\-,.]+", s) if len(tok) >= 4)
    return found


def anonymize(src, outdir=None):
    """Writes <outdir>/<name>_anonymized.xlsx without the identifier columns and with empty author properties.

    Leak check: none of the dropped values may appear in any cell of the saved file. Returns (path, dropped columns, hit coordinates).
    Needs openpyxl (system python lacks it: run through ~/.venvs/olat/bin/python).
    """
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("openpyxl missing - run with ~/.venvs/olat/bin/python")
    warnings.filterwarnings("ignore", message="Unknown extension")
    outdir = outdir or client.ANON_DIR
    os.makedirs(outdir, exist_ok=True)
    wb = openpyxl.load_workbook(src)
    plan, ids, dropped = {}, set(), []
    for ws in wb.worksheets:                      # pass 1: find the columns and collect their values before anything is deleted
        header_row, cols = _header(ws)
        if cols:
            plan[ws.title] = cols
            dropped += [f"{ws.title}:{ws.cell(header_row, c).value}" for c in cols]
            ids |= _identifiers(ws, header_row, cols)
    for ws in wb.worksheets:                      # pass 2: delete right to left
        for c in sorted(plan.get(ws.title, []), reverse=True):
            ws.delete_cols(c)
    wb.properties.creator = ""
    wb.properties.lastModifiedBy = ""
    out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + "_anonymized.xlsx")
    wb.save(out)

    pattern = re.compile("|".join(r"(?<!\w)" + re.escape(i) + r"(?!\w)" for i in ids)) if ids else None
    hits = []
    for sheet in openpyxl.load_workbook(out).worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if pattern and isinstance(cell.value, (str, int, float)) and pattern.search(str(cell.value).lower()):
                    hits.append(f"{sheet.title}!{cell.coordinate}")
        hits += [f"{sheet.title}!hyperlink:{h.ref}" for h in getattr(sheet, "_hyperlinks", [])]
    return Path(out), dropped, hits
