"""sforzando にスロットの `.sfz` を読ませる（最初の 1 回だけ要る操作）。

    python3.14 app.py --sforzando-load import <.sfz のパス> --track Inst1
    python3.14 app.py --sforzando-load reload --track Inst1
    python3.14 app.py --sforzando-load empty --track Inst1
    python3.14 app.py --sforzando-load --dry-run import <.sfz のパス>
    python3.14 app.py --sforzando-load --check

`tools/sforzando_load.py` からも同じものを動かせる（手で試すとき）。
アプリは `ui/controller._default_plugin_loader` から別のプロセスで呼ぶ。
**本体をここ（integration/）に置くのは、配布版でも同じ入口で動かすため**
（配布版の .app は、`.py` の道具をそのまま動かせない）。

**一度読ませれば、あとは書き換えるだけでよい。** sforzando は読み込んだ
`.sfz` の置き場所を監視していて、自動で読み直す（2026-09-04 実機確認）。
`reload` は監視が効かない場面の逃げ道として残してある。

### なぜ座標クリックなのか

sforzando の画面は AX にも VoiceOver にも出ない。**利用者が手で読み込む
こともできない。** そこを肩代わりするのがこの道具。押すのは 2 点だけで、

  1. ファイル名欄（座標は定義 XML 由来。`core/sforzando_gui.py`）
  2. 出たメニューの `import` / `reload` / `empty`（こちらは実測値）

`import` を押すと **macOS 標準の「Please select file」** が開く。
そこから先は Cmd+Shift+G でパスを直接入力でき、**VoiceOver で完結する。**

### 押す前にエラーダイアログを畳む（**省略すると黙って効かなくなる**）

サンプルが見つからないと sforzando はモーダルのエラーを出す。
**これが出ている間、プラグインへのクリックは全部素通りする。**
しかもフォルダの監視は効き続けるので、「読み込みは動いているのに
操作だけ効かない」という分かりにくい状態になる（2026-09-04 に踏んだ）。
そのため**毎回、押す前に畳む。**

### 割り当てたトラックの画面だけを押す（2026-10-25 のレビューで直した）

`--track` を渡すと、そのトラックの sforzando の画面を探し、**その画面を
前に出し、いちばん前に出たことを確かめてから押す。** 見つからなければ押さない。

以前は「いちばん前の sforzando の画面」を押していた。割り当てたあとに
別のトラックの画面を開くと、そちらに読み込ませてしまう（2 つのトラックが
同じ音を鳴らし、台帳とも食い違う）。前に出す側も「最初に見つかった
プラグインの画面」だったので、別のプラグインの画面が前にあると、
同じ位置に重なったその画面を押していた。

### sforzando の版を確かめてから押す

押す位置は sforzando の画面の定義（gui.xml）から出している。**定義が前提と
違えば押さない**（`core/sforzando_gui.definition_problems`）。配布版は、
ほかの人の Mac の、違う版の sforzando で動くことがある。

### 安全のために

- 押す点が窓の中に入っているか、撃つ前に確かめる（`integration/mouse`）
- 描画領域の位置は AX の値を検証してから使う（窓の外を返すことがある）
- 文字入力はクリップボード経由。**利用者のクリップボードは元に戻す**
- **アクセシビリティの許可が無ければ押さない。** 合成マウスは許可が無いと
  黙って何もしない（`integration/permissions.py`）

### 結果の伝え方

最後の行に `MESSAGE<TAB>読み上げる一文` を出す（`ui/controller.tool_message`）。
終了コードは 0 成功 / 1 失敗 / 2 使い方の誤り。
"""

from __future__ import annotations

from core.i18n import COMMA, tr

import time
from pathlib import Path
from typing import Sequence

from core.geometry import Rect
from core.sforzando_gui import (
    SOURCE_XML,
    center_of,
    definition_problems,
    file_menu_item_point,
)
from core.sibling import PROJECT_ROOT

from . import mouse
from .axread import AxWindow, make_reader, read_plugin_windows
from .permissions import is_trusted
from .reloader import OsascriptRunner, explain_error, permission_hint

__all__ = [
    "ACTIONS",
    "SCRIPTS",
    "choose_window",
    "is_front",
    "click_points",
    "gui_problems",
    "main",
]

ACTIONS = ("import", "reload", "empty")

MENU_WAIT_SEC = 1.0
DIALOG_WAIT_SEC = 1.8
RAISE_WAIT_SEC = 0.4

DISMISS_SCRIPT = "dismiss_sforzando_error.applescript"
RAISE_SCRIPT = "raise_sforzando_window.applescript"
# 開くダイアログにパスを入れる手順は `tools/fill_open_dialog.applescript`
# に置いてある。**ここに書き写さない。** 以前は同じ流れが 2 か所にあり、
# 実機で詰めた待ち時間がすでに食い違っていた（0.9/0.6/1.2 と 0.8/0.5/1.0）。
DIALOG_SCRIPT = "fill_open_dialog.applescript"
# この道具が使う AppleScript（配布版に同梱するもの。`--check` が確かめる）
SCRIPTS = (
    "ax_plugin_windows.applescript",
    DISMISS_SCRIPT,
    RAISE_SCRIPT,
    DIALOG_SCRIPT,
)
SCRIPTS_DIR = PROJECT_ROOT / "tools"

USAGE = tr(
    "使い方: --sforzando-load import <.sfz のパス> [--track トラック名]"
    " / reload / empty / --dry-run / --check",
    "Usage: --sforzando-load import <.sfz path> [--track track name] / reload / empty / "
    "--dry-run / --check",
)


def say(message: str) -> None:
    """読み上げる一文を最後の行に出す（アプリが拾う）。"""
    print(f"MESSAGE\t{message}", flush=True)


def _same_track(a: str | None, b: str | None) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _is_sforzando(window: AxWindow) -> bool:
    return "sforzando" in (window.info.plugin_name or "").casefold()


def choose_window(
    windows: Sequence[AxWindow], track: str = ""
) -> tuple[AxWindow | None, str]:
    """押す sforzando の画面を選ぶ。戻り値は (画面, 選べなかった理由)。**純粋関数。**

    `track` が空なら、いちばん前の sforzando の画面（手で試すとき）。
    """
    found = [w for w in windows if _is_sforzando(w)]
    if not found:
        return None, (
            tr(
                "sforzando の画面が開いていません。"
                "Pro Tools で sforzando の画面を開いてから、もう一度押してください。",
                "The sforzando window is not open. Open the sforzando window in Pro Tools and "
                "press again.",
            )
        )
    if not track.strip():
        return found[0], ""
    for window in found:
        if _same_track(window.info.track_name, track):
            return window, ""
    shown = COMMA.join(
        tr(
            f"「{w.info.track_name or '名前の分からないトラック'}」",
            f"“{w.info.track_name or 'a track with an unknown name'}”",
        ) for w in found
    )
    return None, (
        tr(
            f"割り当てたトラック「{track}」の sforzando の画面が開いていません"
            f"（開いているのは {shown}）。"
            f"Pro Tools で「{track}」の sforzando の画面を開いてから、もう一度押してください。",
            f"The sforzando window of the assigned track “{track}” is not open (open: {shown}). "
            f"Open the sforzando window of “{track}” in Pro Tools and press again.",
        )
    )


def is_front(windows: Sequence[AxWindow], chosen: AxWindow) -> bool:
    """前に出したあと、**いちばん前のプラグインの画面が選んだ画面か。** 純粋関数。

    AppleScript はプラグインの画面だけを前から順に返す。位置と大きさまで
    比べるのは、同じトラックに同じプラグインを 2 つ挿したときに取り違えないため。
    """
    if not windows:
        return False
    front = windows[0]
    return (
        _is_sforzando(front)
        and _same_track(front.info.track_name, chosen.info.track_name)
        and (front.x, front.y, front.width, front.height)
        == (chosen.x, chosen.y, chosen.width, chosen.height)
    )


def click_points(
    window: AxWindow, action: str
) -> tuple[tuple[int, int], tuple[int, int], Rect] | str:
    """押す 2 点と、押してよい範囲。決められなければ理由の文。**純粋関数。**"""
    origin = window.content_origin()
    if origin is None or not window.has_rect:
        return tr(
            "sforzando の画面の位置が分かりませんでした。押していません。",
            "The position of the sforzando window is unknown. Nothing was pressed.",
        )
    assert window.x is not None and window.y is not None
    assert window.width is not None and window.height is not None
    allowed = Rect(window.x, window.y, window.width, window.height)
    open_at = center_of("file_menu", origin[0], origin[1])
    item_at = file_menu_item_point(action, *open_at)
    if not (allowed.contains(*open_at) and allowed.contains(*item_at)):
        return tr(
            "押す位置が sforzando の画面の外になりました。押していません。",
            "The position to press is outside the sforzando window. Nothing was pressed.",
        )
    return open_at, item_at, allowed


def gui_problems(path: str = SOURCE_XML) -> list[str]:
    """実物の sforzando の画面の定義が、押す位置の前提と合っているか。"""
    target = Path(path)
    if not target.is_file():
        return [tr(
            f"sforzando の画面の定義が見つかりません（{path}）",
            f"The sforzando window definition was not found ({path})",
        )]
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [tr(
            f"sforzando の画面の定義を読めません（{exc}）",
            f"Cannot read the sforzando window definition ({exc})",
        )]
    return definition_problems(text)


def _check() -> int:
    """`--check`: 押さず、Pro Tools にも触らずに、道具がそろっているかだけ言う。

    配布版を作るときに、組み上げた .app の中から呼ぶ（`app.py --selftest`）。
    **ここで AppleScript を動かさない。** 新しく組んだ .app が System Events を
    操作すると、作っている Mac に許可を求める画面が出てしまう。
    """
    missing = [name for name in SCRIPTS if not (SCRIPTS_DIR / name).is_file()]
    problems = gui_problems()
    print(tr("道具: ", "Tools: ") + (tr(
        "そろっている",
        "all there",
    ) if not missing else tr("足りない ", "missing ") + COMMA.join(missing)))
    print(
        tr("sforzando の画面の定義: ", "sforzando window definition: ")
        + (tr(
            "前提と合っている",
            "matches what is expected",
        ) if not problems else COMMA.join(problems))
    )
    if missing:
        say(tr(
            "読み込ませる道具が足りません: ",
            "The loading tools are incomplete: ",
        ) + COMMA.join(missing))
        return 1
    say(tr("読み込ませる道具はそろっています。", "The loading tools are all there."))
    return 0


def _parse(argv: Sequence[str]) -> tuple[str, str, str, bool] | str:
    """(操作, パス, トラック, 試しか) か、使い方の誤りの文。"""
    args = list(argv)
    dry = "--dry-run" in args
    track = ""
    if "--track" in args:
        index = args.index("--track")
        if index + 1 >= len(args):
            return tr(
                "--track のあとにトラック名を渡してください。",
                "Give a track name after --track.",
            )
        track = args[index + 1]
        del args[index : index + 2]
    words = [a for a in args if not a.startswith("--")]
    if not words or words[0] not in ACTIONS:
        return USAGE
    action = words[0]
    path = words[1] if len(words) > 1 else ""
    if action == "import" and not path:
        return tr("読み込むファイルのパスを渡してください。", "Give the path of the file to load.")
    return action, path, track, dry


def main(argv: Sequence[str]) -> int:
    """`argv[0]` は道具の名前（`sys.argv` と同じ形）。"""
    rest = list(argv[1:])
    if "--check" in rest:
        return _check()
    parsed = _parse(rest)
    if isinstance(parsed, str):
        print(parsed)
        say(parsed)
        return 2
    action, path, track, dry = parsed

    problems = gui_problems()
    if problems:
        print(tr(
            "sforzando の画面の定義が前提と違います: ",
            "The sforzando window definition differs from what is expected: ",
        ) + COMMA.join(problems))
        say(
            tr(
                "sforzando の版が、このアプリで確かめた版と違うようです。"
                "押す位置が合わないので、押していません。",
                "This sforzando version seems to differ from the one this app was checked with. "
                "The position to press would not match, so nothing was pressed.",
            )
        )
        return 1

    reader = make_reader(SCRIPTS_DIR)
    result = read_plugin_windows(reader)
    if not result.ok:
        say(result.describe_ja())
        return 1
    window, why = choose_window(result.windows, track)
    if window is None:
        say(why)
        return 1
    planned = click_points(window, action)
    if isinstance(planned, str):
        say(planned)
        return 1
    open_at, item_at, allowed = planned
    name = window.info.track_name or tr("名前の分からないトラック", "a track with an unknown name")

    print(tr(f"トラック「{name}」の sforzando", f"sforzando on track “{name}”"))
    print(tr(f"  ファイル名欄 : {open_at}", f"  File name field: {open_at}"))
    print(f"  {action:<7}: {item_at}")
    if dry:
        print(tr("--dry-run なので押しません。", "--dry-run, so nothing is pressed."))
        say(tr(
            f"トラック「{name}」の sforzando を押す位置を決めました。押していません。",
            f"Decided where to press in the sforzando window of track “{name}”. Nothing was "
            "pressed.",
        ))
        return 0

    if is_trusted() is False:
        say(permission_hint("-25211"))
        return 1

    runner = OsascriptRunner(SCRIPTS_DIR, timeout=30.0)
    # **押す前にエラーダイアログを畳む。** 出ているとクリックが素通りする。
    dismissed = runner.run(DISMISS_SCRIPT, ()).output
    if dismissed.startswith("DISMISSED"):
        print(tr(
            f"エラーダイアログを畳みました: {dismissed.split(chr(9), 1)[-1]}",
            f"Closed the error dialog: {dismissed.split(chr(9), 1)[-1]}",
        ))

    raised = runner.run(RAISE_SCRIPT, [window.info.track_name or ""] if track else [])
    if not raised.ok or not raised.output.startswith("RAISED"):
        print(tr(
            f"前に出せませんでした: {raised.output or raised.error}",
            f"Could not bring it to the front: {raised.output or raised.error}",
        ))
        say(
            explain_error(raised.error)
            if not raised.ok
            else tr(
                "sforzando の画面を前に出せませんでした。押していません。",
                "Could not bring the sforzando window to the front. Nothing was pressed.",
            )
        )
        return 1
    time.sleep(RAISE_WAIT_SEC)

    # **前に出たことを確かめてから押す。** 重なった別の画面を押さないため。
    again = read_plugin_windows(reader)
    if not again.ok or not is_front(again.windows, window):
        say(
            tr(
                f"トラック「{name}」の sforzando の画面を、いちばん前に出せませんでした。"
                "ほかのプラグインの画面を閉じてから、もう一度押してください。押していません。",
                f"Could not bring the sforzando window of track “{name}” all the way to the "
                "front. Close the other plugin windows and press again. Nothing was pressed.",
            )
        )
        return 1

    first = mouse.click(*open_at, allowed=allowed)
    if not first.ok:
        say(first.message_ja)
        return 1
    time.sleep(MENU_WAIT_SEC)

    second = mouse.click(*item_at, allowed=allowed)
    if not second.ok:
        say(second.message_ja)
        return 1
    time.sleep(DIALOG_WAIT_SEC)

    if action != "import":
        # reload と empty はダイアログを出さない。押して終わり。
        say(tr(
            f"トラック「{name}」の sforzando で {action} を押しました。",
            f"Pressed {action} in the sforzando window of track “{name}”.",
        ))
        return 0

    filled = runner.run(DIALOG_SCRIPT, [path])
    out = (filled.output or filled.error).strip()
    print(out)
    if filled.ok and out.startswith("OK"):
        say(tr(
            f"トラック「{name}」のスフォルツァンドに読み込ませました。",
            f"Loaded into sforzando on track “{name}”.",
        ))
        return 0
    say(
        tr(
            "ファイルを選ぶ画面にパスを入れられませんでした。",
            "Could not enter the path in the file selection window. ",
        )
        + (
            permission_hint(out)
            or tr(
                "sforzando の画面を開き直して、もう一度押してください。",
                "Reopen the sforzando window and press again.",
            )
        )
    )
    return 1
