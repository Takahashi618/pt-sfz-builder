"""キー操作の一覧（コマンド+シフト+K）。**1 項目ずつたどれる一覧にする。**

以前は全文をまとめて能動読み上げしていた。項目が多く途中から聞き直せず、
メニューから開いたときはメニューの読み上げとぶつかって切れることもある
（作者の別のアプリが実機で確かめ、一覧の画面にした。同じ形にそろえる）。

上下矢印で「検索結果一覧でスペース、試聴を再生または停止する」のように
1 行ずつ読める。**エスケープとリターンで閉じる。**

**`KEY_HELP` はメニューの割り当てと対で保つ。** 片方だけ直すと、説明と
実際がずれる（利用者は説明を信じて操作するので実害が大きい）。
`tests/test_gui_smoke.py` がメニューのキーと突き合わせ、
マニュアルのキーの表もここから作る（`tools/doc_parts.py`）。
"""

from __future__ import annotations

import wx

from core.i18n import APP_NAME, tr
from ui.borrowed import handle_dialog_enter_escape, label_control

__all__ = ["KEY_HELP", "describe_key", "key_rows", "KeysDialog"]

_ANYWHERE = tr("全体", "Anywhere")
_RESULTS = tr("検索結果一覧", "Result list")
_SETTINGS = tr("割り当ての設定", "Assign Settings")
_RETURN = tr("リターン", "Return")
_RUN_SEARCH = tr("検索を実行する", "Run the search")

# (場所, キー, 動作)。読み上げるので記号ではなく言葉で書く
# （キーは「コマンド+S」の形。VoiceOver は「+」を「プラス」と読む）
KEY_HELP: list[tuple[str, str, str]] = [
    (tr("検索語の欄", "Search word field"), _RETURN, _RUN_SEARCH),
    (tr("BPM の欄", "BPM field"), _RETURN, _RUN_SEARCH),
    (_RESULTS, tr("上下矢印", "Up and Down arrows"), tr("素材を移動する", "Move between samples")),
    (_RESULTS, tr("文字キー", "Letter keys"), tr(
        "その頭文字の素材へ移動する",
        "Move to the sample starting with that letter",
    )),
    (_RESULTS, tr("スペース", "Space"), tr("試聴を再生または停止する", "Play or stop the preview")),
    (_RESULTS, _RETURN, tr("選んでいる素材を割り当てる", "Assign the selected sample")),
    (tr("ボタン", "Buttons"), _RETURN, tr(
        "そのボタンを押す。スペースでも押せる",
        "Press the button. Space also works",
    )),
    (_ANYWHERE, tr("タブ", "Tab"), tr(
        "次の欄へ移動する。シフト+タブで前の欄へ戻る",
        "Move to the next field. Shift-Tab moves back",
    )),
    (_ANYWHERE, tr("コマンド+S", "Command-S"), tr(
        "割り当ての設定を開く。配置・テンポ・ルートキー・音作りを決める",
        "Open Assign Settings: mapping, tempo, root key and tone",
    )),
    (_ANYWHERE, tr("コマンド+T", "Command-T"), tr(
        "割り当て先を調べ直す。前に出ている sforzando の画面を見る",
        "Check the assignment target again by looking at the sforzando window in front",
    )),
    (_ANYWHERE, tr("コマンド+R", "Command-R"), tr(
        "Splice の索引を更新する。買い足した素材を検索できるようにする",
        "Update the Splice index so that new samples can be found",
    )),
    (_ANYWHERE, tr("コマンド+C", "Command-C"), tr(
        "選んでいる素材のパスをコピーする。文字入力欄では、選んだ文字のコピーになる",
        "Copy the path of the selected sample. In a text field, copies the selected text",
    )),
    (_ANYWHERE, tr("コマンド+I", "Command-I"), tr(
        "検索結果一覧へ移動する",
        "Move to the result list",
    )),
    (_ANYWHERE, tr("コマンド+シフト+G", "Command-Shift-G"), tr(
        "パックの並び順を順送りする。中身の多い順、名前順、更新の新しい順、追加した順",
        "Change the pack order: most samples first, by name, recently updated first, order added",
    )),
    (_ANYWHERE, tr("コマンド+シフト+L", "Command-Shift-L"), tr(
        "スロットの一覧を読み上げる",
        "Read the list of slots",
    )),
    (_ANYWHERE, tr("コマンド+シフト+K", "Command-Shift-K"), tr(
        "このキー操作の一覧を開く",
        "Open this list of keyboard commands",
    )),
    (_ANYWHERE, tr("コマンド+Q", "Command-Q"), tr(f"{APP_NAME}を終了する", f"Quit {APP_NAME}")),
    (_SETTINGS, _RETURN, tr(
        "決定して閉じる。ボタンの上では、そのボタンを押す",
        "Confirm and close. On a button, presses that button",
    )),
    (_SETTINGS, tr(
        "エスケープかコマンド+W",
        "Escape or Command-W",
    ), tr(
        "何も変えずに閉じる",
        "Close without changing anything",
    )),
    (tr("キー操作の一覧", "Keyboard Commands"), tr(
        "エスケープかリターン",
        "Escape or Return",
    ), tr("閉じる", "Close")),
]


def describe_key(place: str, key: str, action: str) -> str:
    """1 行分の読み上げ文言。

    「どこで」「何を押すと」「どうなる」の順にする。場所が先にあると、
    いま自分がいる場所と照らし合わせながら聞ける（作者の別のアプリと同じ）。
    """
    return tr(f"{place}で{key}、{action}", f"{place}: {key}. {action}")


def key_rows() -> list[str]:
    """一覧に並べる行。"""
    return [describe_key(*row) for row in KEY_HELP]


class KeysDialog(wx.Dialog):
    """キー操作を 1 項目ずつたどれる一覧。"""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title=tr("キー操作の一覧", "Keyboard Commands"))
        outer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            self, label=tr(
                "上下矢印で 1 つずつ確認できます。エスケープキーで閉じます。",
                "Use the Up and Down arrows to check them one by one. Press Escape to close.",
            )
        )
        intro.SetName(tr("説明", "Description"))
        outer.Add(intro, 0, wx.ALL, 8)

        self._list = wx.ListBox(self, style=wx.LB_SINGLE, choices=key_rows())
        label_control(self._list, tr(
            "キー操作の一覧。上下矢印で 1 つずつ読み上げます",
            "Keyboard commands. The Up and Down arrows read them one by one",
        ))
        outer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        if self._list.GetCount():
            self._list.SetSelection(0)

        close = wx.Button(self, wx.ID_CLOSE, label=tr("閉じる", "Close"))
        label_control(close, tr("閉じる", "Close"))
        outer.Add(close, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

        self.SetSizerAndFit(outer)
        self.SetMinSize((560, 420))
        # **エスケープとリターンで閉じる。** 閉じるボタンだけの画面では、
        # 既定のエスケープが効かないことがある。
        self.SetEscapeId(wx.ID_CLOSE)
        self.SetAffirmativeId(wx.ID_CLOSE)
        self.Bind(wx.EVT_BUTTON, self._on_close, id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        # **一覧にフォーカスを置いて開く。** 開いた直後から矢印でたどれるように
        self._list.SetFocus()

    def _on_close(self, _evt) -> None:
        self.EndModal(wx.ID_CLOSE)

    def _on_char_hook(self, evt: wx.KeyEvent) -> None:
        if handle_dialog_enter_escape(self, evt):
            return
        if evt.GetModifiers() == wx.MOD_NONE and evt.GetKeyCode() in (
            wx.WXK_RETURN,
            wx.WXK_NUMPAD_ENTER,
            wx.WXK_ESCAPE,
        ):
            # 借り物が無いときの控え（借りられれば上で処理済み）
            self.EndModal(wx.ID_CLOSE)
            return
        evt.Skip()
