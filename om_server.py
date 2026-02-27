#!/usr/bin/env python3
"""
SB 1123 Deal Finder — Local dev server with OM generation API.
Replaces `python3 -m http.server 8080`.

Usage:
  python3 om_server.py [port]       # default: 8080

Serves static files AND handles:
  POST /api/generate-om  → accepts JSON deal dict, returns PPTX binary
"""

import json, os, sys, io, traceback
from http.server import SimpleHTTPRequestHandler, HTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import generate_om from same directory
sys.path.insert(0, SCRIPT_DIR)
from generate_om import build_om

ASSETS_DIR = os.path.join(SCRIPT_DIR, 'assets')
MATT_PHOTO = os.path.join(ASSETS_DIR, 'matt_circle.png')
JOE_PHOTO = os.path.join(ASSETS_DIR, 'joe_circle.png')


class OMHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/generate-om':
            self._handle_generate_om()
        else:
            self.send_error(404, 'Not Found')

    def _handle_generate_om(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            d = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self.send_error(400, f'Bad JSON: {e}')
            return

        try:
            matt = MATT_PHOTO if os.path.exists(MATT_PHOTO) else None
            joe = JOE_PHOTO if os.path.exists(JOE_PHOTO) else None
            pres = build_om(d, matt, joe)

            buf = io.BytesIO()
            pres.save(buf)
            pptx_bytes = buf.getvalue()

            addr = d.get('address', 'deal').replace(' ', '-').replace(',', '').replace('.', '')
            filename = f"{addr}-OM.pptx"

            self.send_response(200)
            self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.presentationml.presentation')
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Length', str(len(pptx_bytes)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(pptx_bytes)
            self.log_message(f'OM generated: {filename} ({len(pptx_bytes):,} bytes)')

        except Exception as e:
            traceback.print_exc()
            self.send_error(500, f'OM generation failed: {e}')

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    os.chdir(SCRIPT_DIR)
    server = HTTPServer(('', port), OMHandler)
    print(f'SB 1123 Deal Finder + OM Server')
    print(f'  Static files: http://localhost:{port}')
    print(f'  OM API:       POST http://localhost:{port}/api/generate-om')
    print(f'  Assets:       {ASSETS_DIR}')
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
