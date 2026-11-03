"""マニュアルとはじめにお読みください（日本語と英語）が今のコードと合っているか。

キーの一覧・メニュー・タブの並び・設定の初めの値は `tools/doc_parts.py` が
本物の窓から作る。**キーを変えて作り直し忘れると、ここで落ちる**
（手で書き写すと必ずずれる）。
構造（見出しの階層・ページ内リンク・表の見出し）は `tools/check_html.py` で見る。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from _harness import Checker

from core.version import VERSION
from tools.build_release import DOC_FILES, TOP_APPS, TOP_FILES

c = Checker("docs")

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, SM_SILENT="1", SM_NO_ANNOUNCE="1")

parts = subprocess.run(
    [sys.executable, "-X", "utf8", str(ROOT / "tools" / "doc_parts.py"), "--check"],
    capture_output=True, text=True, env=ENV, timeout=180,
)
c.check(
    "マニュアルが今のコードと合っている（tools/doc_parts.py で作り直す）",
    parts.returncode == 0,
    (parts.stdout + parts.stderr).strip()[-300:],
)

html = subprocess.run(
    [sys.executable, "-X", "utf8", str(ROOT / "tools" / "check_html.py"),
     str(ROOT / "docs" / "manual.html"), str(ROOT / "docs" / "manual_en.html")],
    capture_output=True, text=True, timeout=60,
)
c.check("マニュアルの構造の検査が通る", html.returncode == 0, (html.stdout or "")[-400:])

manual = (ROOT / "docs" / "manual.html").read_text(encoding="utf-8")
manual_en = (ROOT / "docs" / "manual_en.html").read_text(encoding="utf-8")
readme = (ROOT / "docs" / "readme.txt").read_text(encoding="utf-8")
readme_en = (ROOT / "docs" / "readme_en.txt").read_text(encoding="utf-8")
license_text = (ROOT / "LICENSE.txt").read_text(encoding="utf-8")

# **全プロジェクトの決まり**（2026-10-24 から）: ライセンス名は Takahashi、
# 配布物の文書に AI（Anthropic の Claude）で作ったことを書く。
for name, text in (
    ("マニュアル", manual),
    ("英語のマニュアル", manual_en),
    ("はじめにお読みください", readme),
    ("英語の README", readme_en),
    ("ライセンス", license_text),
):
    c.check(f"{name}に AI で作ったことを書く", "Claude" in text and "AI" in text)
    c.check(f"{name}に著作権者の名前", "Takahashi" in text)
c.check("ライセンスは MIT", license_text.startswith("MIT License"))
c.check("著作権の表示", "Copyright (c) 2026 Takahashi" in license_text)

for name, text in (("マニュアル", manual), ("英語のマニュアル", manual_en)):
    c.check(f"{name}の版は core/version.py と同じ", f'<span class="version">{VERSION}</span>' in text)
for name, text in (("はじめにお読みください", readme), ("英語の README", readme_en)):
    c.check(f"{name}は版を差し込む", "{VERSION}" in text)

# --- 日本語と英語で同じ構成 ---
#
# マニュアルの章が言語で違うと、英語の版だけ古いまま残っても気づけない。
CHAPTER = re.compile(r'<h2 id="([a-z_]+)"')
c.equal("日本語と英語のマニュアルで章がそろう", CHAPTER.findall(manual_en), CHAPTER.findall(manual))
c.check("文書は全部ある", all(path.is_file() for path in DOC_FILES.values()))

# はじめにお読みくださいの説明と、配布物の並びが合う
c.check("はじめにお読みくださいの数が合う", f"ファイルが {len(TOP_FILES)} つと、アプリが {len(TOP_APPS)} つ" in readme)
c.check("英語の README の数が合う", f"{len(TOP_FILES)} files and {len(TOP_APPS)} app" in readme_en)
for name in TOP_FILES + TOP_APPS:
    c.check(f"はじめにお読みくださいに {name} がある", name in readme)
    c.check(f"英語の README に {name} がある", name in readme_en)

raise SystemExit(c.summary())
