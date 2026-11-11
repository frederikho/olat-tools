"""Courses and tests: structure listing, QTI test import, attaching a test to a course, run-time options, editor-lock probe.

Ids: `course_id` is the repository entry's olatResourceId (NOT the number in the course URL, that is the root node id);
`test_entry_key` is the repository entry key of the imported test (NOT its olatResourceId, that gives 404).
Writes to a course fail with 403 while anybody has the course editor open (editor lock) - ask the user to close it first.
New nodes exist only in the editor until the course is published; no endpoint deletes a node.
"""
import json
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

from . import client

# run-time options verified on 2026-11-11 (no feedback or solutions for students; the correction mode cannot be set via REST)
DEFAULT_TEST_OPTIONS = dict(allowCancel=False, allowSuspend=False, allowNavigation=True, showNavigation=True, showQuestionTitle=True,
                            showResultsAfterFinish=False, showResultsOnHomepage=False)


def _query(**params):
    """URL query string; booleans become 'true'/'false' as the API expects."""
    return urllib.parse.urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()})


# --- structure (no participant data) ---------------------------------------------------------------------------------------------
def course_nodes(course_id, type_filter=None):
    """[(depth, node id, type, title)] from GET /repo/courses/{id}/runstructure (XML only; JSON gives 406)."""
    status, body = client.request("GET", f"/repo/courses/{course_id}/runstructure", accept="application/xml")
    if status != 200:
        raise RuntimeError(f"runstructure -> HTTP {status}")
    nodes = []

    def walk(el, depth):
        attrs = {k.lower(): v for k, v in el.attrib.items()}
        kids = {ch.tag.lower(): (ch.text or "").strip() for ch in el if len(ch) == 0}
        ident = attrs.get("ident") or attrs.get("id") or kids.get("ident") or kids.get("id")
        kind = attrs.get("type") or kids.get("type") or el.tag
        title = kids.get("shorttitle") or kids.get("title") or attrs.get("shorttitle") or attrs.get("title") or ""
        if ident and (type_filter is None or type_filter.lower() in kind.lower()):
            nodes.append((depth, ident, kind, title))
        for child in el:
            walk(child, depth + 1)

    walk(ET.fromstring(body), 0)
    return nodes


# --- tests -----------------------------------------------------------------------------------------------------------------------
def upload_test(zip_path, title, org_key=client.ORG_KEY):
    """Imports a QTI 2.1 test zip as a new test resource (status 'preparation' = private to the owner). Returns (status, info)."""
    fields = {"filename": Path(zip_path).name, "resourcename": title, "displayname": title, "organisationkey": org_key}
    content_type, body = client.multipart(fields, "file", zip_path)
    status, resp = client.request("PUT", "/repo/entries", data=body, content_type=content_type)
    try:
        j = json.loads(resp)
        return status, {k: j.get(k) for k in ("key", "displayname", "resourceableTypeName", "authors")}
    except ValueError:
        return status, resp[:300].decode("utf-8", "replace")


def attach_test(course_id, parent_node_id, test_entry_key, title, description="Intermediate individual check-up", position=0):
    """Adds a Test element below `parent_node_id`. Returns (status, response text); the new node id is in the response."""
    query = _query(parentNodeId=parent_node_id, position=position, shortTitle=title[:25], longTitle=title,
                   description=description, testResourceableId=test_entry_key)
    status, body = client.request("PUT", f"/repo/courses/{course_id}/elements/test?{query}")
    return status, body.decode("utf-8", "replace")


def set_test_options(course_id, node_id, **overrides):
    """Sets the run-time options of a test node (defaults: DEFAULT_TEST_OPTIONS). Returns the HTTP status."""
    options = {**DEFAULT_TEST_OPTIONS, **overrides}
    status, _ = client.request("PUT", f"/repo/courses/{course_id}/elements/test/{node_id}/configuration?{_query(**options)}")
    return status


def probe_lock(course_id, node_id, test_entry_key):
    """Is the course editor free for the API? The API has no lock endpoint, so this re-saves an existing test node with IDENTICAL values.

    Returns (verdict, status): FREE (200) / LOCKED (403: editor open elsewhere or no editor right) / NOT FOUND (404) / OTHER.
    A LOCKED answer has not been compared against a state known to be free yet.
    """
    status, node = client.get_json(f"/repo/courses/{course_id}/elements/{node_id}")
    if status != 200 or not isinstance(node, dict):
        return f"cannot read the node (GET -> {status})", status
    form = urllib.parse.urlencode({"shortTitle": node.get("shortTitle") or "", "longTitle": node.get("longTitle") or "",
                                   "description": node.get("description") or "", "testResourceableId": test_entry_key}).encode()
    status, _ = client.request("POST", f"/repo/courses/{course_id}/elements/test/{node_id}", data=form,
                               content_type="application/x-www-form-urlencoded")
    verdicts = {200: "FREE: editor lock could be taken, writes will work",
                403: "LOCKED: the course editor is held by someone else (or no editor right) - ask the user to close it",
                404: "NOT FOUND: course, node or test missing"}
    return verdicts.get(status, f"OTHER: HTTP {status}"), status
