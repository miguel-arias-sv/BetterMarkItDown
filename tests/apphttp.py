"""Talking to the setup page's server from tests, as the page does."""

from __future__ import annotations

import http.client
import json
import time


def call(app, method, path, body=None, *, token=True, host=None, origin=None, raw=False):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{app.port}", "Content-Type": "application/json"}
    if token:
        headers["X-BMID-Token"] = app.token
    if origin:
        headers["Origin"] = origin
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    if raw:
        return response.status, data, dict(response.getheaders())
    return response.status, json.loads(data or b"{}")


def wait(app, job, seconds: float = 30.0):
    """Poll a job until it ends. The budget is generous: on a busy machine a job that
    takes 0.2 s alone can take several, and a tight one made the suite flaky."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if job["status"] != "running":
            return job
        time.sleep(0.05)
        _, job = call(app, "GET", f"/api/jobs/{job['id']}")
    raise AssertionError(f"job did not finish in {seconds:g} s")
