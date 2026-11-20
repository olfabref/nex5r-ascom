"""Writes tests/data/sample.ARW, the image the fake camera-app serves.

A real NEX-5R ARW is 16 MB, too big for the repository. This one is a minimal uncompressed DNG
(a TIFF that LibRaw, hence rawpy, decodes like an ARW): 64 x 40 pixels, 14-bit, CFA pattern GRBG so
that red sits at (x, y) = (1, 0) and the BayerOffset the server derives from the file is not the
config default (0, 0). Pixel value = 512 + 4 * x + 256 * y, so tests can check the orientation.

    .venv/bin/python tests/make_sample_arw.py
"""
import struct
from pathlib import Path

import numpy as np

WIDTH, HEIGHT = 64, 40
BAYER_OFFSET = (1, 0)               # red at x=1, y=0 (GRBG)
OUT = Path(__file__).parent / 'data' / 'sample.ARW'

SHORT, LONG, RATIONAL, SRATIONAL, ASCII, BYTE = 3, 4, 5, 10, 2, 1


def pixels() -> np.ndarray:
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    return (512 + 4 * x + 256 * y).astype('<u2')


def build() -> bytes:
    data = pixels().tobytes()
    entries = []                    # (tag, type, values)

    def add(tag, typ, values):
        entries.append((tag, typ, values))

    add(254, LONG, [0])                         # NewSubFileType: main image
    add(256, LONG, [WIDTH])
    add(257, LONG, [HEIGHT])
    add(258, SHORT, [16])                       # BitsPerSample
    add(259, SHORT, [1])                        # Compression: none
    add(262, SHORT, [32803])                    # PhotometricInterpretation: CFA
    add(271, ASCII, b'SONY\0')
    add(272, ASCII, b'NEX-5R\0')
    add(273, LONG, [0])                         # StripOffsets, patched below
    add(274, SHORT, [1])                        # Orientation
    add(277, SHORT, [1])                        # SamplesPerPixel
    add(278, LONG, [HEIGHT])                    # RowsPerStrip
    add(279, LONG, [len(data)])                 # StripByteCounts
    add(284, SHORT, [1])                        # PlanarConfiguration
    add(33421, SHORT, [2, 2])                   # CFARepeatPatternDim
    add(33422, BYTE, bytes([1, 0, 2, 1]))       # CFAPattern GRBG (0=R, 1=G, 2=B)
    add(50706, BYTE, bytes([1, 4, 0, 0]))       # DNGVersion
    add(50708, ASCII, b'Sony NEX-5R\0')         # UniqueCameraModel
    add(50714, SHORT, [512])                    # BlackLevel
    add(50717, SHORT, [16383])                  # WhiteLevel
    add(50721, SRATIONAL, [(1, 1), (0, 1), (0, 1), (0, 1), (1, 1), (0, 1), (0, 1), (0, 1), (1, 1)])
    add(50778, SHORT, [21])                     # CalibrationIlluminant1: D65
    entries.sort()

    ifd_offset = 8
    ifd_size = 2 + 12 * len(entries) + 4
    extra_offset = ifd_offset + ifd_size
    extra = b''
    ifd = struct.pack('<H', len(entries))
    strip_entry_pos = None
    for tag, typ, values in entries:
        if typ in (ASCII, BYTE):
            payload, count = bytes(values), len(values)
        elif typ == SHORT:
            payload, count = struct.pack(f'<{len(values)}H', *values), len(values)
        elif typ == LONG:
            payload, count = struct.pack(f'<{len(values)}I', *values), len(values)
        else:
            fmt = '<ii' if typ == SRATIONAL else '<II'
            payload, count = b''.join(struct.pack(fmt, *v) for v in values), len(values)
        if tag == 273:
            strip_entry_pos = len(ifd) + 8
        if len(payload) <= 4:
            ifd += struct.pack('<HHI', tag, typ, count) + payload.ljust(4, b'\0')
        else:
            ifd += struct.pack('<HHII', tag, typ, count, extra_offset + len(extra))
            extra += payload + (b'\0' if len(payload) % 2 else b'')
    ifd += struct.pack('<I', 0)                 # no next IFD
    strip_offset = extra_offset + len(extra)
    ifd = ifd[:strip_entry_pos] + struct.pack('<I', strip_offset) + ifd[strip_entry_pos + 4:]
    return b'II*\0' + struct.pack('<I', ifd_offset) + ifd + extra + data


if __name__ == '__main__':
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(build())
    print(f'{OUT}: {OUT.stat().st_size} B')
