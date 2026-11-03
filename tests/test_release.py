"""配布版（PyInstaller で固めた .app）に入れるものの見張り。**組み立てはしない。**

組み立てて確かめるのは `tools/build_release.py`（数分かかる）。ここでは、
**借りているのに同梱の一覧に無い部品**と、**配布物に入れてはいけない文字**を、
ふだんのテストで先に見つける。
"""

import ast
import json
from pathlib import Path

from _harness import Checker

from core.i18n import SUPPORTED
from core.sibling import BUNDLE_PARTS, DEV_DIRS_FILE, find_sibling
from integration.sforzando_load import SCRIPTS
from tools.build_release import DOC_FILES, PERSONAL, PERSONAL_TEXT, PRIVATE_WORDS, clean_source, find_words

c = Checker("release")

ROOT = Path(__file__).resolve().parents[1]

# --- 借りている部品は全部、同梱の一覧にある ---
#
# **一覧から漏れると、配布版でだけその機能が黙って止まる**（読み上げ名が
# 付かない・試聴できない）。ui/borrowed.py の `_load("名前", "フォルダ")` を読む。
tree = ast.parse((ROOT / "ui" / "borrowed.py").read_text(encoding="utf-8"))
loads = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_load":
        args = [a.value for a in node.args if isinstance(a, ast.Constant)]
        if args:
            name, subdir = args[0], (args[1] if len(args) > 1 else "ui")
            loads.append(f"{subdir}/{name}.py")
c.check("借りている部品を読めた", len(loads) >= 5, str(loads))
bundled = set(BUNDLE_PARTS.get("speech_and_preview", ()))
c.equal("読み上げと試聴の部品は全部同梱する", sorted(set(loads) - bundled), [])

# ptcore は使うものと、それらが読むものだけを同梱する（`load_ptcore` の呼び出しも全部見る）
index_parts = set(BUNDLE_PARTS.get("sample_index", ()))
c.check("ptcore の __init__ は入れない（関係の無いモジュールまで読む）", "ptcore/__init__.py" not in index_parts)
used = set()
sources = [ROOT / "app.py"]
for folder in ("core", "ui", "integration"):
    sources += sorted((ROOT / folder).glob("*.py"))
for path in sources:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "load_ptcore":
            used.update(a.value for a in node.args if isinstance(a, ast.Constant))
c.check("load_ptcore の呼び出しを読めた", {"splicename", "keydetect", "library", "dsp"} <= used, str(used))
c.equal("load_ptcore が読むものは全部同梱する", sorted(f"ptcore/{n}.py" for n in used if f"ptcore/{n}.py" not in index_parts), [])

# 一覧の部品が、手元に実在する（無ければ組み立てが止まる）
for project, patterns in BUNDLE_PARTS.items():
    base = find_sibling(project)
    c.check(f"借り先 {project} がある", base is not None)
    if base is None:
        continue
    for pattern in patterns:
        c.check(f"{project}/{pattern} がある", (base / pattern).is_file(), pattern)

# 同梱した ptcore が読む部品も同梱してある
base = find_sibling("sample_index")
for rel in sorted(index_parts) if base else ():
    for node in ast.walk(ast.parse((base / rel).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            c.check(f"{rel} が読む {node.module} も同梱する", f"ptcore/{node.module}.py" in index_parts)

# 読み込ませる道具の AppleScript も同梱する
c.equal(
    "道具の AppleScript は全部ある",
    [name for name in SCRIPTS if not (ROOT / "tools" / name).is_file()],
    [],
)
spec = (ROOT / "tools" / "release.spec").read_text(encoding="utf-8")
c.check("spec が道具の AppleScript を同梱する", "SCRIPTS" in spec)
c.check("spec が借り物を同梱する", "BUNDLE_PARTS" in spec)
c.check("配布版は ad-hoc で署名する（証明書の名前を入れない）", "codesign_identity=None" in spec)
c.check("配布版のバンドル ID は手元の版と分ける", "local.takahashi.sfzbuilder" in spec)

# --- 同梱する写しからコメントと説明文を除く ---
#
# .app の中の .py は平文で残り、コンパイルしたコードにも説明文は文字列として残る。
src = (
    '"""別のアプリと合わせる。"""\n'
    "# 手元のノートを見る\n"
    "def f(x):\n"
    '    """別のアプリの写し。"""\n'
    "    return x + 1  # 同期の話\n"
    "class C:\n"
    '    """説明だけ。"""\n'
    "MESSAGE = 'これは残す'\n"
)
out = clean_source(src)
for word in ("別のアプリ", "手元のノート", "同期の話", "説明だけ"):
    c.check(f"写しに「{word}」が残らない", word not in out, out)
c.check("文字列の定数は残す", "これは残す" in out)
space: dict = {}
exec(compile(out, "<clean>", "exec"), space)
c.equal("動きは変わらない", space["f"](1), 2)

# --- 借り物は中立の名前で呼ぶ ---
#
# 手元の本当のフォルダ名は sibling_dirs.json（公開しない）にだけ書く。
# 公開しているソースには検索語の設定が無いので、この先は作者の手元でだけ確かめる。
if DEV_DIRS_FILE.is_file():
    dev = json.loads(DEV_DIRS_FILE.read_text(encoding="utf-8"))
    c.equal("手元の名前の対応が同梱の一覧と合う", set(dev), set(BUNDLE_PARTS))
    c.check("検索語がある", bool(PERSONAL and PERSONAL_TEXT and PRIVATE_WORDS))
    for real in dev.values():
        c.check(f"検査は本当の名前 {real} を見つけられる", bool(find_words(real, PRIVATE_WORDS)))
    for name in BUNDLE_PARTS:
        c.equal(f"中立の名前 {name} は検索語に当たらない", find_words(name, PRIVATE_WORDS), [])

# --- 配布物に入るものに、作者の名前・手元のパス・メールアドレス・関係の無い名前が無い ---
#
# 以前は core/slots.py の既定値と、いくつかの説明文に作者の手元のパスがあった。
# 固めると zlib で縮むので、配布物の中の文字を探すだけでは見つからない
# （build_release.py は固めた部品の中まで探すが、ここで先に止める）。
# **借り物は、同梱する形（コメントと説明文を除いた写し）で調べる。** 元のファイルの
# コメントには開発の経過が残っているが、それは配布物に入らない。
sources += [ROOT / "tools" / name for name in SCRIPTS]
sources += list(DOC_FILES.values())
sources += sorted((ROOT / "resources").glob("*.lproj/InfoPlist.strings"))
sources.append(ROOT / "requirements.txt")
words = PERSONAL + PERSONAL_TEXT + PRIVATE_WORDS
found = [
    f"{path.name}: {hit}"
    for path in sources
    for hit in find_words(path.read_text(encoding="utf-8", errors="replace"), words)
]
for project, patterns in BUNDLE_PARTS.items():
    base = find_sibling(project)
    for pattern in patterns if base else ():
        text = clean_source((base / pattern).read_text(encoding="utf-8"))
        found += [f"{project}/{pattern}: {hit}" for hit in find_words(text, words)]
c.equal("配布物に入るものに個人の情報と関係の無い名前が無い", found, [])
c.check("調べたファイルの数", len(sources) > 30, str(len(sources)))

# Finder の名前の訳（Mac の言語で .app の名前が変わる）
for lang in SUPPORTED:
    c.check(f"{lang} の lproj がある", (ROOT / "resources" / f"{lang}.lproj" / "InfoPlist.strings").is_file())

raise SystemExit(c.summary())
