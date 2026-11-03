# -*- mode: python ; coding: utf-8 -*-
# PT SFZビルダー（配布版）— PyInstaller の設定
#
# ★直接は使わない。tools/build_release.py が、組み立て・確認・ライセンスの収集・zip まで行う。
#   python3.14 -X utf8 tools/build_release.py
#
# 出力: build/release/dist/PT SFZビルダー.app（windowed / onedir / arm64）
# - 中の実行ファイルは ASCII 名（SFZBuilder）。.app の名前は読み上げで分かるように日本語
#   （中の実行ファイルに日本語の名前を付けると署名の封印が壊れる）
# - 開発言語は en（Info.plist の既定の説明も英語）。日本語は resources/ja.lproj から出る。
#   画面の言語の決め方（core/i18n.py）と同じく、日本語も英語も無い Mac では英語になる
# - 署名は ad-hoc（PyInstaller の既定）。**手元の証明書では署名しない**（証明書の名前が配布物に入る）
# - 借りる部品は .app の中の siblings/ に、中立の名前のフォルダで置く（core/sibling.py の BUNDLE_PARTS）。
#   ファイルの場所を指定して読む作りのため、ファイルのまま置く。**コメントと説明文を除いた写し**を入れる
#   （平文で残るので、開発の経過を出さない）
# - AppleScript の道具（tools/*.applescript）も、ファイルのまま tools/ に置く（osascript に渡すため）
# - ファイルのまま置いた .py は PyInstaller が中を調べないので、それらが import するもの（標準ライブラリや
#   pyobjc）をここで拾って hiddenimports に足す（拾い忘れると、配布版でだけその機能が黙って止まる）
import ast
import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))

from core.sibling import BUNDLE_PARTS, find_sibling  # noqa: E402
from core.i18n import SUPPORTED  # noqa: E402
from core.version import BUNDLE_NAME, VERSION  # noqa: E402
from integration.sforzando_load import SCRIPTS  # noqa: E402
from tools.build_release import CLEAN, OWN_PACKAGES, clean_source  # noqa: E402

# このプロジェクトと借り先の中の名前（hiddenimports には入れない）
LOCAL_TOPS = {"core", "ui", "integration", "tools", "ptcore", "audio", "app", "tests",
              "audiofile", "dsp", "keydetect", "library", "prep", "splicename"}


def imports_of(path: Path) -> set:
    """ファイルが import する名前（関数の中のものも）。相対 import は除く。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name.split(".")[0]) is not None
    except (ImportError, ValueError):
        return False


def write_clean(path: Path, out: Path) -> None:
    """コメントと説明文を除いた写しを書く。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(clean_source(path.read_text(encoding="utf-8")), encoding="utf-8")


# AppleScript の道具。読み込ませる道具が使うものと、割り当て先を読むもの
datas = [(str(ROOT / "tools" / name), "tools") for name in SCRIPTS]
# 日本語と英語の名前・許可の説明（Contents/Resources/*.lproj。Mac の言語で Finder の名前が変わる）
datas += [(str(ROOT / "resources" / f"{lang}.lproj" / "InfoPlist.strings"), f"{lang}.lproj")
          for lang in SUPPORTED]
loose = []
for project, patterns in BUNDLE_PARTS.items():
    base = find_sibling(project)
    if base is None:
        raise SystemExit(f"借り先が見つかりません: {project}")
    for pattern in patterns:
        found = sorted(base.glob(pattern))
        if not found:
            raise SystemExit(f"借りる部品が見つかりません: {project}/{pattern}")
        for path in found:
            rel = Path(project) / path.relative_to(base)
            write_clean(path, CLEAN / "siblings" / rel)
            datas.append((str(CLEAN / "siblings" / rel), str(Path("siblings") / rel.parent)))
            loose.append(path)

# 試聴の just_playback の _ma_playback（cffi で作った拡張）は、読み込まれるときに C の側から _cffi_backend を
# import する。PyInstaller には見えないので足す（無いと配布版でだけ試聴が使えない）
hidden = {"_cffi_backend"}
for path in loose:
    for name in imports_of(path):
        if name.split(".")[0] in LOCAL_TOPS or not importable(name):
            continue        # 自分たちの部品と、ほかの OS でだけ使う名前（accessible_output2 など）
        hidden.add(name)

# 自分たちのコードも、**説明文とコメントを除いた写し**から組み立てる。
# コンパイルしたコード（.app の中の PYZ）にも説明文は文字列として残り、取り出せば読めるため
SRC = CLEAN / "src"
for path in [ROOT / "app.py"] + [p for d in OWN_PACKAGES for p in sorted((ROOT / d).glob("*.py"))]:
    write_clean(path, SRC / path.relative_to(ROOT))

a = Analysis(
    [str(SRC / "app.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    # 関数の中で遅れて import するもの（integration.sforzando_load など）を取りこぼさないよう、丸ごと入れる
    hiddenimports=sorted(hidden) + collect_submodules("core") + collect_submodules("ui")
    + collect_submodules("integration"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "numpy", "PyInstaller", "pytest", "IPython", "setuptools", "pkg_resources"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SFZBuilder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SFZBuilder",
)
app = BUNDLE(
    coll,
    name=f"{BUNDLE_NAME}.app",
    icon=None,
    bundle_identifier="local.takahashi.sfzbuilder",
    version=VERSION,
    info_plist={
        # **Finder は、この表示名が .app の本当の名前と同じときだけ訳を使う**（Apple の仕様）
        "CFBundleName": BUNDLE_NAME,
        "CFBundleDisplayName": BUNDLE_NAME,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": list(SUPPORTED),
        "LSHasLocalizedDisplayName": True,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "15.0",
        "LSArchitecturePriority": ["arm64"],
        "LSRequiresNativeExecution": True,
        # バージョン情報で読み上げる（tools/build_release.py が環境変数で渡す。ui/main_frame._version_text）
        "SFZBuildDate": os.environ.get("SFZ_BUILD_DATE", ""),
        "SFZGitCommit": os.environ.get("SFZ_GIT_COMMIT", ""),
        # 許可の説明の既定は英語。日本語は resources/ja.lproj/InfoPlist.strings にある
        "NSAccessibilityUsageDescription": (
            "Used to read the Pro Tools plugin windows and to press the sforzando window, "
            "which VoiceOver cannot reach, so that a definition file can be loaded."),
        "NSAppleEventsUsageDescription": (
            "Controls System Events to read which plugin windows are open in Pro Tools "
            "and to load a definition file into sforzando."),
        "NSDesktopFolderUsageDescription": "Used to assign samples placed on the Desktop.",
        "NSDocumentsFolderUsageDescription": "Used to assign samples in the Documents folder.",
        "NSDownloadsFolderUsageDescription": "Used to assign downloaded samples.",
        "NSRemovableVolumesUsageDescription": "Used to assign samples on external drives, such as your Splice folder.",
        "NSNetworkVolumesUsageDescription": "Used to assign samples in network folders.",
    },
)
