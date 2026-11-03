"""割り当ての設定ダイアログ（Cmd+S）。

**主画面から設定を追い出す。** 主画面に並べていたときは Tab を 6 回
余分に押さないと実行ボタンへ届かなかった。繰り返し使うのは
「探す → 選ぶ → 割り当てる」で、設定を変えるのは時々でよい。

作者の別のアプリの「セッションの条件」（Cmd+S）と同じ位置付けにしてある。
**どのアプリでも同じキーが同じ意味を持つ**ようにするため。

守っていること:

- 板は `wx.ScrolledWindow`。素の `wx.Panel` だと欄が高さ 0 に潰れる
- 読み上げ名は `label_control` で付ける
- 大きさは中身から決めて、画面の作業領域で頭打ちにする
- **Enter と Escape はボタンの上かどうかで意味を変える**（`wx_keys`）。
  キャンセルの上で Enter を押したのに決定になる、という事故を防ぐ
- **Escape と Cmd+W のどちらでも閉じられること**（作者の別のアプリの規約）
"""

from __future__ import annotations

from dataclasses import replace

import wx

from core.notes import NOTE_NAMES
from core.tone import DEFAULT_PRESET, preset_names
from core.i18n import tr
from ui.borrowed import handle_dialog_enter_escape, label_control, press_button
from ui.controller import AUTO, MODE_LABELS, MODE_ORDER, AssignForm
from ui.layout import display_area

__all__ = ["AssignDialog", "SPANS", "OCTAVES"]

# 「速さを保つ」で用意する範囲。**広いほど待つし、音も荒れる。**
SPANS: list[tuple[str, int]] = [
    (tr("上下6半音。13鍵盤", "6 semitones up and down, 13 keys"), 6),
    (tr("上下1オクターブ。25鍵盤", "1 octave up and down, 25 keys"), 12),
    (tr("上下2オクターブ。49鍵盤", "2 octaves up and down, 49 keys"), 24),
]

OCTAVES = list(range(0, 9))


def _static(parent: wx.Window, text: str) -> wx.StaticText:
    """欄名の文字。**すべてのウィジェットに名前を付ける**（例外なし）。"""
    st = wx.StaticText(parent, label=text)
    st.SetName(text)
    return st


class AssignDialog(wx.Dialog):
    """配置・範囲・テンポ・ルートキー・音作りをまとめて決める。"""

    def __init__(self, parent: wx.Window, form: AssignForm) -> None:
        super().__init__(parent, title=tr("割り当ての設定", "Assign Settings"))
        self._form = form
        self._build(form)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._fit_to_content()

    # -- 画面 -------------------------------------------------------------

    def _build(self, form: AssignForm) -> None:
        panel = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        panel.SetScrollRate(0, 20)
        outer = wx.BoxSizer(wx.VERTICAL)

        self._mode = self._choice(
            panel, outer, tr("配置", "Mapping"), [MODE_LABELS[m] for m in MODE_ORDER]
        )
        self._mode.SetSelection(
            MODE_ORDER.index(form.mode) if form.mode in MODE_ORDER else 0
        )

        self._span = self._choice(
            panel,
            outer,
            tr(
                "速さを保つときの範囲。広いほど待ちます",
                "Range when keeping speed. A wider range takes longer",
            ),
            [name for name, _ in SPANS],
        )
        self._span.SetSelection(
            next(
                (i for i, (_, v) in enumerate(SPANS) if v == form.phrase_span),
                1,
            )
        )

        self._bpm = self._text(
            panel, outer, tr(
                "セッションのテンポ。空欄なら素材のまま",
                "Session tempo. If empty, the sample's own tempo is kept",
            ), form.target_bpm
        )

        # **倍・半分の解釈を切れるようにしてある。** 素材の BPM 表記が
        # 実感と半分ずれていることがあり、既定では読み替えたほうが合う。
        # だが読み替えが意図と逆に働くこともあるので、逃げ道を残す。
        self._half_double = wx.CheckBox(
            panel, label=tr(
                "倍・半分のテンポの解釈を許す",
                "Allow treating a tempo as double or half",
            )
        )
        self._half_double.SetValue(form.allow_half_double)
        label_control(
            self._half_double,
            tr(
                "倍・半分のテンポの解釈を許す。"
                "170 の素材を 85 のセッションでそのまま使えるようにする",
                "Allow treating a tempo as double or half. A 170 sample can then be used as is in "
                "an 85 session",
            ),
        )
        outer.Add(self._half_double, 0, wx.ALL, 4)

        self._root = self._choice(
            panel, outer, tr("ルートキー", "Root key"), [AUTO] + list(NOTE_NAMES)
        )
        self._root.SetSelection(
            0 if form.root_key == AUTO else NOTE_NAMES.index(form.root_key) + 1
        )

        self._octave = self._choice(
            panel, outer, tr("オクターブ", "Octave"), [str(n) for n in OCTAVES]
        )
        self._octave.SetSelection(
            OCTAVES.index(form.octave) if form.octave in OCTAVES else 3
        )

        names = preset_names()
        self._tone = self._choice(panel, outer, tr("音作り", "Tone"), names)
        self._tone.SetSelection(
            names.index(form.tone_preset) if form.tone_preset in names else
            names.index(DEFAULT_PRESET)
        )

        panel.SetSizer(outer)
        panel.FitInside()
        self._inner = outer

        # **`EndModal` は自前で呼ぶ。**
        # `CreateStdDialogButtonSizer` に閉じる仕事を任せない
        # （ダイアログが確実に閉じない）。並び順は macOS の
        # 標準に従いたいので sizer は使うが、**閉じるところは wx の
        # 既定の仕組みに任せない。** 作者の別のアプリと
        # 同じ形にしてある。
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok = self.FindWindow(wx.ID_OK)
        cancel = self.FindWindow(wx.ID_CANCEL)
        if isinstance(ok, wx.Button):
            ok.SetLabel(tr("決定", "OK"))
            label_control(ok, tr("決定", "OK"))
        if isinstance(cancel, wx.Button):
            cancel.SetLabel(tr("取り消し", "Cancel"))
            label_control(cancel, tr("取り消し", "Cancel"))
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        # `wx_keys` が「Enter で押すボタン」を探すのに使う。
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)

        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(panel, 1, wx.EXPAND | wx.ALL, 8)
        frame.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(frame)
        self._frame_sizer = frame

    def _choice(self, parent, sizer, label: str, choices: list[str]) -> wx.Choice:
        sizer.Add(_static(parent, label), 0, wx.LEFT | wx.TOP, 4)
        ctrl = wx.Choice(parent, choices=choices)
        ctrl.SetSelection(0)
        label_control(ctrl, label)
        sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 4)
        return ctrl

    def _text(self, parent, sizer, label: str, value: str) -> wx.TextCtrl:
        sizer.Add(_static(parent, label), 0, wx.LEFT | wx.TOP, 4)
        ctrl = wx.TextCtrl(parent)
        ctrl.SetValue(value)
        label_control(ctrl, label)
        sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 4)
        return ctrl

    def _fit_to_content(self) -> None:
        """**大きさを決め打ちしない。** 文字が大きい環境で欄が潰れる。"""
        need = self._frame_sizer.GetMinSize()
        area = display_area(self)
        self.SetSize(
            (
                min(need.width + 40, area.width),
                min(need.height + 40, int(area.height * 0.92)),
            )
        )

    # -- 閉じる -----------------------------------------------------------

    def _on_ok(self, _evt) -> None:
        """決定。**必ずここを通って閉じる。**"""
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _evt) -> None:
        """取り消し。"""
        self.EndModal(wx.ID_CANCEL)

    # -- キー -------------------------------------------------------------

    def _on_char_hook(self, evt: wx.KeyEvent) -> None:
        """Enter と Escape。**ボタンの上かどうかで意味を変える。**"""
        if handle_dialog_enter_escape(self, evt):
            return
        if evt.GetModifiers() == wx.MOD_NONE:
            key = evt.GetKeyCode()
            focused = wx.Window.FindFocus()
            if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                if isinstance(focused, wx.Button):
                    press_button(focused)
                    return
                ok = self.FindWindow(wx.ID_OK)
                if isinstance(ok, wx.Button):
                    press_button(ok)
                    return
            if key == wx.WXK_ESCAPE:
                self.EndModal(wx.ID_CANCEL)
                return
        # **Cmd+W でも閉じる。** 作者の別のアプリと同じ約束にしてある。
        if (
            evt.GetModifiers() == wx.MOD_CONTROL
            and evt.GetKeyCode() in (ord("W"), ord("w"))
        ):
            self.EndModal(wx.ID_CANCEL)
            return
        evt.Skip()

    # -- 結果 -------------------------------------------------------------

    def result(self) -> AssignForm:
        """入力された設定。**元の値を壊さず、新しいものを返す。**

        **触らない項目は書き写さない**（`dataclasses.replace`）。
        全項目を手で並べていたときは、`AssignForm` に項目を足すたびに
        ここも直す必要があり、忘れると**開いて閉じただけで値が既定へ戻る。**
        """
        root_index = self._root.GetSelection()
        return replace(
            self._form,
            mode=MODE_ORDER[max(self._mode.GetSelection(), 0)],
            root_key=AUTO if root_index <= 0 else NOTE_NAMES[root_index - 1],
            octave=OCTAVES[max(self._octave.GetSelection(), 0)],
            tone_preset=self._tone.GetStringSelection() or DEFAULT_PRESET,
            phrase_span=SPANS[max(self._span.GetSelection(), 0)][1],
            target_bpm=self._bpm.GetValue(),
            allow_half_double=self._half_double.GetValue(),
        )
