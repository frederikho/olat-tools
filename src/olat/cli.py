"""Command line entry point:  ~/.venvs/olat/bin/olat <command> ...   (installed into the venv that has openpyxl; PYTHONPATH=src python3 -m olat works for commands without Excel)

  check                                         refresh the cookie from Firefox and test the session - ALWAYS run this first
  nodes <course> [--type iqtest]                list the nodes of a course (structure only)
  upload-test <zip> <title> [--org 5]           import a QTI 2.1 test zip as a new test resource
  attach-test <course> <parent-node> <test-entry-key> <title>   add a Test element and set its run-time options (editor must be closed)
  lock-probe <course> <node> <test-entry-key>   is the course editor free? (harmless re-save of a test node)
  archive list|start|fetch|run <course> [key|title]   course archive with the answer texts; `run` = start + wait + download + anonymise
  anonymize <results.xlsx> [--out DIR]          anonymised copy of a results Excel (e.g. one downloaded manually)
Exit codes of `check`: 0 OK, 10 session expired (log in to OLAT in Firefox again), 11 blocked by an earlier slow request, 12 other.
"""
import argparse
import json

from . import client, courses, results, session


def _parser():
    p = argparse.ArgumentParser(prog="olat", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    s = sub.add_parser("nodes")
    s.add_argument("course")
    s.add_argument("--type", dest="type_filter")
    s = sub.add_parser("upload-test")
    s.add_argument("zip")
    s.add_argument("title")
    s.add_argument("--org", type=int, default=client.ORG_KEY)
    s = sub.add_parser("attach-test")
    s.add_argument("course")
    s.add_argument("parent_node")
    s.add_argument("test_key")
    s.add_argument("title")
    s = sub.add_parser("lock-probe")
    s.add_argument("course")
    s.add_argument("node")
    s.add_argument("test_key")
    s = sub.add_parser("archive")
    s.add_argument("action", choices=["list", "start", "fetch", "run"])
    s.add_argument("course")
    s.add_argument("arg", nargs="?", help="archive key (fetch) or title (start, run)")
    s = sub.add_parser("anonymize")
    s.add_argument("xlsx")
    s.add_argument("--out")
    return p


def _print_results(rows):
    for kept, anon, dropped, hits in rows:
        print(f"kept (private): {kept}\nanonymised:     {anon}\n  dropped: {dropped}\n  leak-check hits: {len(hits)} {hits[:10] or ''}")
    if not rows:
        print("no results Excel found in the archive")


def main(argv=None):
    args = _parser().parse_args(argv)
    cmd = args.command
    if cmd == "check":
        return session.check()
    if cmd == "nodes":
        for depth, ident, kind, title in courses.course_nodes(args.course, args.type_filter):
            print("  " * depth + f"{ident}  {kind}  {title}")
    elif cmd == "upload-test":
        status, info = courses.upload_test(args.zip, args.title, args.org)
        print("PUT /repo/entries ->", status, info)
    elif cmd == "attach-test":
        status, text = courses.attach_test(args.course, args.parent_node, args.test_key, args.title)
        print("attach ->", status, text[:300])
        if status == 200:
            node_id = json.loads(text).get("id")
            print("options ->", courses.set_test_options(args.course, node_id))
        return 0 if status == 200 else 1
    elif cmd == "lock-probe":
        verdict, status = courses.probe_lock(args.course, args.node, args.test_key)
        print(verdict)
        return 0 if status == 200 else 1
    elif cmd == "archive":
        if args.action == "list":
            for a in results.archive_list(args.course):
                print(a)
        elif args.action == "start":
            print("archive key:", results.archive_start(args.course, args.arg or "Test results archive"))
        elif args.action == "fetch":
            _print_results(results.archive_fetch(args.course, int(args.arg)))
        else:
            _print_results(results.archive_run(args.course, args.arg or "Test results archive")[1])
    elif cmd == "anonymize":
        out, dropped, hits = results.anonymize(args.xlsx, args.out)
        print(f"anonymised: {out.name}\n  dropped: {dropped}\n  leak-check hits: {len(hits)} {hits[:10] or ''}")
    return 0
