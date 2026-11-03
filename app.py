"""エントリポイント。

    python3.14 app.py                     普通に起動する（ソースから。手元の版）
    python3.14 app.py --selftest          窓を出さずに組み立て、部品がそろっているかを 1 行の JSON で言う
    python3.14 app.py --sforzando-load …  sforzando に読み込ませる道具（アプリが別のプロセスで呼ぶ）

このファイルのある場所が自動で `sys.path` に入るので、
どのカレントディレクトリからでも起動できる。

### macOS でアプリ名を出す

`python app.py` で起動すると、macOS はアプリ名を「Python」と表示する。
実行しているのが Python.app 本体だから。**`wx.App` を作る前に**
NSBundle の情報辞書を書き換えると、アプリメニューの表示名が変わる。

wx が作るアプリメニューは「Quit …」のように英語のまま残るので、
NSMenu の項目名も直接書き換える（**読み上げに英語が混ざると分かりにくい**）。

作者の別のアプリで確立した手順をそのまま踏襲している。

### 配布版（PyInstaller で固めた .app。2026-10-25 から）

手元の版はランチャ（`PT SFZビルダー.app` の中のシェルスクリプト）がログの行き先と
`.app` の場所を決めるが、配布版にはランチャが無いので、ここで同じことをする
（`_frozen_setup`）。**.app の中に `__pycache__` を書かない**（同梱した借り物の .py を
読むと書こうとし、署名が壊れて Finder から開いても無反応になる。
作者の別のアプリで踏んだ）。

`--sforzando-load` は**どちらの版でも**アプリが自分を別のプロセスとして起こす
入口（`ui/controller.loader_command`）。配布版の実行ファイルは python ではないので、
`.py` の道具をそのまま渡せない。
"""

from __future__ import annotations

import sys
from pathlib import Path

from core.i18n import APP_NAME, is_english, tr

# PyInstaller で固めた配布版として動いているか（`core/sibling.FROZEN` と同じ）
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    sys.dont_write_bytecode = True


# ログの行き先。手元の版のランチャと同じ場所
LOG_PATH = Path.home() / "Library" / "Logs" / "SfzBuilder.log"

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _bundle_root() -> Path:
    """配布版の .app の場所（…/PT SFZビルダー.app）。実行ファイルは `Contents/MacOS/` にある。"""
    return Path(sys.executable).resolve().parents[2]


def _frozen_setup(log: bool = True) -> None:
    """配布版だけ。手元の版でランチャがしていることをここでする。

    - バージョン情報が読む Info.plist の場所を教える（`SFZBUILDER_APP`）
    - 標準出力とエラーをログへ（Finder から開くと見えないため）
    """
    import os
    import time

    os.environ.setdefault("SFZBUILDER_APP", str(_bundle_root()))
    if not log:
        return
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        stream = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stderr = stream
    from core.version import VERSION

    print(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} started (packaged version {VERSION})", flush=True)


def _set_app_name(name: str) -> None:
    """メニューバーに出るアプリ名を変える。**`wx.App` より先に呼ぶ。**

    失敗しても起動は止めない（名前が「Python」のままになるだけ）。
    """
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle
    except ImportError:
        return
    try:
        bundle = NSBundle.mainBundle()
        if bundle is None:
            return
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = name
            info["CFBundleDisplayName"] = name
    except Exception:
        pass


def _localize_app_menu(name: str) -> None:
    """アプリメニューの項目名を日本語にする。**窓を出したあとに呼ぶ。**

    英語ではそのままでよい（wx が作る英語の項目を使う）。
    """
    if sys.platform != "darwin" or is_english():
        return
    try:
        from AppKit import NSApp
    except ImportError:
        return
    try:
        main_menu = NSApp().mainMenu()
        if main_menu is None or main_menu.numberOfItems() == 0:
            return
        app_menu = main_menu.itemAtIndex_(0).submenu()
        if app_menu is None:
            return
        # 前方一致で置き換える。項目の並びは macOS の版で変わり得る
        rules = (
            ("Quit", f"{name}を終了"),
            ("Hide Others", "ほかを隠す"),
            ("Hide", f"{name}を隠す"),
            ("Show All", "すべてを表示"),
            ("Services", "サービス"),
            ("About", f"{name}について"),
            ("Preferences", "設定…"),
        )
        _retitle_items(app_menu, rules)
        _localize_window_menu(main_menu)
    except Exception:
        pass


def _retitle_items(menu, rules) -> None:
    """メニューの項目名を、前方一致の規則で置き換える。"""
    for i in range(menu.numberOfItems()):
        item = menu.itemAtIndex_(i)
        title = str(item.title() or "")
        for prefix, replacement in rules:
            if title.startswith(prefix):
                item.setTitle_(replacement)
                break


# wx が macOS で自動で足す「Window」メニューの訳（macOS の標準の言い方）
WINDOW_MENU_TITLE = "ウインドウ"
WINDOW_MENU_RULES = (
    ("Minimize", "しまう"),
    ("Zoom", "拡大／縮小"),
    ("Bring All to Front", "すべてを手前に移動"),
)


def _localize_window_menu(main_menu) -> None:
    """wx が足す「Window」メニューを日本語にする。

    wx には日本語の訳語が無く、**このメニューだけ英語のまま残っていた**
    （起動した配布版のメニューバーを System Events で調べて分かった）。
    読み上げに英語が混ざらないよう、アプリメニューと同じく書き換える。
    """
    for i in range(main_menu.numberOfItems()):
        item = main_menu.itemAtIndex_(i)
        sub = item.submenu()
        if sub is None or "Window" not in (str(item.title() or ""), str(sub.title() or "")):
            continue
        item.setTitle_(WINDOW_MENU_TITLE)
        sub.setTitle_(WINDOW_MENU_TITLE)
        _retitle_items(sub, WINDOW_MENU_RULES)
        return


class _EmptyLibrary:
    """`--selftest` 用の空の索引。**利用者の索引に触らない。**"""

    entries: list = []

    def search(self, **_kwargs):
        return []

    def keys(self):
        return []


def selftest() -> int:
    """`--selftest`: 窓を出さずに組み立てて、部品がそろっているかを確かめる。

    **音も読み上げも出さず、Pro Tools にも System Events にも触らない。**
    配布版を作るとき（`tools/build_release.py`）に、組み上げた .app の中の
    実行ファイルで動かす。関数の中で遅れて読む部品（試聴・伸縮・借り物）は、
    配布版で取りこぼすとその機能だけが黙って止まるので、ここで読めるかを確かめる。
    新しく組んだ .app が System Events を操作すると、作っている Mac に
    許可を求める画面が出てしまうので、AppleScript は動かさない。

    結果は 1 行の JSON。そろっていれば終了コード 0。
    """
    import json
    import os
    import shutil
    import subprocess
    import tempfile

    os.environ["SM_SILENT"] = "1"
    os.environ["SM_NO_ANNOUNCE"] = "1"
    if FROZEN:
        _frozen_setup(log=False)

    problems: list[str] = []
    for name in (
        "wx",
        "objc",
        "Foundation",
        "AppKit",
        "Quartz",
        "ApplicationServices",
        "just_playback",
    ):
        try:
            __import__(name)
        except Exception as exc:
            problems.append(tr(
                f"{name}（{type(exc).__name__}: {str(exc)[:120]}）",
                f"{name} ({type(exc).__name__}: {str(exc)[:120]})",
            ))

    from core.sibling import load_ptcore
    from core.version import VERSION
    from integration.render import backend_name
    from ui.borrowed import missing_borrowed

    problems += [tr(
        f"借りている部品 {name}",
        f"the borrowed part {name}",
    ) for name in missing_borrowed()]
    for name in ("splicename", "keydetect", "library", "dsp", "audiofile"):
        if load_ptcore(name) is None:
            problems.append(tr(f"借りている部品 ptcore/{name}", f"the borrowed part ptcore/{name}"))

    # 読み込ませる道具が、別のプロセスとして起こせるか（配布版でだけ壊れる道を見張る）
    from ui.controller import AppController, loader_base_command, tool_message

    loader = ""
    try:
        done = subprocess.run(
            loader_base_command() + ["--check"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        loader = tool_message(done.stdout or "")
        if done.returncode != 0 or not loader:
            problems.append(tr(
                f"読み込ませる道具（{loader or (done.stderr or '').strip()[-200:]}）",
                f"the loading tool ({loader or (done.stderr or '').strip()[-200:]})",
            ))
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(tr(
            f"読み込ませる道具を起こせない（{exc}）",
            f"cannot start the loading tool ({exc})",
        ))

    import wx

    from core.slots import SlotLayout
    from ui.main_frame import MainFrame

    # 既定の置き場所を通す（読むだけ。書かない）。**配布版で .app の中を指していないか。**
    defaults = AppController(target_reader=lambda: (None, tr("調べていません", "Not checked"), ""))
    slots_dir = defaults.layout.slots_dir
    index = defaults._open_library()
    index_path = getattr(index, "index_path", "") if index is not None else ""
    if FROZEN:
        inside = str(_bundle_root())
        for label, path in ((tr(
            "スロットの置き場所",
            "the slot folder",
        ), slots_dir), (tr("索引", "the index"), index_path)):
            if not path or str(Path(path).resolve()).startswith(inside):
                problems.append(tr(
                    f"{label}が .app の中か、決まっていない（{path}）",
                    f"{label} is inside the .app or not decided ({path})",
                ))

    workdir = Path(tempfile.mkdtemp(prefix="sfz_selftest_"))
    try:
        app = wx.App(False)
        frame = MainFrame(
            AppController(
                layout=SlotLayout(slots_dir=str(workdir)),
                library=_EmptyLibrary(),
                target_reader=lambda: (None, tr("調べていません", "Not checked"), ""),
            )
        )
        if frame.GetMenuBar() is None:
            problems.append(tr("メニュー", "the menu"))
        frame.Destroy()
        del app
    except Exception as exc:
        problems.append(tr(
            f"窓の組み立て（{type(exc).__name__}: {exc}）",
            f"building the window ({type(exc).__name__}: {exc})",
        ))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(
        json.dumps(
            {
                "ok": not problems,
                "problems": problems,
                "version": VERSION,
                "frozen": FROZEN,
                "python": sys.version.split()[0],
                # 伸縮の道具は利用者が入れるもの。無くても失敗にはしない（報告だけ）
                "render_backend": backend_name() or tr("なし", "none"),
                "slots_dir": slots_dir,
                "splice_index": index_path or tr(
                    "借りている部品と共有",
                    "shared with the borrowed part",
                ),
                "loader": loader,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if not problems else 1


def _run_loader(args: list[str]) -> int:
    """`--sforzando-load`: 読み込ませる道具（`integration/sforzando_load.py`）。"""
    from integration.sforzando_load import main as load_main

    return load_main(["sforzando_load", *args])


# 起動の確認（配布物を作るとき）。**ふつうの起動と同じ道を通し、窓は出さずに数秒で終わる。**
# `--selftest` は窓を組み立てるだけで、ログ・アプリ名・メニューの日本語化・
# イベントの流れを通らない（作者の別のアプリと同じ考え方）。
SMOKE_ENV = "SFZBUILDER_SMOKE"
SMOKE_DONE = "Startup check finished"


def main(argv: list[str] | None = None) -> int:
    import os

    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--sforzando-load"]:
        return _run_loader(args[1:])
    if args[:1] == ["--selftest"]:
        return selftest()
    smoke = os.environ.get(SMOKE_ENV, "") not in ("", "0")
    if FROZEN:
        _frozen_setup()

    import wx

    # wx.App より先に。メニューバーのアプリ名に効く
    _set_app_name(APP_NAME)

    from ui.controller import AppController
    from ui.main_frame import MainFrame

    if smoke:
        # **Pro Tools にも System Events にも触らない。** 新しく組んだ .app が
        # System Events を操作すると、作っている Mac に許可を求める画面が出る。
        controller = AppController(target_reader=lambda: (None, tr(
            "起動の確認なので調べていません",
            "Not checked during the startup check",
        ), ""))
    else:
        controller = AppController()

    app = wx.App(False)
    app.SetAppName(APP_NAME)
    app.SetAppDisplayName(APP_NAME)
    try:
        app.locale = wx.Locale(wx.LANGUAGE_ENGLISH if is_english() else wx.LANGUAGE_JAPANESE)
    except Exception:
        pass

    frame = MainFrame(controller)
    if smoke:
        wx.CallLater(1500, frame.Close)
    else:
        frame.Show()
    _localize_app_menu(APP_NAME)
    app.MainLoop()
    if smoke:
        print(SMOKE_DONE, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
