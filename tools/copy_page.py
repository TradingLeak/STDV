#!/usr/bin/env python3
"""One-click copy page for the Bandz STDV & CISD Pine source.

Serves:
  /           the copy page (tools/copy-page.html)
  /code.pine  the current contents of src/bandz_stdv_cisd.pine, always live

The Pine file is streamed from disk on every request, so the page can never
serve a stale copy after the source is edited.

Usage: python3 tools/copy_page.py [port]
"""

import http.server
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "tools", "copy-page.html")
PINE = os.path.join(ROOT, "src", "bandz_stdv_cisd.pine")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path in ("/", "/index.html", "/copy"):
            try:
                with open(PAGE, "rb") as handle:
                    body = handle.read()
            except OSError:
                self._send(500, b"copy-page.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")
        elif path in ("/code.pine", "/bandz_stdv_cisd.pine"):
            try:
                with open(PINE, "rb") as handle:
                    body = handle.read()
            except OSError:
                self._send(404, b"source file missing", "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/plain; charset=utf-8")
        elif path == "/health":
            self._send(200, b"ok", "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    if not os.path.exists(PINE):
        sys.exit("Cannot find %s" % PINE)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.allow_reuse_address = True
    print("Copy page on http://0.0.0.0:%d  ->  %s" % (PORT, PINE), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
