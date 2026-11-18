"""Shared by the DEV31 page tests: run the shipped tracking page script under Node with a stubbed DOM and read what a page function returns.
No browser; the same approach as tests/test_tracking_situation.py (Script). Returns None from `skip()` when Node is missing: callers skipTest."""
import json
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

from onecrew.v2.tracking_web import PAGE

STUB = ("var document={querySelector:function(){return {addEventListener:function(){},value:'',options:[],style:{}}},querySelectorAll:function(){return []},addEventListener:function(){}};"
        "var window={matchMedia:function(){return {matches:false,addEventListener:function(){}}},addEventListener:function(){},scrollTo:function(){},scrollY:0};"
        "var location={search:'',pathname:'/'};var history={pushState:function(){}};var localStorage={getItem:function(){return null},setItem:function(){}};"
        "function setInterval(){};function setTimeout(){};function fetch(){return {then:function(){return {then:function(){return {catch:function(){return {then:function(){}}}}}}}}};")


def node():
    return shutil.which('node')


def run(expr, extra=''):
    """Evaluate `expr` inside the page script's scope after `extra` (which may assign `last=` and define variables); the value as JSON."""
    start = PAGE.index('<script>') + 8
    body = PAGE[start:PAGE.rindex('</script>')].replace('@@INTERVAL@@', '2000')
    body = body.replace('(function(){', '', 1)
    body = body[:body.rindex('})();')]
    result = subprocess.run([node(), '-'], input=STUB + body + extra + '\nconsole.log(JSON.stringify(' + expr + '));', text=True, encoding='utf8',
                            capture_output=True, timeout=30)
    if result.returncode: raise AssertionError(result.stderr[-2000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


class Served:
    """The real tracking server on a free port over a state root; `get(path)` -> (status, bytes). Use as a context manager."""

    def __init__(self, state_root, **kw):
        from onecrew.v2 import tracking_web
        self.server = tracking_web.make_server(state_root, interval=1.0, **kw)
        self.url = tracking_web.url_of(self.server)

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown(); self.server.server_close(); self.thread.join(10)

    def get(self, path):
        with urllib.request.urlopen(self.url.rstrip('/') + path, timeout=30) as response:
            return response.status, response.read()
