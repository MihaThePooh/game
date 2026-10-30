#!/usr/bin/env python3
"""Сборка игры для сайта: dist/ с index.html и скриптами отдельными файлами.

В репозитории игра — один game.html: открывается с диска, без сервера.
На сайте же строгий CSP (script-src 'self') не пускает скрипты, встроенные
в страницу, — так подставленный в разметку чужой скрипт не выполнится.
Поэтому каждый <script> уходит в свой файл run-N.js, а в странице остаётся
ссылка на него. Порядок и смысл те же: скрипты без defer идут по очереди.
"""
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

if DIST.exists():
    shutil.rmtree(DIST)
DIST.mkdir()
html = (ROOT / "game.html").read_text(encoding="utf-8")
scripts = []


def extract(m: re.Match) -> str:
    name = f"run-{len(scripts) + 1}.js"
    scripts.append(name)
    (DIST / name).write_text(m.group(1).strip("\n") + "\n", encoding="utf-8")
    return f'<script src="{name}"></script>'


html = re.sub(r"<script>(.*?)</script>", extract, html, flags=re.S)
if not scripts:
    raise SystemExit("в game.html нет ни одного <script>")
(DIST / "index.html").write_text(html, encoding="utf-8")
for f in ("sw.js", "manifest.webmanifest"):
    shutil.copy(ROOT / f, DIST / f)
shutil.copytree(ROOT / "icons", DIST / "icons")
print(f"dist: index.html + {', '.join(scripts)}")
