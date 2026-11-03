"""配布物（zip）を作る。確かめる → 組み立てる → 並べる → zip → 中身の検証、の順。

    python3.14 -X utf8 tools/build_release.py
        dist/PT SFZビルダー_<版>.zip を作る
    python3.14 -X utf8 tools/build_release.py --dirty
        試し（書きかけの変更があっても止めない。コミットに + が付く）
    python3.14 -X utf8 tools/build_release.py --app-only
        .app の組み立てと確認だけ（zip は作らない）

配布版は **PyInstaller で固めた .app**（python も wx も pyobjc も中に入る。
受け取った人は python を入れなくてよい）。

### 組み立てに使う python

**python.org の python3.14 で組み立てる**（この道具を動かす python）。Homebrew の python で
固めると、Homebrew の OpenSSL などが入り、それぞれのライセンスを別に集めることになる。
要る部品（PyInstaller・wx・pyobjc・just_playback）は python.org の python に入っている。

工程（どこかで落ちたら zip を作らない）:

  1. 書きかけの変更  同梱するソースと、配布物の印（コミット）をずらさない
  2. テスト          tests/run_all.py（音と読み上げは止める）
  3. マニュアル      tools/doc_parts.py --check と check_html.py
  4. .app の組み立て PyInstaller（tools/release.spec）。build/release/ に作る
  5. .app の確認     中の実行ファイルで --selftest と起動の確認を日本語と英語で（ホームは一時フォルダ）。署名が ad-hoc か
  6. 同梱部品のライセンス  PyInstaller の目録（toc）と各部品の RECORD から作る
  7. 並べる          はじめにお読みください・マニュアル・ライセンス・.app
  8. zip             ditto（.app の中のシンボリックリンクと署名を壊さない）
  9. zip の検証      展開して署名と --selftest と起動の確認（日本語と英語）、並び、txt の形、個人の情報と関係の無い名前
                     （**固めた python の部品の中まで**探す。zlib で縮めてあるので、
                     ファイルの中の文字を探すだけでは見つからない）

**署名は ad-hoc。** 手元の証明書で署名すると、
証明書の名前が配布物に入る。そのかわり受け取った人は、新しい版に入れ替えるたびに
アクセシビリティの許可を入れ直す（マニュアル 3.3 に書いた）。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.i18n import ENV_NAME, SUPPORTED  # noqa: E402
from core.sibling import BUNDLE_PARTS, find_sibling  # noqa: E402
from core.version import BUNDLE_NAME, VERSION  # noqa: E402

APP_NAME = BUNDLE_NAME
EXE_NAME = "SFZBuilder"
BUILD = ROOT / "build" / "release"
DIST = ROOT / "dist"
SPEC = ROOT / "tools" / "release.spec"
APP = BUILD / "dist" / f"{APP_NAME}.app"
WORK = BUILD / "work"
STAGE = BUILD / "stage"
# コメントと説明文を除いた写しの置き場所（tools/release.spec が作る）
CLEAN = BUILD / "clean"
FOLDER = f"{APP_NAME}_{VERSION}"
ZIP = DIST / f"{FOLDER}.zip"
DOCS = ROOT / "docs"

# 配る文書（配布物の中の名前 → 元のファイル）。テストと公開の道具もこれを読む
DOC_FILES = {
    "はじめにお読みください.txt": DOCS / "readme.txt",
    "マニュアル.html": DOCS / "manual.html",
    "マニュアル.txt": DOCS / "manual.txt",
    "ライセンス.txt": ROOT / "LICENSE.txt",
    "README (English).txt": DOCS / "readme_en.txt",
    "Manual (English).html": DOCS / "manual_en.html",
    "Manual (English).txt": DOCS / "manual_en.txt",
}
THIRD_PARTY = "同梱部品のライセンス.txt"
# 配布物の直下に並べるもの（はじめにお読みくださいの説明と合わせる。ずれたら止める）
TOP_FILES = (*DOC_FILES, THIRD_PARTY)
TOP_APPS = (f"{APP_NAME}.app",)

# 検査の検索語（個人の情報・関係の無い名前）は**ソースに書かない**（検索語そのものが
# 個人の情報になる）。作者の手元の release_private.json にだけ置く。無ければ、
# その検査はしない（公開しているソースから組み立てるとき）
PRIVATE_FILE = ROOT / "release_private.json"
_WORD_LISTS = ("personal", "personal_text", "words")


def read_private(path: Path) -> dict:
    """検索語を読む。ファイルが無ければ空（公開しているソースから組み立てるとき）。

    **壊れているときは止める。** 読めないまま空にすると、検査が全部黙って素通りして
    「確かめた」と表示される。語は小文字にそろえる（どの検査も大文字小文字を問わない）。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[エラー] {path.name} を読めません（{exc}）") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"[エラー] {path.name} の形が違います")
    for key in _WORD_LISTS:
        words = data.get(key)
        if not (words and isinstance(words, list) and all(w and isinstance(w, str) for w in words)):
            raise SystemExit(f"[エラー] {path.name} の {key} が語の並びではありません")
        data[key] = tuple(w.lower() for w in words)
    return data


_PRIVATE = read_private(PRIVATE_FILE)
# 配布物に入っていてはいけないもの（作者の名前など）。**全部のファイルで探す**
PERSONAL = _PRIVATE.get("personal", ())
# 自分たちで書いた文字のファイルでだけ探すもの（メールアドレスの印と手元のパス）。
# python 本体や標準ライブラリ、同梱部品のライセンスの文書には、関係のない人の
# アドレスが入っている
PERSONAL_TEXT = _PRIVATE.get("personal_text", ())
# 自分たちで書いた文字のファイルと、コンパイルしたコードに入っていてはいけない言葉
# （ほかのプロジェクトの名前・手元のメモ）
PRIVATE_WORDS = _PRIVATE.get("words", ())
TEXT_SUFFIXES = (".py", ".txt", ".html", ".md", ".plist", ".strings", ".sh", ".json", ".applescript")
# .app の中の、自分たちで書いたもの（同梱した部品の .py と AppleScript）
OWN_INSIDE_APP = ("siblings", "tools")
# 自分たちのコードのパッケージ（写しから組み立てて、コンパイルしたものを調べる）
OWN_PACKAGES = ("core", "ui", "integration")
# 固めた python の部品のうち、自分たちのもの（中の文字まで探す）
OWN_MODULES = ("app", *OWN_PACKAGES)

RESULTS: list[tuple[str, bool, str]] = []


def find_words(text: str, words) -> list[str]:
    """文字列の中にある検索語（大文字小文字を問わない。語は小文字にしてある）。"""
    lowered = text.lower()
    return [word for word in words if word in lowered]


def clean_source(text: str) -> str:
    """同梱する .py から、**コメントと説明文（docstring）を除く**（動きは変えない）。

    .app の中の .py は平文のまま入り、コンパイルしたコードにも説明文は文字列として残る。
    開発の経過を配布物に出さない。ast で読んで書き直すとコメントは消える。説明文を消すと
    中身が空になるところは pass にする。
    """
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body.pop(0)
                if not body and not isinstance(node, ast.Module):
                    body.append(ast.Pass())
    return ast.unparse(tree) + "\n"


def step(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    tail = f" — {detail}" if detail else ""
    print(f"{'OK' if ok else 'NG'}  {name}{tail}", flush=True)
    return ok


def run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)


def last_line(done: subprocess.CompletedProcess) -> str:
    for text in (done.stderr, done.stdout):
        lines = (text or "").strip().splitlines()
        if lines:
            return lines[-1]
    return "出力なし"


def silent_env(**extra: str) -> dict:
    """音も読み上げも出さない（組み立ての最中に VoiceOver が読み出さないように）。"""
    return dict(os.environ, SM_SILENT="1", SM_NO_ANNOUNCE="1", **extra)


# --------------------------------------------------------------------------
# 1〜3. 確かめる
# --------------------------------------------------------------------------


def git_lines(*args: str) -> str:
    return run(["git", *args], cwd=ROOT).stdout.strip()


def git_commit() -> str:
    commit = git_lines("rev-parse", "--short", "HEAD") or "?"
    dirty = git_lines("status", "--porcelain")
    return commit + ("+" if dirty else "")


def check_clean(allow_dirty: bool) -> bool:
    name = "1. 書きかけの変更"
    dirty = [line for line in git_lines("status", "--porcelain").splitlines() if line.strip()]
    if dirty and not allow_dirty:
        return step(name, False, f"{len(dirty)} 件（コミットしてから作る。試すなら --dirty）: {dirty[0]}")
    return step(name, True, "なし" if not dirty else f"{len(dirty)} 件あるが --dirty で続ける")


def run_tests() -> bool:
    done = run([sys.executable, "-X", "utf8", ROOT / "tests" / "run_all.py"], cwd=ROOT, env=silent_env())
    return step("2. テスト", done.returncode == 0, last_line(done))


def check_docs(allow_dirty: bool) -> bool:
    name = "3. マニュアル"
    tool = ROOT / "tools" / "doc_parts.py"
    parts = run([sys.executable, "-X", "utf8", tool, "--check"], cwd=ROOT, env=silent_env())
    if parts.returncode != 0:
        if not allow_dirty:
            return step(name, False, "コードから作る部分が古い。tools/doc_parts.py で作り直してコミットする")
        parts = run([sys.executable, "-X", "utf8", tool], cwd=ROOT, env=silent_env())
        if parts.returncode != 0:
            return step(name, False, last_line(parts))
    html = run([sys.executable, "-X", "utf8", ROOT / "tools" / "check_html.py", DOCS / "manual.html", DOCS / "manual_en.html"], cwd=ROOT)
    if html.returncode != 0:
        return step(name, False, "check_html: " + last_line(html))
    return step(name, True, "コードと合っている。構造の検査も通過")


# --------------------------------------------------------------------------
# 4〜5. 組み立てて確かめる
# --------------------------------------------------------------------------


def build_app() -> bool:
    name = "4. .app の組み立て"
    if not sys.base_prefix.startswith("/Library/Frameworks/Python.framework"):
        return step(name, False, f"python.org の python で動かしてください（いまは {sys.base_prefix}）")
    if BUILD.exists():
        shutil.rmtree(BUILD)
    env = dict(
        os.environ,
        SFZ_BUILD_DATE=time.strftime("%Y-%m-%d %H:%M"),
        SFZ_GIT_COMMIT=git_commit(),
        PYTHONDONTWRITEBYTECODE="1",
    )
    done = run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
         "--distpath", BUILD / "dist", "--workpath", WORK, SPEC],
        cwd=ROOT, env=env,
    )
    if done.returncode != 0 or not APP.is_dir():
        return step(name, False, last_line(done))
    size = sum(p.stat().st_size for p in APP.rglob("*") if p.is_file() and not p.is_symlink())
    return step(name, True, f"{size / 1e6:.0f} MB、python {sys.version.split()[0]}、コミット {env['SFZ_GIT_COMMIT']}")


def selftest(app: Path, lang: str = "ja") -> tuple[bool, str]:
    """組み上げた .app の中の実行ファイルで `--selftest`。**ホームは一時フォルダ**（初めて使う人と同じ）。

    **日本語と英語の両方で通す**（言語は起動したときに決まる）。
    """
    exe = app / "Contents" / "MacOS" / EXE_NAME
    with tempfile.TemporaryDirectory(prefix="sfz_release_home_") as home:
        try:
            done = run([exe, "--selftest"], timeout=240, env=silent_env(HOME=home, **{ENV_NAME: lang}))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        try:
            report = json.loads((done.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return False, last_line(done)
        slots = str(report.get("slots_dir", ""))
        index = str(report.get("splice_index", ""))
        if (
            done.returncode != 0
            or not report.get("ok")
            or not report.get("frozen")
            or report.get("version") != VERSION
            or not report.get("loader")
            or not slots.startswith(home)
            or not index.startswith(home)
        ):
            return False, json.dumps(report, ensure_ascii=False)
        # 確かめるだけで、ホームに何も作っていないこと（置き場所は割り当てたときに作る）
        made = sorted(str(p.relative_to(home)) for p in Path(home).rglob("*"))
    if made:
        return False, f"--selftest がホームに作ったもの: {made[:5]}"
    return True, (
        f"版 {report['version']}、伸縮 {report['render_backend']}、python {report['python']}、"
        f"置き場所 ~/{Path(slots).relative_to(Path(home)).as_posix()}"
    )


def smoke(app: Path, lang: str = "ja") -> tuple[bool, str]:
    """**ふつうの起動と同じ道**を通す（`SFZBUILDER_SMOKE=1`。窓は出さず、Pro Tools にも触らない）。

    `--selftest` は窓を組み立てるだけで、ログ・アプリ名・メニューの日本語化・
    イベントの流れを通らない。ホームを
    一時フォルダにして動かし、そこにログができて「Startup check finished」と
    書いてあれば通った証拠。
    """
    exe = app / "Contents" / "MacOS" / EXE_NAME
    with tempfile.TemporaryDirectory(prefix="sfz_release_smoke_") as home:
        try:
            done = run([exe], timeout=120, env=silent_env(HOME=home, SFZBUILDER_SMOKE="1", **{ENV_NAME: lang}))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"起動の確認: {exc}"
        log = Path(home) / "Library" / "Logs" / "SfzBuilder.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if done.returncode != 0:
        return False, f"起動の確認: 終了コード {done.returncode}。{text.strip()[-300:] or last_line(done)}"
    if f"started (packaged version {VERSION})" not in text or "Startup check finished" not in text:
        return False, f"起動の確認: ログが足りない（{text.strip()[-300:] or 'ログが無い'}）"
    return True, "起動の道も通った"


def signature_problems(app: Path) -> list[str]:
    """署名が壊れていないか、ad-hoc か（証明書の名前が入っていないか）。"""
    problems = []
    verify = run(["codesign", "--verify", "--deep", "--strict", app])
    if verify.returncode != 0:
        problems.append("署名の検証: " + last_line(verify))
    info = run(["codesign", "-dvv", app]).stderr
    if "Signature=adhoc" not in info:
        problems.append("ad-hoc の署名ではない")
    if "Authority=" in info:
        problems.append("証明書の名前が入っている")
    return problems


def check_app() -> bool:
    ok, detail = selftest(APP)
    if not ok:
        return step("5. .app の確認", False, f"--selftest: {detail}")
    ok, english = selftest(APP, "en")
    if not ok:
        return step("5. .app の確認", False, f"--selftest（英語）: {english}")
    if not all((APP / "Contents" / "Resources" / f"{lang}.lproj" / "InfoPlist.strings").is_file() for lang in SUPPORTED):
        return step("5. .app の確認", False, "Finder の名前の訳（lproj）が無い")
    started, said = smoke(APP)
    if not started:
        return step("5. .app の確認", False, said)
    started, english = smoke(APP, "en")
    if not started:
        return step("5. .app の確認", False, f"英語: {english}")
    problems = signature_problems(APP)
    if problems:
        return step("5. .app の確認", False, "、".join(problems))
    hits, checked = frozen_hits(APP)
    if hits:
        return step("5. .app の確認", False, f"コンパイルしたコードに関係の無い名前や個人の情報: {'、'.join(hits[:5])}")
    scanned = (f"コンパイルしたコード {checked} 個に関係の無い名前は無い" if PERSONAL
               else "検索語が無いので、関係の無い名前は調べていない")
    return step("5. .app の確認", True, f"{detail}。{said}。英語でも起動。署名は ad-hoc。{scanned}")


# --------------------------------------------------------------------------
# 6. 同梱部品のライセンス（実際に入ったファイルから）
# --------------------------------------------------------------------------

DOC_SUFFIXES = ("", ".txt", ".md", ".rst")
LICENSE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.I)


def toc_sources() -> set[Path]:
    """PyInstaller の目録（build/release/work/release/*.toc）から、.app に入れた元のファイルを全部拾う。"""
    found: set[Path] = set()

    def walk(node) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) == 3 and all(isinstance(x, str) for x in node):
                path = Path(node[1])
                if path.is_absolute() and path.is_file():
                    found.add(path.resolve())
                return
            for child in node:
                walk(child)

    for toc in sorted((WORK / SPEC.stem).glob("*.toc")):
        try:
            walk(ast.literal_eval(toc.read_text(encoding="utf-8")))
        except (ValueError, SyntaxError):
            continue
    return found


def dist_index() -> dict[Path, metadata.Distribution]:
    """site-packages のファイル → その部品（RECORD）。"""
    owner: dict[Path, metadata.Distribution] = {}
    for dist in metadata.distributions():
        for rel in dist.files or []:
            try:
                owner[Path(dist.locate_file(rel)).resolve()] = dist
            except (OSError, ValueError):
                continue
    return owner


def license_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """部品の dist-info の中のライセンス文書（自分の dist-info のものだけ。名前は文書の拡張子に限る）。"""
    texts = []
    for rel in dist.files or []:
        parts = Path(str(rel)).parts
        if not parts or not parts[0].endswith(".dist-info"):
            continue
        name = parts[-1]
        if LICENSE_NAME.match(name) and Path(name).suffix.lower() in DOC_SUFFIXES:
            try:
                text = Path(dist.locate_file(rel)).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # GNU の条文は改ページの記号（\f）で区切ってある。印刷の区切りなので空行にする（条文は変えない）
            texts.append((str(rel), text.replace("\f", "\n")))
    return texts


def project_of(dist: metadata.Distribution) -> str:
    """部品の出どころ（同じプロジェクトの部品を見分ける。PyObjC は 1 つのプロジェクトを部品に分けて配っている）。"""
    meta = dist.metadata
    urls = [meta.get("Home-page") or ""] + [u.split(",", 1)[-1].strip() for u in meta.get_all("Project-URL") or []]
    return next((u.rstrip("/").lower() for u in urls if "github.com" in u), (urls[0] or "").rstrip("/").lower())


def license_label(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    label = meta.get("License-Expression") or ""
    if not label:
        text = (meta.get("License") or "").strip()
        label = text if text and len(text) < 120 else ""
    if not label:
        classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
        label = "、".join(classifiers)
    return label or "（部品の文書を参照）"


def collect_licenses() -> tuple[bool, str, str]:
    """(成否, 文書, 詳細)。**どの部品にも当たらないファイルがあれば止める**（黙って一覧から落とさない）。"""
    sources = toc_sources()
    if not sources:
        return False, "", "PyInstaller の目録が読めない"
    owner = dist_index()
    own_roots = [ROOT.resolve()] + [p.resolve() for p in (find_sibling(n) for n in BUNDLE_PARTS) if p]
    base = Path(sys.base_prefix).resolve()
    site = [Path(p).resolve() for p in sys.path if p.endswith("site-packages")]
    pyinstaller = Path(__import__("PyInstaller").__file__).resolve().parent
    used: dict[str, metadata.Distribution] = {}
    python_files = 0
    unknown = []
    for path in sorted(sources):
        # **部品の持ち主を先に見る**（先に「自分たちのもの」で弾くと、部品が一覧から黙って落ちる）
        dist = owner.get(path)
        if dist is not None:
            used[dist.metadata["Name"]] = dist
            continue
        if any(path.is_relative_to(r) for r in own_roots):
            continue
        if path.is_relative_to(pyinstaller):
            used["pyinstaller"] = metadata.distribution("pyinstaller")
            continue
        if path.is_relative_to(base) and not any(path.is_relative_to(s) for s in site):
            python_files += 1
            continue
        unknown.append(str(path))
    # ブートローダー（.app の実行ファイル）は目録に載らないことがある。必ず足す
    used.setdefault("pyinstaller", metadata.distribution("pyinstaller"))
    if unknown:
        return False, "", f"持ち主の分からないファイルが {len(unknown)} 件: {unknown[0]}"
    names = sorted(used, key=str.lower)
    lines = [
        f"{APP_NAME} {VERSION} に同梱している部品のライセンス",
        "",
        "この .app には、次の部品が入っています（PyInstaller でまとめたとき、実際に入ったファイルから作った一覧です）。",
        f"部品は {len(names) + 1} 個です。それぞれの条件の全文を、この下に部品ごとに載せます。",
        "",
        f"・Python {sys.version.split()[0]}（Python Software Foundation License。標準ライブラリと、Python に含まれる部品）",
    ]
    for name in names:
        dist = used[name]
        lines.append(f"・{name} {dist.version}（{license_label(dist)}）")
    lines += [
        "",
        "このアプリ自身（作者 Takahashi）のライセンスは「ライセンス.txt」にあります。",
        "アプリの中には、作者が作った別の道具の部品（素材の名前の解析・索引・長さの変換と、"
        "読み上げ・試聴・効果音の部品）も入っています。これも「ライセンス.txt」の条件で配ります。",
        "",
    ]
    python_license = base / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"
    lines += ["=" * 70, f"Python {sys.version.split()[0]}", "=" * 70, "",
              python_license.read_text(encoding="utf-8", errors="replace").strip(), ""]
    missing, borrowed_texts = [], []
    for name in names:
        dist = used[name]
        texts = license_texts(dist)
        lines += ["=" * 70, f"{name} {dist.version}（{license_label(dist)}）", "=" * 70, ""]
        if name.lower() == "pyinstaller":
            lines += ["PyInstaller のブートローダー（.app の中の実行ファイル）と、起動時に使う部品が入っています。",
                      "PyInstaller の条件は、PyInstaller でまとめたプログラムを、どのような条件でも配ってよいとしています"
                      "（下の文書の「Bootloader Exception」）。", ""]
        if not texts:
            # 部品の配布物に文書が無いとき: 同じプロジェクトの、同じ条件の部品の文書を載せる（MIT は全文を添える条件のため）
            sibling = next((other for other in names if other != name and project_of(used[other]) == project_of(dist)
                            and license_label(used[other]) == license_label(dist) and license_texts(used[other])), None)
            if sibling is None:
                missing.append(name)
                lines += [f"この部品の配布物にはライセンスの文書が入っていません。条件は「{license_label(dist)}」です。",
                          f"部品の案内: {project_of(dist)}", ""]
            else:
                borrowed_texts.append(name)
                texts = license_texts(used[sibling])
                lines += [f"この部品の配布物にはライセンスの文書が入っていないので、同じプロジェクト（{project_of(dist)}）の"
                          f"同じ条件の部品 {sibling} の文書を載せます。", ""]
        for rel, text in texts:
            lines += [f"--- {rel} ---", "", text.strip(), ""]
    detail = f"部品 {len(names) + 1} 個（{'、'.join(names)}。Python の標準ライブラリなど {python_files} ファイル）"
    if borrowed_texts:
        detail += f"。同じプロジェクトの文書を載せたもの: {'、'.join(borrowed_texts)}"
    if missing:
        return False, "", detail + f"。ライセンスの文書が見つからないもの: {'、'.join(missing)}"
    return True, "\n".join(lines) + "\n", detail


# --------------------------------------------------------------------------
# 7〜9. 並べて zip にし、確かめる
# --------------------------------------------------------------------------


def write_txt(path: Path, text: str) -> None:
    """配る txt は BOM 付き UTF-8・CRLF（古い日本語のエディタで化けない）。"""
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8-sig", newline="\r\n")


def doc_text(src: Path) -> str:
    """配る文書の中身（BOM を除き、版を差し込む）。"""
    return src.read_text(encoding="utf-8-sig").replace("{VERSION}", VERSION)


def stage_files(third_party: str) -> bool:
    name = "7. 並べる"
    if STAGE.exists():
        shutil.rmtree(STAGE)
    folder = STAGE / FOLDER
    folder.mkdir(parents=True)
    copy = run(["ditto", APP, folder / APP.name])
    if copy.returncode != 0:
        return step(name, False, last_line(copy))
    for doc, src in DOC_FILES.items():
        if doc.endswith(".txt"):
            write_txt(folder / doc, doc_text(src))
        else:
            shutil.copy2(src, folder / doc)
    write_txt(folder / THIRD_PARTY, third_party)
    names = sorted(p.name for p in folder.iterdir())
    want = sorted(TOP_FILES + TOP_APPS)
    if names != want:
        return step(name, False, f"並びが説明と違う: {names}")
    return step(name, True, f"ファイル {len(TOP_FILES)} つとアプリ {len(TOP_APPS)} つ")


def make_zip() -> bool:
    DIST.mkdir(exist_ok=True)
    if ZIP.exists():
        ZIP.unlink()
    # --norsrc --noextattr: 拡張属性（隔離の印など）を __MACOSX に入れない。署名は .app の中の CodeResources にある
    done = run(["ditto", "-c", "-k", "--norsrc", "--noextattr", "--keepParent", STAGE / FOLDER, ZIP])
    if done.returncode != 0 or not ZIP.is_file():
        return step("8. zip", False, last_line(done))
    return step("8. zip", True, f"{ZIP.name}（{ZIP.stat().st_size / 1e6:.1f} MB）")


def _own_text(folder: Path, path: Path) -> bool:
    """自分たちで書いた文字のファイルか（メールアドレスの印と関係の無い名前も探す対象）。

    直下の文書（同梱部品のライセンスを除く）、.app の中の同梱した部品と AppleScript、Info.plist、名前の訳（*.lproj）。
    python 本体や部品のファイルは含めない。
    """
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    rel = path.relative_to(folder)
    if len(rel.parts) == 1:
        return rel.name != THIRD_PARTY
    return (
        rel.parts[1:] == ("Contents", "Info.plist")
        or (rel.parts[1:3] == ("Contents", "Resources") and rel.parent.name.endswith(".lproj"))
        or any(part in rel.parts for part in OWN_INSIDE_APP)
    )


def personal_hits(folder: Path) -> list[str]:
    hits = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes().lower()
        words = PERSONAL + (PERSONAL_TEXT if _own_text(folder, path) else ())
        for word in words:
            if word.encode() in data:
                hits.append(f"{path.relative_to(folder)}（{word}）")
                break
    return hits


def private_hits(folder: Path) -> list[str]:
    """自分たちで書いた文字のファイルに、ほかのプロジェクトの名前・手元のメモが無いか。"""
    hits = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        named = find_words(rel, PRIVATE_WORDS + PERSONAL)  # 名前も見る
        if named:
            hits.append(f"{rel}（名前に {'・'.join(named)}）")
            continue
        if path.is_symlink() or not path.is_file() or not _own_text(folder, path):
            continue
        found = find_words(path.read_text(encoding="utf-8", errors="replace"), PRIVATE_WORDS)
        if found:
            hits.append(f"{rel}（{'・'.join(found)}）")
    return hits


def _strings_in(value) -> list[str]:
    """コードオブジェクトの定数の中の文字。タプルと frozenset の中も見る。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, bytes):
        return [value.decode("utf-8", "replace")]
    if isinstance(value, (tuple, frozenset)):
        return [s for item in value for s in _strings_in(item)]
    return []


def _strings_of(code) -> list[str]:
    """コードオブジェクトの中の文字（説明文・定数・名前）。入れ子の関数やクラスの中まで。"""
    found: list[str] = []
    stack = [code]
    while stack:
        current = stack.pop()
        found += list(current.co_names) + list(current.co_varnames)
        for const in current.co_consts:
            if hasattr(const, "co_consts"):
                stack.append(const)
            else:
                found += _strings_in(const)
    return found


def frozen_hits(app: Path) -> tuple[list[str], int]:
    """固めた python の部品（実行ファイルの中の PYZ）の中の、自分たちのモジュールの文字を探す。

    **ファイルの中の文字を探すだけでは見つからない。** PYZ は zlib で縮めてあるので、
    説明文に手元のパスが残っていても、上の `personal_hits` は素通りする。
    戻り値は (当たったもの, 調べたモジュールの数)。
    """
    from PyInstaller.archive.readers import CArchiveReader

    exe = app / "Contents" / "MacOS" / EXE_NAME
    pkg = CArchiveReader(str(exe))
    pyz_name = next(n for n in pkg.toc if n.upper().startswith("PYZ"))
    pyz = pkg.open_embedded_archive(pyz_name)
    words = PERSONAL + PERSONAL_TEXT + PRIVATE_WORDS
    hits: list[str] = []
    checked = 0
    targets = [n for n in pyz.toc if n.split(".")[0] in OWN_MODULES]
    for name in targets:
        try:
            code = pyz.extract(name)
        except Exception as exc:
            hits.append(f"{name}（読めない: {exc}）")
            continue
        if code is None:
            continue
        checked += 1
        hits += [f"{name}（{word}）" for word in find_words("\n".join(_strings_of(code)), words)][:1]
    # 入口の app.py は PYZ ではなく、実行ファイルの中に別に入っている
    for name in pkg.toc:
        if name != "app":
            continue
        data = pkg.extract(name)
        try:
            import marshal

            text = "\n".join(_strings_of(marshal.loads(data)))
        except Exception:
            text = (data or b"").decode("utf-8", "replace")
        checked += 1
        hits += [f"app（{word}）" for word in find_words(text, words)][:1]
    return hits, checked


def txt_problems(folder: Path) -> list[str]:
    problems = []
    for name in TOP_FILES:
        if not name.endswith(".txt"):
            continue
        data = (folder / name).read_bytes()
        if not data.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{name} に BOM が無い")
        if b"\n" in data.replace(b"\r\n", b""):
            problems.append(f"{name} に CRLF でない改行がある")
        if re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", data):
            problems.append(f"{name} に制御文字がある")
    return problems


def _zip_layout() -> tuple[list[str], list[str]]:
    """(問題, UTF-8 の印が無い日本語の名前)。

    **ditto の zip は、日本語の名前に UTF-8 の印（0x800）を付けない。** 名前は UTF-8 なので、
    そのとおりに読む（Mac の「アーカイブユーティリティ」も UTF-8 として読むので化けない）。
    """
    with zipfile.ZipFile(ZIP, metadata_encoding="utf-8") as zf:
        bad = zf.testzip()
        if bad is not None:
            return [f"壊れたファイル: {bad}"], []
        names = zf.namelist()
        tops = sorted({n.split("/", 2)[1] for n in names if n.count("/") >= 1 and n.split("/", 2)[1]})
        roots = {n.split("/", 1)[0] for n in names}
        unflagged = [i.filename for i in zf.infolist() if not i.filename.isascii() and not i.flag_bits & 0x800]
    problems = []
    if roots != {FOLDER}:
        problems.append(f"最上位のフォルダが 1 つでない: {sorted(roots)}")
    if tops != sorted(TOP_FILES + TOP_APPS):
        problems.append(f"直下の並びが説明と違う: {tops}")
    junk = ("__MACOSX", ".DS_Store", "__pycache__")
    if any(j in n for n in names for j in junk):
        problems.append("__MACOSX・.DS_Store・__pycache__ のどれかが入っている")
    return problems, unflagged


def verify_zip() -> bool:
    name = "9. zip の検証"
    problems, unflagged = _zip_layout()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        done = run(["ditto", "-x", "-k", ZIP, out])
        if done.returncode != 0:
            return step(name, False, "展開できない: " + last_line(done))
        folder = out / FOLDER
        app = folder / f"{APP_NAME}.app"
        problems += signature_problems(app)
        for lang in SUPPORTED:
            ok, detail = selftest(app, lang)
            if not ok:
                problems.append(f"展開した .app の --selftest（{lang}）: {detail}")
            started, said = smoke(app, lang)
            if not started:
                problems.append(f"展開した .app の{said}（{lang}）")
        # --selftest のあとも署名が壊れていないこと（.app の中に書いていないこと）
        problems += [f"--selftest のあと: {p}" for p in signature_problems(app)]
        problems += txt_problems(folder)
        hits = personal_hits(folder)
        if hits:
            problems.append(f"個人の情報が入っている: {'、'.join(hits[:5])}")
        hits = private_hits(folder)
        if hits:
            problems.append(f"関係の無い名前が入っている: {'、'.join(hits[:5])}")
        hits, checked = frozen_hits(app)
        if hits:
            problems.append(f"コンパイルしたコードに関係の無い名前や個人の情報がある: {'、'.join(hits[:5])}")
        same = run(["diff", "-rq", STAGE / FOLDER, folder])
        if same.returncode != 0:
            problems.append("展開したものが並べたものと違う: " + last_line(same))
    if problems:
        return step(name, False, "、".join(problems))
    note = ""
    if unflagged:
        note = f"。日本語の名前に UTF-8 の印が無いもの {len(unflagged)} 件（Mac の展開では化けない）"
    digest = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    words = (f"個人の情報と関係の無い名前（固めた部品の中の {checked} モジュールまで）" if PERSONAL
             else "（検索語が無いので、個人の情報と関係の無い名前は調べていない）")
    return step(name, True, f"展開して署名・--selftest・起動の確認・並び・txt・{words}を"
                f"確かめた{note}。SHA-256 {digest[:16]}…")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="配布物（zip）を作る")
    ap.add_argument("--dirty", action="store_true", help="書きかけの変更があっても止めない（試し）")
    ap.add_argument("--app-only", action="store_true", help=".app の組み立てと確認だけ")
    args = ap.parse_args(argv)
    print(f"配布物: {FOLDER}（{ROOT}）", flush=True)
    print()
    if args.app_only:
        ok = build_app() and check_app()
        print()
        print(f"{'.app を作りました' if ok else '.app を作れませんでした'}: {APP}")
        return 0 if ok else 1
    ok = check_clean(args.dirty) and run_tests() and check_docs(args.dirty)
    ok = ok and build_app() and check_app()
    third_party = ""
    if ok:
        good, third_party, detail = collect_licenses()
        ok = step("6. 同梱部品のライセンス", good, detail)
    ok = ok and stage_files(third_party) and make_zip() and verify_zip()
    print()
    if not ok:
        failed = [name for name, good, _ in RESULTS if not good]
        print(f"配布物を作れませんでした。通らなかった工程: {'、'.join(failed)}")
        if ZIP.exists() and failed:
            ZIP.unlink()          # 検証に通らなかった zip は残さない
        return 1
    print(f"配布物ができました: {ZIP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
