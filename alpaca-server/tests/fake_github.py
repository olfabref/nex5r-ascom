"""A fake GitHub API: GET /repos/olfabref/nex5r-ascom/releases/latest answers like api.github.com,
with the Release set in `release` (a tag name, or None for a repository without any Release: 404).

With `assets` (asset name -> bytes or a file Path), the Release lists those assets and this server also
serves their downloads (GET /download/<tag>/<name>), as github.com does for browser_download_url: the
Update downloads the installer and SHA256SUMS from there. Without `assets`, the Release lists the real
asset names with github.com URLs that are never fetched.

Also run outside pytest, by alpaca-server/installer/check_update.py on a Windows runner.
"""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LATEST_PATH = '/repos/olfabref/nex5r-ascom/releases/latest'
INSTALLER = 'nex5r-ascom-setup.exe'


def sha256sums(files: dict[str, bytes | Path]) -> bytes:
    """SHA256SUMS as the release workflow writes it (`sha256sum` format)."""
    lines = []
    for name, data in files.items():
        data = data.read_bytes() if isinstance(data, Path) else data
        lines.append(f'{hashlib.sha256(data).hexdigest()}  {name}\n')
    return ''.join(lines).encode()


def release_json(tag: str, base: str | None = None, assets: dict[str, int] | None = None) -> dict:
    """The fields of a GitHub Release object that the Alpaca Server reads, as the API returns them.
    assets: name -> size, downloaded from base (default: the real asset names on github.com)."""
    base = base or f'https://github.com/olfabref/nex5r-ascom/releases/download/{tag}'
    assets = assets if assets is not None else {INSTALLER: 12345678, 'nex5r.apk': 54321, 'SHA256SUMS': 200}
    return {
        'tag_name': tag,
        'name': tag,
        'html_url': f'https://github.com/olfabref/nex5r-ascom/releases/tag/{tag}',
        'draft': False,
        'prerelease': False,
        'published_at': '2026-11-01T12:00:00Z',
        'assets': [{'name': name, 'size': size, 'browser_download_url': f'{base}/{name}'}
                   for name, size in assets.items()],
    }


class FakeGitHub:
    def __init__(self, release: str | None = None, assets: dict[str, bytes | Path] | None = None,
                 host: str = '127.0.0.1'):
        self.release = release
        self.assets = assets
        self.requests: list[dict] = []        # headers of each request, oldest first
        self.paths: list[str] = []            # path of each request, oldest first
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, code: int, data: bytes, content_type: str):
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.requests.append(dict(self.headers))
                fake.paths.append(self.path)
                download = fake._download(self.path)
                if download is not None:
                    return self.send(200, download, 'application/octet-stream')
                if self.path != LATEST_PATH or fake.release is None:
                    body, code = {'message': 'Not Found'}, 404
                else:
                    body, code = fake._release_json(), 200
                self.send(code, json.dumps(body).encode(), 'application/json; charset=utf-8')

        self.httpd = ThreadingHTTPServer((host, 0), Handler)
        self.root = f'http://{host}:{self.httpd.server_address[1]}'
        self.url = self.root + LATEST_PATH

    def _bytes(self) -> dict[str, bytes]:
        return {name: data.read_bytes() if isinstance(data, Path) else data
                for name, data in (self.assets or {}).items()}

    def _release_json(self) -> dict:
        if self.assets is None:
            return release_json(self.release)
        sizes = {name: len(data) for name, data in self._bytes().items()}
        return release_json(self.release, f'{self.root}/download/{self.release}', sizes)

    def _download(self, path: str) -> bytes | None:
        if self.assets is None or self.release is None:
            return None
        prefix = f'/download/{self.release}/'
        if not path.startswith(prefix):
            return None
        return self._bytes().get(path[len(prefix):])

    def downloads(self) -> list[str]:
        """Names of the assets downloaded so far, oldest first."""
        return [p.rsplit('/', 1)[1] for p in self.paths if p.startswith('/download/')]

    def start(self) -> 'FakeGitHub':
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
