"""A fake GitHub API: GET /repos/olfabref/nex5r-ascom/releases/latest answers like api.github.com,
with the Release set in `release` (a tag name, or None for a repository without any Release: 404)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LATEST_PATH = '/repos/olfabref/nex5r-ascom/releases/latest'


def release_json(tag: str) -> dict:
    """The fields of a GitHub Release object that the Alpaca Server reads, as the API returns them."""
    base = f'https://github.com/olfabref/nex5r-ascom/releases/download/{tag}'
    return {
        'tag_name': tag,
        'name': tag,
        'html_url': f'https://github.com/olfabref/nex5r-ascom/releases/tag/{tag}',
        'draft': False,
        'prerelease': False,
        'published_at': '2026-11-01T12:00:00Z',
        'assets': [
            {'name': f'nex5r-ascom-setup-{tag}.exe', 'size': 12345678,
             'browser_download_url': f'{base}/nex5r-ascom-setup-{tag}.exe'},
            {'name': 'SHA256SUMS', 'size': 200, 'browser_download_url': f'{base}/SHA256SUMS'},
        ],
    }


class FakeGitHub:
    def __init__(self, release: str | None = None):
        self.release = release
        self.requests: list[dict] = []        # headers of each request, oldest first
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                fake.requests.append(dict(self.headers))
                if self.path != LATEST_PATH or fake.release is None:
                    body, code = {'message': 'Not Found'}, 404
                else:
                    body, code = release_json(fake.release), 200
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}{LATEST_PATH}'

    def start(self) -> 'FakeGitHub':
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
