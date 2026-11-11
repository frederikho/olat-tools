"""Agent-side tooling for the OpenOlat installation olat.vcrp.de (REST API with the browser session cookie).

client   - paths, constants, HTTP requests, multipart upload, the Cookie line of the credentials file
session  - reads the Firefox session cookies, checks that the session is valid (run this first)
courses  - course structure, test import/attach/options, editor-lock probe
results  - course archive of test results (answer texts) and the anonymised copies of the results Excel files
cli      - the single command line entry point (console script `olat`, see ../../pyproject.toml)
"""
