#!/usr/bin/env python3
"""Фото рисунка -> спрайт PNG с прозрачным фоном.

Тот же алгоритм, что зашит в game.html, только здесь его удобно
прогонять и смотреть глазами.

    ./sprite.py фото.jpg [out.png]

ffmpeg используется ровно как декодер: отдаёт голые RGB-байты, чтобы
не тащить Pillow (её на сервере нет и поставить нечем).

Порядок:
    1. уменьшить до 320 px по большей стороне
    2. маска тёмного — это линии рисунка
    3. выбросить пятна, касающиеся края кадра:
       так уходят пружины блокнота, тени и край стола
    4. рамка по тому, что осталось
    5. фон = светлое, до которого можно дойти от края;
       светлое ВНУТРИ контура остаётся белой заливкой
"""
import collections
import pathlib
import subprocess
import sys
import zlib
import struct

MAX = 320
DARK = 0.80        # доля от местной яркости бумаги: ниже — линия
LIGHT = 0.90       # выше — чистая бумага
MIN_BLOB = 3       # пятна мельче — пыль и шум JPEG, а не рисунок
FILL_R = 8         # на столько раздуваем линии, чтобы замкнуть силуэт


def decode(path):
    """JPEG -> (ширина, высота, bytes RGB) силами ffmpeg."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True)
    w, h = (int(v) for v in probe.stdout.strip().split("x")[:2])
    k = min(MAX / w, MAX / h, 1)
    w, h = max(1, round(w * k)), max(1, round(h * k))
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"scale={w}:{h}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    return w, h, raw


def lum(raw, i):
    """Яркость по восприятию: зелёный глазу заметнее синего."""
    return (raw[i] * 0.299 + raw[i + 1] * 0.587 + raw[i + 2] * 0.114) / 255


def normalize(raw, w, h):
    """Убирает неровный свет: каждый пиксель делится на яркость бумаги
    вокруг него. Снимок в тени и снимок у окна после этого одинаковы,
    и порог можно задать раз и навсегда.

    Местная яркость — среднее по большому окну. Считается через таблицу
    сумм: сумма любого прямоугольника берётся за четыре обращения,
    сколько бы он ни был велик.
    """
    px = [lum(raw, i * 3) for i in range(w * h)]
    acc = [0.0] * ((w + 1) * (h + 1))
    for y in range(h):
        line = 0.0
        for x in range(w):
            line += px[y * w + x]
            acc[(y + 1) * (w + 1) + x + 1] = acc[y * (w + 1) + x + 1] + line

    r = max(8, max(w, h) // 8)
    out = [0.0] * (w * h)
    for y in range(h):
        y0, y1 = max(0, y - r), min(h, y + r + 1)
        for x in range(w):
            x0, x1 = max(0, x - r), min(w, x + r + 1)
            total = (acc[y1 * (w + 1) + x1] - acc[y0 * (w + 1) + x1]
                     - acc[y1 * (w + 1) + x0] + acc[y0 * (w + 1) + x0])
            bg = total / ((y1 - y0) * (x1 - x0))
            out[y * w + x] = px[y * w + x] / bg if bg > 0.02 else 1.0
    return out


def blobs(mask, w, h, frame=None):
    """Связные пятна тёмного. Возвращает список (клетки, касается_края).

    frame — границы рамки (x0, y0, x1, y1); по умолчанию весь кадр."""
    fx0, fy0, fx1, fy1 = frame or (0, 0, w - 1, h - 1)
    seen = bytearray(w * h)
    out = []
    for start in range(w * h):
        if seen[start] or not mask[start]:
            continue
        q = collections.deque([start])
        seen[start] = 1
        cells, edge = [], False
        while q:
            p = q.popleft()
            cells.append(p)
            x, y = p % w, p // w
            if x <= fx0 or y <= fy0 or x >= fx1 or y >= fy1:
                edge = True
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    n = ny * w + nx
                    if mask[n] and not seen[n]:
                        seen[n] = 1
                        q.append(n)
        out.append((cells, edge))
    return out


def close(mask, w, h, r):
    """Замыкание: линии сначала толстеют на r, потом худеют обратно.
    Разрывы уже r закрываются — а рисунок от руки почти всегда с
    разрывами, и без этого заливка вытекает наружу через щель."""
    def grow(src, rad):
        out = bytearray(w * h)
        for y in range(h):
            for x in range(w):
                if not src[y * w + x]:
                    continue
                for dy in range(-rad, rad + 1):
                    yy = y + dy
                    if yy < 0 or yy >= h:
                        continue
                    for dx in range(-rad, rad + 1):
                        xx = x + dx
                        if 0 <= xx < w:
                            out[yy * w + xx] = 1
        return out

    grown = grow(mask, r)
    inv = bytearray(1 - v for v in grown)
    return bytearray(1 - v for v in grow(inv, r))


def cut(w, h, raw, box=None, fill=FILL_R):
    """Возвращает (ширина, высота, RGBA) вырезанного рисунка.

    box — рамка в долях (x0, y0, x1, y1). Если её нет, кадр берётся
    целиком, и тогда всё, что упирается в его границу, считается
    посторонним: пружины блокнота, тень, край стола."""
    nrm = normalize(raw, w, h)
    frame = None
    if box:
        bx0, by0 = int(box[0] * w), int(box[1] * h)
        bx1, by1 = int(box[2] * w), int(box[3] * h)
        frame = (bx0, by0, bx1, by1)
        for y in range(h):
            for x in range(w):
                if x < bx0 or x > bx1 or y < by0 or y > by1:
                    nrm[y * w + x] = 1.0   # снаружи рамки — чистая бумага
    mask = bytearray(1 if nrm[i] < DARK else 0 for i in range(w * h))

    # Пружины блокнота и край стола — тоже тёмные, но они всегда упираются
    # в границу кадра. Рисунок в середине листа — нет.
    # Выбрасываем только то, что упирается в границу кадра: пружины
    # блокнота, тень, край стола. По размеру не фильтруем — тонкий
    # контур при уменьшении рассыпается на сотни кусочков, и «оставить
    # только крупное» съело бы сам рисунок.
    parts = blobs(mask, w, h, frame)
    for cells, edge in parts:
        if not edge:
            continue
        for p in cells:
            mask[p] = 0
            nrm[p] = 1.0        # чтобы тень не проступила в спрайте серым

    # А вот рамку считаем по заметным пятнам: одинокая пылинка
    # в углу листа не должна растягивать спрайт на весь лист.
    keep = [c for c, edge in parts if not edge and len(c) >= MIN_BLOB]
    if not keep:
        return None

    x0, y0, x1, y1 = w, h, -1, -1
    for cells in keep:
        for p in cells:
            x, y = p % w, p // w
            x0, y0 = min(x0, x), min(y0, y)
            x1, y1 = max(x1, x), max(y1, y)

    pad = 3
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w - 1, x1 + pad), min(h - 1, y1 + pad)
    cw, ch = x1 - x0 + 1, y1 - y0 + 1

    # Заливка идёт по замкнутой маске: снаружи всё, до чего удалось
    # дойти от края, не пересекая утолщённых линий. Остальное — тело
    # персонажа, оно станет непрозрачным.
    solid = close(mask, w, h, fill)
    outside = bytearray(cw * ch)
    q = collections.deque()

    def push(x, y):
        if 0 <= x < cw and 0 <= y < ch:
            j = y * cw + x
            if not outside[j] and not solid[(y + y0) * w + (x + x0)]:
                outside[j] = 1
                q.append(j)

    for x in range(cw):
        push(x, 0); push(x, ch - 1)
    for y in range(ch):
        push(0, y); push(cw - 1, y)
    while q:
        p = q.popleft()
        x, y = p % cw, p // cw
        push(x - 1, y); push(x + 1, y); push(x, y - 1); push(x, y + 1)

    out = bytearray(cw * ch * 4)
    for y in range(ch):
        for x in range(cw):
            j = y * cw + x
            n = nrm[(y + y0) * w + (x + x0)]
            # Внутри персонажа бумага становится ровной белой заливкой:
            # серость и клетка листа в игре ни к чему.
            ink = max(0.0, min(1.0, (LIGHT - n) / (LIGHT - DARK + 0.001)))
            tone = round(255 - ink * 215)
            out[j * 4] = out[j * 4 + 1] = out[j * 4 + 2] = tone
            if outside[j]:
                # Снаружи прозрачно, но линия на самой границе гаснет
                # плавно — иначе край получается пилой.
                out[j * 4 + 3] = round(min(1.0, ink * 1.6) * 255)
            else:
                out[j * 4 + 3] = 255
    return cw, ch, out


def png(path, w, h, rgba):
    rows = bytearray()
    for y in range(h):
        rows += b"\0" + rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    pathlib.Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b""))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    box = None
    for a in sys.argv[1:]:
        if a.startswith("--box="):
            box = [float(v) for v in a[6:].split(",")]

    src = pathlib.Path(args[0])
    dst = args[1] if len(args) > 1 else str(src.with_suffix(".sprite.png"))
    w, h, raw = decode(src)
    fill = FILL_R
    for a in sys.argv[1:]:
        if a.startswith("--fill="):
            fill = int(a[7:])
    res = cut(w, h, raw, box, fill)
    if not res:
        sys.exit("рисунка не нашлось: слишком бледный контур или тёмное фото")
    cw, ch, rgba = res
    png(dst, cw, ch, rgba)
    print(f"{dst}  {cw}x{ch}  из {w}x{h}")
