# olat_tools

Command line tooling for the OpenOlat installation olat.vcrp.de (REST API, authenticated with the session cookie of a logged-in Firefox).
What works, what does not and why (editor lock, organisations, privacy rules) is documented in `../CLAUDE.md` – this file only describes the code.

```
pyproject.toml          package `olat`, console script `olat`
src/olat/
  client.py             paths, constants, HTTP request/get_json/multipart, the Cookie line of the credentials file
  session.py            Firefox cookie reader (own LZ4 decoder), `check` (session verdict + log)
  courses.py            course structure, test upload/attach/options, editor-lock probe
  results.py            course archive with answer texts, anonymised Excel copies
  cli.py                argparse entry point (python -m olat works too)
tests/                  unit tests (invented data only)
docs/openapi.json       REST spec of the server (needs login to download)
private_downloads/      full student data      – git-ignored, never read by the agent
anonymized/             anonymised copies      – git-ignored, may be read by the agent
```

Setup (once): `python3 -m venv ~/.venvs/olat && ~/.venvs/olat/bin/pip install -e .` – installs `openpyxl` and the command `~/.venvs/olat/bin/olat`.

```
~/.venvs/olat/bin/olat check                      # always first; exit 0 = session OK
~/.venvs/olat/bin/olat nodes <course> --type iqtest
~/.venvs/olat/bin/olat archive run <course>       # start, wait, download, anonymise
~/.venvs/olat/bin/python -m unittest discover -s tests
```

`olat --help` lists the other commands.
