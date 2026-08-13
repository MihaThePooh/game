#!/usr/bin/env python3
"""Спрайт на шахматке — чтобы глазами увидеть, где прозрачно."""
import zlib, struct, pathlib, sys

def read(path):
    b = pathlib.Path(path).read_bytes()
    i, w, h, idat = 8, 0, 0, b''
    while i < len(b):
        ln = struct.unpack('>I', b[i:i+4])[0]; tag = b[i+4:i+8]; data = b[i+8:i+8+ln]
        if tag == b'IHDR': w, h = struct.unpack('>II', data[:8])
        if tag == b'IDAT': idat += data
        i += 12 + ln
    raw = zlib.decompress(idat)
    px = bytearray(); stride = w*4
    for y in range(h):
        px += raw[y*(stride+1)+1 : y*(stride+1)+1+stride]
    return w, h, px

def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag+data)&0xFFFFFFFF)

w, h, px = read(sys.argv[1])
S, out = 8, bytearray()
for y in range(h):
    for x in range(w):
        j = (y*w+x)*4; a = px[j+3]
        base = 224 if ((x//S + y//S) % 2 == 0) else 150
        out += bytes(((px[j+c]*a + base*(255-a))//255 for c in range(3))) + b'\xff'
rows = bytearray()
for y in range(h):
    rows += b"\0" + out[y*w*4:(y+1)*w*4]
pathlib.Path(sys.argv[2]).write_bytes(b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", w,h,8,6,0,0,0))
    + chunk(b"IDAT", zlib.compress(bytes(rows),9)) + chunk(b"IEND", b""))
print(sys.argv[2], w, h, 'непрозрачных',
      round(sum(1 for i in range(w*h) if px[i*4+3]>0)/(w*h)*100), '%')
