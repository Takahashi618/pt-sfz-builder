"""作者の別のプロジェクトの部品を借りる（探し方は `core/sibling.py`）。**コピーしない。**

借り先 `speech_and_preview` には、実機で詰めた読み上げの部品がある。

| 借りるもの | 何をするか |
| --- | --- |
| `ax_label.label_control` | macOS で読み上げ名を確実に付ける（`SetName` は入力欄に効かない） |
| `announce.announce` | 画面を見ない利用者へ能動的に読み上げる |
| `audio/player.PreviewPlayer` | 試聴。**スペース 1 つで再生と停止**を切り替える |
| `sounds.play` | 操作の結果を短い音で知らせる（成功・失敗・開始） |
| `wx_keys.press_button` | ボタンを Enter でも押せるようにする |

**同じ操作感にすることに意味がある。** 作者の別のアプリと使い分けるので、
試聴のキーが揃っていないと持ち替えるたびに迷う。

**`sys.path` に足す方式は使えない。** あちらのパッケージ名が `ui` で、
本プロジェクトの `ui/` と衝突する。そこで**ファイルの場所を指定して
読み込む**（`importlib`）。一本道で、名前の衝突も起きない。

`core/rootkey.py` が `splicename` を借りているのと同じ考え方で、
**見つからなくても落ちない。** 読み上げ名が付かないだけで、
アプリは起動する。Windows でも同じ（あちらは `SetName` が効く）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from core.i18n import tr
from core.sibling import find_sibling

__all__ = [
    "label_control",
    "announce",
    "announce_enabled",
    "make_player",
    "play_sound",
    "play_sound_for",
    "press_button",
    "handle_dialog_enter_escape",
    "borrowed_from",
    "missing_borrowed",
]


def _find_parts() -> Path | None:
    """部品の場所を探す。**探し方は `core/sibling.py` に集めてある。**"""
    return find_sibling("speech_and_preview", "ui/ax_label.py")


def _load(name: str, subdir: str = "ui") -> ModuleType | None:
    """ファイルの場所を指定して読み込む。**sys.path を汚さない。**"""
    base = _find_parts()
    if base is None:
        return None
    path = base / subdir / f"{name}.py"
    if not path.is_file():
        return None
    # 借り物と分かる名前にする。あちらの `ui.ax_label` とは別物として載せる。
    spec = importlib.util.spec_from_file_location(f"_borrowed_{name}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        # 借り物が壊れていてもアプリは起動させる
        sys.modules.pop(spec.name, None)
        return None
    return module


_ax_label = _load("ax_label")
_announce = _load("announce")
_player = _load("player", "audio")
_sounds = _load("sounds")
_wx_keys = _load("wx_keys")

# 借りているものの一覧（診断用）。**ビルドの工程 1 がここを見る。**
_BORROWED: dict[str, ModuleType | None] = {
    tr("ax_label（読み上げ名）", "ax_label (spoken names)"): _ax_label,
    tr("announce（能動読み上げ）", "announce (active speech)"): _announce,
    tr("player（試聴）", "player (preview)"): _player,
    tr("sounds（効果音）", "sounds (notification sounds)"): _sounds,
    tr("wx_keys（Enter でボタンを押す）", "wx_keys (Return presses buttons)"): _wx_keys,
}


def borrowed_from() -> str | None:
    """借りてきた場所。借りられなければ None。診断用。"""
    base = _find_parts()
    return str(base) if base and _ax_label is not None else None


def missing_borrowed() -> list[str]:
    """借りられなかった部品の名前。**全部借りられていれば空。**

    **この利用者にとって読み上げは必須。** 部品が欠けたまま
    「ビルド成功」と言うと、起動はするのに何も読み上げないアプリが
    最新版として残る。ビルドの工程 1 がここを見て止める。
    """
    return [name for name, module in _BORROWED.items() if module is None]


def make_player():
    """試聴プレイヤーを作る。**借りられなければ None。**

    音が出せなくても割り当てはできるので、無いなら無いで進める。
    呼び出し側は None を受けたら「試聴は使えません」と伝えるだけでよい。
    """
    if _player is None:
        return None
    try:
        return _player.PreviewPlayer()
    except Exception:
        return None


def label_control(ctrl, label: str) -> None:
    """読み上げ名を付ける。**借りられなければ wx の標準だけで済ませる。**"""
    if _ax_label is not None:
        _ax_label.label_control(ctrl, label)
        return
    try:
        ctrl.SetName(label)
    except Exception:
        pass


def announce(message: str) -> None:
    """能動的に読み上げる。**借りられなければ何もしない。**

    黙って何もしないのは、読み上げが無くても画面の文字は出ているため。
    ここで例外を投げると、伝えたい内容そのものが失われる。
    """
    if not message:
        return
    if _announce is not None:
        _announce.announce(message)


def announce_enabled() -> bool:
    """能動読み上げが止められていないか。**テストとビルドでは止めてある。**

    止める環境変数は借り先の決まり（`SM_NO_ANNOUNCE`）。止めてあるときは、
    読み上げのためだけにアプリを前に出すこと（`main_frame._announce_in_front`）もしない
    （テストの最中に利用者の作業中のアプリからフォーカスを奪わないため）。
    """
    import os

    name = getattr(_announce, "_ENV_NO_ANNOUNCE", "SM_NO_ANNOUNCE")
    return os.environ.get(name, "") in ("", "0")


def play_sound(kind: str) -> None:
    """短い通知音を鳴らす（`success` / `failure` / `start`）。

    **読み上げより先に鳴らす。** 音が読み上げに重なると聞き取りにくい。
    借りられなければ何もしない。
    """
    if _sounds is None:
        return
    try:
        _sounds.play(kind)
    except Exception:
        pass


def play_sound_for(message: str) -> None:
    """読み上げ文言から成否を判断して鳴らす。

    文言は `[警告]` / `[エラー]` で始まる規約になっている
    （`core/assign.py`）。借り先と同じ規約なので、
    判断もそのまま借りられる。
    """
    if _sounds is None:
        return
    try:
        _sounds.play_for_message(message)
    except Exception:
        pass


def press_button(button) -> None:
    """ボタンをキー操作から押したことにする。

    **macOS の wx では、既定ボタン以外は Enter で押せない**（スペースのみ）。
    VoiceOver で辿ってきて押せないと戸惑うので、クリックに変換する。
    """
    if _wx_keys is not None:
        try:
            _wx_keys.press_button(button)
            return
        except Exception:
            pass
    # 借りられなければ自前で組み立てる
    import wx

    click = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    click.SetEventObject(button)
    button.GetEventHandler().ProcessEvent(click)


def handle_dialog_enter_escape(dialog, evt) -> bool:
    """ダイアログ共通の Enter / Escape 処理。処理したら True。"""
    if _wx_keys is None:
        return False
    try:
        return bool(_wx_keys.handle_dialog_enter_escape(dialog, evt))
    except Exception:
        return False
