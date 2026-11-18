"""End-to-end check through the Alpaca API, as N.I.N.A. would do it: connect, one exposure, ImageBytes.

    .venv/bin/python smoke_test.py [seconds] [server]     # defaults: 2 s, http://localhost:11111
"""
import json
import struct
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
BASE = (sys.argv[2] if len(sys.argv) > 2 else 'http://localhost:11111') + '/api/v1/camera/0/'
tid = 0


def call(method: str, name: str, **fields):
    global tid
    tid += 1
    fields.update(ClientID=1, ClientTransactionID=tid)
    data = urllib.parse.urlencode(fields)
    if method == 'GET':
        req = urllib.request.Request(BASE + name + '?' + data)
    else:
        req = urllib.request.Request(BASE + name, data=data.encode(), method='PUT')
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    if body['ErrorNumber']:
        raise SystemExit(f'{name}: error {body["ErrorNumber"]}: {body["ErrorMessage"]}')
    return body.get('Value')


call('PUT', 'connected', Connected='true')
for p in ('cameraxsize', 'cameraysize', 'sensortype', 'gains', 'gain', 'exposuremin'):
    print(f'{p} = {call("GET", p)}')

t0 = time.monotonic()
call('PUT', 'startexposure', Duration=DUR, Light='true')
while True:
    state = call('GET', 'camerastate')
    if call('GET', 'imageready'):
        break
    if state == 5:
        raise SystemExit('camera state Error')
    time.sleep(1)
print(f'image ready {time.monotonic() - t0:.1f} s after StartExposure ({DUR} s)')

req = urllib.request.Request(BASE + 'imagearray?ClientID=1&ClientTransactionID=99',
                             headers={'Accept': 'application/imagebytes'})
with urllib.request.urlopen(req, timeout=60) as r:
    ctype, raw = r.headers['Content-Type'], r.read()
hdr = struct.unpack('<11i', raw[:44])
print(f'{ctype}: header {hdr}')
img = np.frombuffer(raw[hdr[4]:], dtype='<u2').reshape(hdr[8], hdr[9])
print(f'image {img.shape} min {img.min()} max {img.max()} mean {img.mean():.1f}')
print(f'bayer offset {call("GET", "bayeroffsetx")},{call("GET", "bayeroffsety")}, '
      f'last {call("GET", "lastexposureduration")} s at {call("GET", "lastexposurestarttime")}')
