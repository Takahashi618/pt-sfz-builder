"""主画面。上から順に「探す → 選ぶ → 割り当てる」。

**設定は Cmd+S のダイアログへ追い出した。** 主画面に並べていたときは
Tab を 6 回余分に押さないと実行ボタンへ届かなかった。繰り返し使うのは
探して選んで割り当てるところで、設定を変えるのは時々でよい。

### 作者の別のアプリと操作を揃える

作者の別のアプリと状況で
使い分けるので、**同じキーが同じ意味を持つ**ようにしてある。

| キー | 意味 |
| --- | --- |
| Cmd+S | 設定のダイアログ（あちらは「セッションの条件」） |
| Cmd+R | 素材の索引を更新（あちらは「フォルダをスキャン」） |
| Cmd+T | 割り当て先を調べ直す（あちらは「配置先のトラックを選ぶ」） |
| Cmd+C | パスをコピー。**文字入力欄では選んだ文字のコピー**（あちらと同じ） |
| Cmd+I | 検索結果一覧へ移動（作者の別のアプリと同じ） |
| Cmd+Shift+G | パックの並び順を順送り（同上。こちらは 4 つ） |
| Cmd+Shift+L | スロットの一覧 |
| Cmd+Q | 終了 |
| Cmd+Shift+K | キー操作の一覧（1 項目ずつたどれる一覧。`ui/keys_dialog.py`） |
| 一覧でスペース | 試聴の再生と停止 |
| 一覧で Enter | 実行（あちらは配置、こちらは割り当て） |
| 一覧で文字キー | その頭文字の項目へ飛ぶ |

### 守っていること

- **板は `wx.ScrolledWindow`。** 素の `wx.Panel` だと欄が高さ 0 に潰れる
- **読み上げ名は `label_control` で付ける**（macOS の `SetName` は入力欄に効かない）
- **状態はボタンの名前に入れる。** `StaticText` にはフォーカスが当たらない
- **名前を書き換えただけでは読まれない。** その場で `announce` する
- **修飾なしの文字キーを横取りしない。** 一覧で頭文字を打って飛べなくなる。
  機能のキーはメニューのアクセラレータ（Cmd 付き）に任せる
- **ボタンは Enter でも押せるようにする。** macOS の wx では既定ボタン以外は
  スペースでしか押せない
- **音は読み上げより先に鳴らす。** 重なると聞き取りにくい
- **`Cmd+L` は使わない。** macOS と競合する（作者の別のアプリが実測）。
  向こうが「リストへ」に `Cmd+I` を使っているので合わせた
- **一覧にフォーカスが来たら選択を戻す。** 何も選ばれていないと
  スペースも上下も効かず「操作できない」に見える（作者の別のアプリの
  `ensure_list_selection` と同じ考え方）
- **下位の窓は Escape と Cmd+W で閉じられること**

### 読み上げの間合い（2026-10-25 のレビューで直した）

能動読み上げは 2026-10-24 に借り先（`announce`）が直るまで
届いていなかった。届くようになったので、ほかのアプリが実機で詰めた約束を入れた。

- **メニューのキーで動かした結果は、押してから 800 ミリ秒あけて読む。**
  VoiceOver はまずメニューの項目名を読むので、すぐ読ませるとぶつかって切れる
  （作者の別のアプリが実機で詰めた値）
- **新しい読み上げが来たら、待っている古いものは読まない。** 順番が入れ替わらないように
- **Pro Tools を前に出す操作（読み込ませる）の結果は、このアプリを前に戻してから読む。**
  VoiceOver は前にいないアプリの読み上げを読まない（作者の別のアプリが実機で確認）
- 長いもの（キー操作の一覧・バージョン情報）は画面に出す。読み上げだけだと聞き直せない
"""

from __future__ import annotations

import os
import plistlib
import threading
import time
from dataclasses import replace
from pathlib import Path

import wx

from core.sibling import FROZEN, part_message
from core.version import VERSION
from integration.permissions import open_accessibility_settings, request_trust_prompt
from ui.assign_dialog import AssignDialog
from core.i18n import APP_NAME, tr
from ui.borrowed import (
    announce,
    announce_enabled,
    label_control,
    play_sound,
    play_sound_for,
    press_button,
)
from ui.controller import (
    KIND_FILTER_LABELS,
    MODE_LABELS,
    AppController,
    AssignForm,
    Outcome,
    SearchForm,
)
from ui.keys_dialog import KeysDialog
from ui.layout import display_area

__all__ = ["MainFrame", "ANNOUNCE_DELAY_MS", "MENU_READ_MS"]

# モーダルを閉じた直後に読ませるまでの間。実機で詰めた値。
ANNOUNCE_DELAY_MS = 250

# メニューのキーを押してから読ませるまでの間（上の「読み上げの間合い」）。
MENU_READ_MS = 800

# 前に戻ったあと、読ませるまでの間。VoiceOver はまず窓とフォーカスのある所を読む
# （作者の別のアプリと同じ値）。前に戻るのを待つのは最長 2 秒。
FRONT_SETTLE_MS = 300
FRONT_WAIT_SEC = 2.0

# 「待ってください」を言ってから、UI を止める処理を始めるまでの間
WAIT_NOTE_LEAD_MS = 150

# **言葉は `ui/controller.KIND_FILTER_LABELS` から取る**（日本語は `core/kinds.py` の言葉。
# 作者の別のアプリと同じ言い方にするため、ここで書き直さない）。
KIND_CHOICES: list[tuple[str, str]] = [
    (KIND_FILTER_LABELS[""], ""),
    (KIND_FILTER_LABELS["one_shot"], "one_shot"),
    (KIND_FILTER_LABELS["loop"], "loop"),
    (KIND_FILTER_LABELS["fx"], "fx"),
]


def _set_clipboard_text(text: str) -> bool:
    """クリップボードに文字を写す。写せたら True。**テストでは差し替える**
    （差し替えずに回していたときは、ビルドのたびに利用者のクリップボードが
    `/tmp/a.wav` に書き換わっていた）。
    """
    if not wx.TheClipboard.Open():
        return False
    try:
        wx.TheClipboard.SetData(wx.TextDataObject(text))
    finally:
        wx.TheClipboard.Close()
    return True


class MainFrame(wx.Frame):
    """本体の窓。"""

    def __init__(self, controller: AppController) -> None:
        super().__init__(None, title=APP_NAME)
        self.controller = controller
        # 割り当ての設定。**主画面には出さない**（Cmd+S のダイアログで変える）
        # 既定の配置は「素材に合わせる」。**実際の配置は割り当てるその場で
        # 決まる**ので、ここで一覧の選び直しを見張る必要は無い。
        self.form = AssignForm(target_bpm=controller.load_session_bpm())
        # どのセッションの設定を読み込み済みか。起動直後はまだ分からない。
        self._synced_session = ""
        # 読み込ませる操作が走っているか。**二重に押させない。**
        self._loading = False
        # 割り当て・索引の更新が走っているか。**二重に始めない**（下ごしらえの
        # 間に Enter をもう一度押すと、同じ割り当てを 2 回していた）。
        self._assigning = False
        self._scanning = False
        # 窓が生きているか。別スレッドの結果を捨てる判断に使う。
        self._alive = True
        # メニューのキーを押した時刻（`_from_menu`）。読ませる間合いに使う。
        self._menu_at: float | None = None
        # 読み上げの通し番号。**新しいものが来たら、待っている古いものは読まない。**
        self._announce_seq = 0
        self._build_menu()
        self._build_ui()
        self._bind()
        self._fit_to_content()
        self._refresh_settings_button()
        # **割り当て先を調べるのは窓を出したあと。**
        # `detect_target` は osascript を呼ぶので実測 270 ミリ秒かかる。
        # 表示前に走らせると、その間まるごと無音になり、起動したのか
        # どうかが分からない（System Events が詰まると最大 15 秒）。
        wx.CallAfter(self._refresh_target, announce_it=False)

    # -- メニュー ---------------------------------------------------------

    def _build_menu(self) -> None:
        """メニューバー。**macOS では必ず作る。**

        **ショートカットには必ず修飾キーを付ける。** 修飾なしの文字キーを
        割り当てると、一覧で頭文字を打って飛ぶ操作が使えなくなる。
        `\\tCtrl+…` と書くと macOS では Cmd に読み替えられる。
        """
        bar = wx.MenuBar()
        ops = wx.Menu()

        self._id_settings = wx.NewIdRef()
        self._id_assign = wx.NewIdRef()
        self._id_preview = wx.NewIdRef()
        self._id_load = wx.NewIdRef()
        self._id_pick = wx.NewIdRef()
        self._id_detect = wx.NewIdRef()
        self._id_copy = wx.NewIdRef()
        self._id_rescan = wx.NewIdRef()
        self._id_splice = wx.NewIdRef()
        self._id_clean = wx.NewIdRef()
        self._id_slots = wx.NewIdRef()
        self._id_focus_list = wx.NewIdRef()
        self._id_pack_order = wx.NewIdRef()
        self._id_access = wx.NewIdRef()
        self._id_keys = wx.NewIdRef()
        self._id_version = wx.NewIdRef()

        ops.Append(self._id_settings, tr(
            "割り当ての設定\tCtrl+S",
            "Assign Settings\tCtrl+S",
        ), tr(
            "配置・テンポ・ルートキー・音作り",
            "Mapping, tempo, root key and tone",
        ))
        ops.Append(self._id_assign, tr("割り当てを実行", "Assign"), tr(
            "選んでいる素材を鍵盤に載せる",
            "Put the selected sample on the keyboard",
        ))
        ops.Append(self._id_preview, tr("試聴 再生/停止", "Preview Play/Stop"), tr(
            "選んでいる素材を聴く",
            "Listen to the selected sample",
        ))
        ops.AppendSeparator()
        ops.Append(self._id_detect, tr(
            "割り当て先を調べ直す\tCtrl+T",
            "Check Assignment Target Again\tCtrl+T",
        ), tr(
            "前面のプラグインを見る",
            "Look at the plugin in front",
        ))
        ops.Append(self._id_load, tr(
            "プラグインに読み込ませる",
            "Load into Plugin",
        ), tr("初回だけ必要", "Needed only the first time"))
        ops.Append(self._id_pick, tr(
            "ファイルを選んで割り当て",
            "Choose a File to Assign",
        ), tr(
            "ライブラリ外のファイル",
            "A file outside the library",
        ))
        ops.AppendSeparator()
        ops.Append(self._id_copy, tr("パスをコピー\tCtrl+C", "Copy Path\tCtrl+C"), tr(
            "選んでいる素材のパスを写す",
            "Copy the path of the selected sample",
        ))
        ops.Append(self._id_rescan, tr(
            "Splice の索引を更新\tCtrl+R",
            "Update Splice Index\tCtrl+R",
        ), tr(
            "買い足した素材を登録する",
            "Register newly added samples",
        ))
        ops.Append(
            self._id_splice,
            tr("Splice のフォルダを選ぶ", "Choose Splice Folder"),
            tr(
                "Splice の素材が入っているフォルダを選び直す",
                "Choose again the folder that holds your Splice samples",
            ),
        )
        ops.Append(
            self._id_pack_order,
            tr("パックの並び順を順送り\tCtrl+Shift+G", "Change Pack Order\tCtrl+Shift+G"),
            tr(
                "中身の多い順、名前順、更新の新しい順、追加した順",
                "Most samples first, by name, recently updated first, order added",
            ),
        )
        ops.Append(self._id_clean, tr(
            "使っていない下ごしらえを片付ける",
            "Clean Up Unused Prepared Files",
        ), tr("容量を空ける", "Free up space"))
        ops.Append(self._id_focus_list, tr(
            "検索結果一覧へ移動\tCtrl+I",
            "Move to Result List\tCtrl+I",
        ), tr(
            "一覧にフォーカスを移す",
            "Move the focus to the list",
        ))
        # **`Cmd+L` は使わない。** macOS と競合する（作者の別のアプリが実測）。
        ops.Append(
            self._id_slots, tr(
                "スロットの一覧\tCtrl+Shift+L",
                "Slot List\tCtrl+Shift+L",
            ), tr(
                "どのスロットに何が載っているか",
                "What is in each slot",
            )
        )
        ops.AppendSeparator()
        ops.Append(
            self._id_access,
            tr("アクセシビリティの設定を開く", "Open Accessibility Settings"),
            tr("許可はご自身で入れてください", "Please turn on the permission yourself"),
        )
        ops.AppendSeparator()
        ops.Append(wx.ID_EXIT, tr("終了\tCtrl+Q", "Quit\tCtrl+Q"))
        bar.Append(ops, tr("操作", "Actions"))

        help_menu = wx.Menu()
        # **Cmd+/ は使わない。** Pro Tools のショートカットと重なる。
        help_menu.Append(self._id_keys, tr(
            "キー操作の一覧\tCtrl+Shift+K",
            "Keyboard Commands\tCtrl+Shift+K",
        ))
        # **`wx.ID_ABOUT` は使わない。** macOS では自動でアプリメニューへ移り、
        # ヘルプから辿れなくなる。
        help_menu.Append(self._id_version, tr("バージョン情報", "Version Information"), tr(
            "版・ビルドの日時とコミット",
            "Version, build date and commit",
        ))
        bar.Append(help_menu, tr("ヘルプ", "Help"))

        self.SetMenuBar(bar)

    # -- 画面 -------------------------------------------------------------

    def _build_ui(self) -> None:
        # **素の Panel にしない。** 入りきらない欄が高さ 0 に潰れる。
        panel = wx.ScrolledWindow(self, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        panel.SetScrollRate(0, 20)
        self._panel = panel
        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(self._heading(panel, tr("素材を探す", "Find samples")), 0, wx.ALL, 4)
        self._text = self._text_field(panel, outer, tr("検索語", "Search word"))
        self._key = self._choice(
            panel, outer, tr("キー", "Key"), [tr("すべてのキー", "All keys")] + list(_note_names())
        )
        self._relative = wx.CheckBox(panel, label=tr("平行調も含める", "Include the relative key"))
        label_control(self._relative, tr("平行調も含める", "Include the relative key"))
        outer.Add(self._relative, 0, wx.ALL, 4)
        self._bpm = self._text_field(panel, outer, tr(
            "BPM。空欄なら指定しない",
            "BPM. If empty, not used",
        ))
        self._kind = self._choice(
            panel, outer, tr("種別", "Type"), [name for name, _ in KIND_CHOICES]
        )
        self._pack = self._choice(panel, outer, tr("パック", "Pack"), [tr(
            "すべてのパック",
            "All packs",
        )])

        self._search_btn = wx.Button(panel, label=tr("検索を実行", "Search"))
        label_control(self._search_btn, tr("検索を実行", "Search"))
        outer.Add(self._search_btn, 0, wx.ALL, 4)

        outer.Add(self._heading(panel, tr("検索結果一覧", "Result list")), 0, wx.ALL, 4)
        self._results = wx.ListBox(panel, style=wx.LB_SINGLE)
        label_control(
            self._results,
            tr(
                "検索結果一覧。上下で移動、文字キーでその頭文字へ、"
                "スペースで試聴、Enter で割り当て",
                "Result list. Up and Down arrows to move, a letter key to jump to that letter, "
                "Space to preview, Return to assign",
            ),
        )
        outer.Add(self._results, 1, wx.EXPAND | wx.ALL, 4)

        outer.Add(self._heading(panel, tr("実行", "Run")), 0, wx.ALL, 4)
        self._settings_btn = wx.Button(panel, label=tr("割り当ての設定", "Assign Settings"))
        outer.Add(self._settings_btn, 0, wx.ALL, 4)
        self._assign_btn = wx.Button(panel, label=tr("割り当てを実行", "Assign"))
        label_control(self._assign_btn, tr("割り当てを実行", "Assign"))
        outer.Add(self._assign_btn, 0, wx.ALL, 4)
        self._load_btn = wx.Button(panel, label=tr(
            "プラグインに読み込ませる（初回だけ）",
            "Load into Plugin (first time only)",
        ))
        label_control(self._load_btn, tr(
            "プラグインに読み込ませる。初回だけ必要",
            "Load into Plugin. Needed only the first time",
        ))
        outer.Add(self._load_btn, 0, wx.ALL, 4)
        self._file_btn = wx.Button(panel, label=tr(
            "ファイルを選んで割り当て",
            "Choose a File to Assign",
        ))
        label_control(self._file_btn, tr("ファイルを選んで割り当て", "Choose a File to Assign"))
        outer.Add(self._file_btn, 0, wx.ALL, 4)
        self._target_btn = wx.Button(panel, label=tr(
            "割り当て先を調べる",
            "Check Assignment Target",
        ))
        outer.Add(self._target_btn, 0, wx.ALL, 4)

        self._status = _static(panel, tr("準備完了", "Ready"), name=tr("状態", "Status"))
        outer.Add(self._status, 0, wx.ALL, 4)

        panel.SetSizer(outer)
        panel.FitInside()
        self._outer = outer
        self._reload_packs()

    def _heading(self, parent: wx.Window, text: str) -> wx.StaticText:
        st = _static(parent, text)
        font = st.GetFont()
        font.MakeBold()
        st.SetFont(font)
        return st

    def _text_field(self, parent, sizer, label: str) -> wx.TextCtrl:
        sizer.Add(_static(parent, label), 0, wx.LEFT | wx.TOP, 4)
        ctrl = wx.TextCtrl(parent, style=wx.TE_PROCESS_ENTER)
        label_control(ctrl, label)
        sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 4)
        return ctrl

    def _choice(self, parent, sizer, label: str, choices: list[str]) -> wx.Choice:
        sizer.Add(_static(parent, label), 0, wx.LEFT | wx.TOP, 4)
        ctrl = wx.Choice(parent, choices=choices)
        ctrl.SetSelection(0)
        label_control(ctrl, label)
        sizer.Add(ctrl, 0, wx.EXPAND | wx.ALL, 4)
        return ctrl

    def _fit_to_content(self) -> None:
        """**大きさは中身から決めて、画面の作業領域で頭打ちにする。**"""
        need = self._outer.GetMinSize()
        area = display_area(self)
        self.SetSize(
            (
                min(need.width + 40, area.width),
                min(need.height + 60, int(area.height * 0.92)),
            )
        )
        self.SetMinSize((360, 320))

    # -- 配線 -------------------------------------------------------------

    def _bind(self) -> None:
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)
        for ident, handler in (
            (self._id_settings, self._on_settings),
            (self._id_assign, self._on_assign),
            (self._id_preview, self._on_preview),
            (self._id_load, self._on_load),
            (self._id_pick, self._on_pick_file),
            (self._id_detect, self._on_detect),
            (self._id_copy, self._on_copy),
            (self._id_rescan, self._on_rescan),
            (self._id_splice, self._on_choose_splice),
            (self._id_clean, self._on_clean),
            (self._id_slots, self._on_slots),
            (self._id_focus_list, self._on_focus_list),
            (self._id_pack_order, self._on_pack_order),
            (self._id_access, self._on_accessibility),
            (self._id_keys, self._on_keys),
            (self._id_version, self._on_version),
        ):
            self.Bind(wx.EVT_MENU, self._from_menu(handler), id=ident)

        self._search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self._text.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self._bpm.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self._settings_btn.Bind(wx.EVT_BUTTON, self._on_settings)
        self._assign_btn.Bind(wx.EVT_BUTTON, self._on_assign)
        self._load_btn.Bind(wx.EVT_BUTTON, self._on_load)
        self._file_btn.Bind(wx.EVT_BUTTON, self._on_pick_file)
        self._target_btn.Bind(wx.EVT_BUTTON, self._on_detect)
        self._results.Bind(wx.EVT_LISTBOX_DCLICK, self._on_assign)
        # **一覧にフォーカスが来たら選択を戻す。** 何も選ばれていないと
        # スペースも上下も効かず「操作できない」に見える。
        self._results.Bind(wx.EVT_SET_FOCUS, self._on_list_focus)
        # **キー処理は 1 か所に集める。** 部品ごとに書くと取りこぼす。
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _from_menu(self, handler):
        """メニュー（とそのキー）から呼ばれたことを控えて、`handler` を呼ぶ。

        **VoiceOver はまずメニューの項目名を読む。** その間に結果を読ませると
        ぶつかって切れるので、`_report` が押した時刻から `MENU_READ_MS` あける。
        """

        def run(evt) -> None:
            self._menu_at = time.monotonic()
            try:
                handler(evt)
            finally:
                self._menu_at = None

        return run

    def _menu_wait_ms(self) -> int:
        """メニューのキーを押してから `MENU_READ_MS` に足りない分。メニューでなければ 0。"""
        if self._menu_at is None:
            return 0
        spent = int((time.monotonic() - self._menu_at) * 1000)
        return max(0, MENU_READ_MS - spent)

    def _on_char_hook(self, evt: wx.KeyEvent) -> None:
        """窓全体のキー処理。

        **修飾なしの文字キーは横取りしない。** 一覧では頭文字を打って
        項目へ飛べる（リストの標準機能）。ここで拾うと使えなくなる。
        """
        focused = self._focused()

        # **ボタンは Enter でも押せるようにする。**
        if (
            isinstance(focused, wx.Button)
            and evt.GetModifiers() == wx.MOD_NONE
            and evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
        ):
            press_button(focused)
            return

        if focused is self._results and evt.GetModifiers() == wx.MOD_NONE:
            key = evt.GetKeyCode()
            if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._on_assign(evt)
                return
            if key == wx.WXK_SPACE:
                self._on_preview(evt)
                return
        evt.Skip()

    def _focused(self) -> wx.Window | None:
        """いまフォーカスのある部品。**テストでは差し替える**（窓が前にいないと
        フォーカスが取れないため）。"""
        return wx.Window.FindFocus()

    # -- 値の取り出し ------------------------------------------------------

    def _search_form(self) -> SearchForm:
        names = _note_names()
        key_index = self._key.GetSelection()
        kind_index = self._kind.GetSelection()
        return SearchForm(
            text=self._text.GetValue().strip(),
            key="" if key_index <= 0 else names[key_index - 1],
            relative=self._relative.GetValue(),
            bpm=self._bpm.GetValue().strip(),
            kind=KIND_CHOICES[max(kind_index, 0)][1],
            pack=(
                ""
                if self._pack.GetSelection() <= 0
                else self._pack.GetStringSelection()
            ),
        )

    def _selected_path(self) -> str | None:
        """いま選んでいる素材のパス。選んでいなければ None。

        一覧は `wx.LB_SINGLE` なので**常に 1 件以下。**
        以前は list で返していたが、使う側は毎回 `[0]` を取っていた。
        """
        index = self._results.GetSelection()
        if index == wx.NOT_FOUND:
            return None
        return self.controller.result_path(index)

    # -- 操作 -------------------------------------------------------------

    def _reload_packs(self) -> None:
        self._pack.Set([tr("すべてのパック", "All packs")] + self.controller.packs())
        self._pack.SetSelection(0)

    def _on_search(self, _evt) -> None:
        play_sound("start")
        outcome = self.controller.search(self._search_form())
        self._report(outcome)
        self._results.Set(self.controller.result_labels())
        if self.controller.results:
            self._select_result(0)

    def _on_settings(self, _evt) -> None:
        """Cmd+S。割り当ての設定を変える。"""
        with AssignDialog(self, self.form) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self._report(tr(
                    "設定を変えずに閉じました。",
                    "Closed without changing the settings.",
                ), ok=True, delay_ms=ANNOUNCE_DELAY_MS)
                return
            self.form = dialog.result()
        self.controller.save_session_bpm(self.form.target_bpm)
        self._refresh_settings_button()
        self._report(
            tr(
                f"設定を変えました。{self._settings_summary()}",
                f"Settings changed. {self._settings_summary()}",
            ),
            ok=True,
            delay_ms=ANNOUNCE_DELAY_MS,
        )

    def _settings_summary(self) -> str:
        bpm = self.form.target_bpm.strip()
        tempo = tr(
            f"セッションのテンポ {bpm}",
            f"session tempo {bpm}",
        ) if bpm else tr("テンポは素材のまま", "the sample's own tempo")
        return tr(
            f"{MODE_LABELS.get(self.form.mode, self.form.mode)}、{tempo}",
            f"{MODE_LABELS.get(self.form.mode, self.form.mode)}, {tempo}",
        )

    def _refresh_settings_button(self) -> None:
        """**状態はボタンの名前に入れる。** `StaticText` は耳に入らない。"""
        name = tr(
            f"割り当ての設定。いまは {self._settings_summary()}",
            f"Assign Settings. Now: {self._settings_summary()}",
        )
        self._settings_btn.SetLabelText(name)
        self._settings_btn.SetName(name)
        label_control(self._settings_btn, name)
        self._panel.Layout()

    def _on_detect(self, _evt) -> None:
        self._refresh_target(announce_it=True)

    def _refresh_target(self, *, announce_it: bool) -> None:
        """割り当て先を調べ直し、ボタンの名前に状態を入れる。

        **読み上げはボタンを書き換える前。** この操作はそのボタンの上から
        呼ばれることがあり、名前を先に変えると VoiceOver の自動読み上げが
        こちらの発話を上書きする。
        """
        outcome = self.controller.detect_target()
        if announce_it:
            self._report(outcome)
        name = tr(
            f"割り当て先を調べる。いまは {outcome.message_ja}",
            f"Check Assignment Target. Now: {outcome.message_ja}",
        )
        self._target_btn.SetLabelText(name)
        self._target_btn.SetName(name)
        label_control(self._target_btn, name)
        self._panel.Layout()
        self._sync_session()

    def _sync_session(self) -> None:
        """セッションが変わったら、そのセッションの設定を読み直す。

        **テンポは曲の性質。** セッションを開き直したら、そのときの値が
        戻るのが正しい。起動直後はまだセッション名が分からないので、
        分かった時点でここで合わせる。
        """
        session = self.controller.session
        if session == self._synced_session:
            return
        self._synced_session = session
        self.form = replace(
            self.form, target_bpm=self.controller.load_session_bpm()
        )
        self._refresh_settings_button()

    def _select_result(self, index: int) -> None:
        """一覧の項目を選ぶ。

        **`SetSelection` は `EVT_LISTBOX` を出さない。** 以前は選び直しの
        副作用で配置を寄せていたため、検索直後の先頭の項目（いちばん
        押される経路）にだけ効かなかった。いまは配置を割り当てる場で
        決めるので、ここは選ぶだけでよい。
        """
        if 0 <= index < self._results.GetCount():
            self._results.SetSelection(index)

    def _on_pack_order(self, _evt) -> None:
        """Cmd+Shift+G。パックの並び順を順送りする。

        中身の多い順 → 名前順 → 更新の新しい順 → 追加した順（古いものから）。

        **既定は中身の多い順。** 実測で 553 パック中 389 個が 1 件だけ
        だったので、名前順だと目当ての大きなパックが埋もれる
        （作者の別のアプリの実測）。

        **日時は 2 種類あり、意味が違う。** 更新は「そのパックで最も新しい
        素材」、追加は「最も古い素材」。Splice は素材を 1 つずつ落とすので、
        買い足し続けているパックでは離れる。
        """
        outcome = self.controller.cycle_pack_order()
        # **読み上げは並べ替えより先。** パックの選択欄にフォーカスが
        # あるまま値が変わると、自動読み上げがこちらの発話を上書きする。
        self._report(outcome)
        # いま選んでいたパックを保つ。並べ替えで別のパックに変わると困る。
        chosen = (
            self._pack.GetStringSelection() if self._pack.GetSelection() > 0 else ""
        )
        self._reload_packs()
        if chosen:
            index = self._pack.FindString(chosen)
            if index != wx.NOT_FOUND:
                self._pack.SetSelection(index)

    def _on_focus_list(self, _evt) -> None:
        """Cmd+I。一覧へ移る。**どこからでも戻れるようにする。**"""
        if not self.controller.results:
            self._report(tr(
                "検索結果がありません。先に検索してください。",
                "There are no search results. Please search first.",
            ), ok=False)
            return
        self._results.SetFocus()
        self._ensure_list_selection()

    def _on_list_focus(self, evt) -> None:
        evt.Skip()
        self._ensure_list_selection()

    def _ensure_list_selection(self) -> None:
        """何も選ばれていなければ先頭を選ぶ。

        **選択が無いとスペースも上下も効かない。** 利用者からは
        「操作できない」に見える（作者の別のアプリで同じ不具合があった）。
        """
        if self._results.GetCount() and self._results.GetSelection() == wx.NOT_FOUND:
            self._select_result(0)

    def _on_preview(self, _evt) -> None:
        index = self._results.GetSelection()
        path = self.controller.result_path(index) if index != wx.NOT_FOUND else None
        self._report(self.controller.toggle_preview(path), sound=False)

    def _on_copy(self, _evt) -> None:
        """Cmd+C。選んでいる素材のパスを写す。**文字入力欄では選んだ文字を写す。**

        メニューの Cmd+C は入力欄より先に受け取る。以前は欄の中でも
        「パスをコピー」になり、検索語の欄で Cmd+C を押しても文字が写らず、
        「一覧から素材を選んでください」と言っていた（2026-10-25 に実物の窓で
        確かめた）。作者の別のアプリと同じく、欄では欄のコピーにする。
        """
        focused = self._focused()
        if isinstance(focused, wx.TextCtrl):
            if focused.CanCopy():
                focused.Copy()
            return
        path = self._selected_path()
        if path is None:
            self._report(tr(
                "一覧から素材を選んでください。",
                "Please choose a sample from the list.",
            ), ok=False)
            return
        if _set_clipboard_text(path):
            self._report(tr(
                f"パスをコピーしました。{Path(path).name}",
                f"Path copied. {Path(path).name}",
            ), ok=True)
            return
        self._report(tr(
            "[警告] クリップボードを開けませんでした。",
            "[Warning] Could not open the clipboard.",
        ), ok=False)

    def _on_assign(self, _evt) -> None:
        path = self._selected_path()
        if path is None:
            self._report(tr(
                "一覧から素材を選んでください。",
                "Please choose a sample from the list.",
            ), ok=False)
            return
        self._do_assign([path])

    def _do_assign(self, paths: list[str], *, delay_ms: int = 0) -> None:
        """割り当てる。**下ごしらえで待たせるときは、言ってから始める。**

        `delay_ms` はモーダル（ファイルを選ぶ画面）を閉じた直後用。
        """
        if self._assigning:
            self._report(tr(
                "いま割り当てています。終わるまでお待ちください。",
                "Assigning now. Please wait until it finishes.",
            ), ok=False)
            return
        self._assigning = True
        try:
            # **割り当てる前に試聴を止める。** 鳴ったまま次の音が出ると分からない。
            self.controller.stop_preview()
            # **割り当て先は先に調べる。** あとから調べていたときは、
            # ボタンの名前だけが新しくなり、書き込み先は古いままだった。
            # 先に調べれば osascript も 1 回で済む（実測 270 ミリ秒）。
            self._refresh_target(announce_it=False)
            wait_note = self.controller.wait_note_ja(paths, self.form)
        except Exception:
            self._assigning = False
            raise
        if not wait_note:
            self._finish_assign(paths, delay_ms)
            return
        # **待たせる前に、待つことを伝える。** 下ごしらえの間は UI が止まる。
        # 以前は `wx.Yield()` で済ませていたが、そのあいだに押された Enter で
        # 割り当てが入れ子に走り、メニューから実行したときは読み上げが
        # 項目名とぶつかっていた。読ませてから、少しあけて始める。
        wait = max(delay_ms, self._menu_wait_ms())
        play_sound("start")
        self._report(wait_note, sound=False, delay_ms=wait)
        wx.CallLater(wait + WAIT_NOTE_LEAD_MS, self._finish_assign, paths, 0)

    def _finish_assign(self, paths: list[str], delay_ms: int) -> None:
        try:
            if not self._alive:
                return
            outcome = self.controller.assign(paths, self.form)
            self._report(outcome, delay_ms=delay_ms)
            self._update_load_button()
        finally:
            self._assigning = False

    def _update_load_button(self) -> None:
        needed = self.controller.needs_loading()
        self._load_btn.Enable(needed)
        name = (
            tr("プラグインに読み込ませる。いま必要です", "Load into Plugin. Needed now")
            if needed
            else tr(
                "プラグインに読み込ませる。いまは必要ありません",
                "Load into Plugin. Not needed now",
            )
        )
        self._load_btn.SetName(name)
        label_control(self._load_btn, name)

    def _on_load(self, _evt) -> None:
        """プラグインに読み込ませる。**別のスレッドで走らせる。**

        座標クリックと AppleScript の待ちで実測 11 秒ほどかかる。
        UI のスレッドで走らせると、その間キー入力も読み上げも止まり、
        画面を見ない利用者には「固まった」としか分からない
        （2026-09-05 のレビューで実測）。

        **どれくらい待つかを先に言う。** 待つこと自体は避けられないので、
        せめて見当が付くようにする。
        """
        if self._loading:
            self._report(
                tr(
                    "いま読み込ませています。終わるまでお待ちください。",
                    "Loading now. Please wait until it finishes.",
                ), ok=False
            )
            return
        self._loading = True
        self._load_btn.Enable(False)
        play_sound("start")
        self._report(
            tr(
                "プラグインに読み込ませています。10秒ほどかかります。",
                "Loading into the plugin. This takes about 10 seconds.",
            ), sound=False
        )
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self) -> None:
        """別スレッド。**wx には触らない。** 例外でも必ず結果を返す（返さないと
        「読み込ませています」のまま、二度と押せなくなる）。
        """
        try:
            outcome = self.controller.load_into_plugin()
        except Exception as exc:
            outcome = Outcome(False, tr(
                f"[エラー] 読み込ませる途中で止まりました（{exc}）。",
                f"[Error] Stopped in the middle of loading ({exc}).",
            ))
        wx.CallAfter(self._finish_load, outcome)

    def _finish_load(self, outcome) -> None:
        """読み込ませ終わった。**UI のスレッドで呼ばれる。**

        **このアプリを前に戻してから読む。** 読み込ませる道具は Pro Tools を
        前に出すので、そのまま読ませると VoiceOver が読まない。
        """
        self._loading = False
        if not self._alive:
            return
        self._report(outcome, front=True)
        self._update_load_button()

    def _on_pick_file(self, _evt) -> None:
        """ライブラリの外のファイルも扱えるようにする。"""
        with wx.FileDialog(
            self,
            tr("割り当てるファイルを選ぶ", "Choose a file to assign"),
            wildcard=tr(
                "音声ファイル|*.wav;*.aif;*.aiff;*.flac;*.ogg|すべて|*.*",
                "Audio files|*.wav;*.aif;*.aiff;*.flac;*.ogg|All files|*.*",
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self._report(tr(
                    "選ばずに閉じました。",
                    "Closed without choosing.",
                ), sound=False, delay_ms=ANNOUNCE_DELAY_MS)
                return
            paths = list(dialog.GetPaths())
        # **一覧から割り当てるときと同じ道を通す。** 別に書いていたときは、
        # 下ごしらえで待たせるのに何も言わなかった。
        self._do_assign(paths, delay_ms=ANNOUNCE_DELAY_MS)

    def _on_rescan(self, _evt) -> None:
        self._start_rescan()

    def _start_rescan(self, prefix: str = "", *, delay_ms: int = 0) -> None:
        """索引を作り直す。**別のスレッドで走らせる。**

        いつもは 1 秒ほどだが、初めて作るときは全部の素材の頭を読むので、
        素材の多い人だと長くかかる。UI のスレッドで走らせると、その間
        VoiceOver も黙り、固まったように見える。
        """
        if self._scanning:
            self._report(tr(
                "いま索引を更新しています。終わるまでお待ちください。",
                "Updating the index now. Please wait until it finishes.",
            ), ok=False)
            return
        self._scanning = True
        play_sound("start")
        self._report(
            tr(
                f"{prefix}索引を更新しています。終わったらお知らせします。",
                f"{prefix}Updating the index. You will be told when it finishes.",
            ),
            sound=False,
            delay_ms=delay_ms,
        )
        threading.Thread(target=self._rescan_worker, daemon=True).start()

    def _rescan_worker(self) -> None:
        """別スレッド。**wx には触らない。** 例外でも必ず結果を返す。"""
        try:
            outcome = self.controller.rescan_library()
        except Exception as exc:
            outcome = Outcome(False, tr(
                f"索引を更新できませんでした: {exc}",
                f"Could not update the index: {part_message(str(exc))}",
            ))
        wx.CallAfter(self._finish_rescan, outcome)

    def _finish_rescan(self, outcome) -> None:
        self._scanning = False
        if not self._alive:
            return
        if outcome.ok:
            self._reload_packs()
        self._report(outcome)

    def _on_choose_splice(self, _evt) -> None:
        """操作メニューの「Splice のフォルダを選ぶ」。選んだら索引を作り直す。

        **Splice のフォルダは利用者が動かせる**（Splice のアプリの設定）。決まった
        場所に無いと、検索が何も見つけない（作者の別のアプリと同じ）。
        """
        if self._scanning:
            self._report(tr(
                "いま索引を更新しています。終わるまでお待ちください。",
                "Updating the index now. Please wait until it finishes.",
            ), ok=False)
            return
        with wx.DirDialog(
            self,
            tr(
                "Splice の素材が入っているフォルダを選ぶ",
                "Choose the folder that holds your Splice samples",
            ),
            defaultPath=str(self.controller.splice_root),
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self._report(tr(
                    "選ばずに閉じました。",
                    "Closed without choosing.",
                ), sound=False, delay_ms=ANNOUNCE_DELAY_MS)
                return
            chosen = dialog.GetPath()
        outcome = self.controller.set_splice_root(chosen)
        if not outcome.ok:
            self._report(outcome, delay_ms=ANNOUNCE_DELAY_MS)
            return
        # 前のフォルダの検索結果とパックは使わない
        self._results.Set([])
        self._reload_packs()
        self._start_rescan(outcome.message_ja, delay_ms=ANNOUNCE_DELAY_MS)

    def _on_clean(self, _evt, *, confirm: bool = True) -> None:
        """使っていない下ごしらえを片付ける。**消す前に量を言う。**

        `confirm=False` はテスト用。`ShowModal` は入力を待つので、
        テストから呼ぶと返らない。
        """
        found = self.controller.unused_renders_ja()
        self._report(found, sound=False)
        # **消すものが無ければ聞かない。** 文言の言い回しで判断していたときは、
        # 言い方を変えると「消してよいですか」と聞く道があった。
        if not found.ok or not self.controller.unused_paths:
            return
        if confirm:
            answer = wx.MessageBox(
                found.message_ja + tr(" 消してよいですか。", " Delete them?"),
                tr("下ごしらえの片付け", "Clean up prepared files"),
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            if answer != wx.YES:
                self._report(tr(
                    "片付けをやめました。",
                    "Cleanup canceled.",
                ), sound=False, delay_ms=ANNOUNCE_DELAY_MS)
                return
        done = self.controller.clean_renders()
        if confirm:
            self._report(done, delay_ms=ANNOUNCE_DELAY_MS)
        else:
            self._report(done)

    def _on_slots(self, _evt) -> None:
        self._report(self.controller.slot_summary_ja(), sound=False)

    def _on_accessibility(self, _evt) -> None:
        """アクセシビリティの設定を開く。**入り切りは利用者本人がする。**

        配布版を初めて開いた人が必ず通る。Pro Tools の画面を読むのにも、
        sforzando を押すのにも要る。
        """
        request_trust_prompt()
        if open_accessibility_settings():
            self._report(
                tr(
                    f"システム設定のアクセシビリティを開きました。一覧で {APP_NAME} "
                    "をオンにしてください。",
                    f"Opened Accessibility in System Settings. Please turn on {APP_NAME} in the "
                    "list.",
                ),
                ok=True,
            )
        else:
            self._report(tr(
                "[エラー] システム設定を開けませんでした。",
                "[Error] Could not open System Settings.",
            ), ok=False)

    def _on_keys(self, _evt) -> None:
        """キー操作の一覧を、1 項目ずつたどれる画面で開く（`ui/keys_dialog.py`）。"""
        self._show_keys()
        self._report(tr(
            "キー操作の一覧を閉じました。",
            "Closed the list of keyboard commands.",
        ), sound=False, delay_ms=ANNOUNCE_DELAY_MS)

    def _show_keys(self) -> None:
        """一覧の画面を出す。**テストでは差し替える**（モーダルは入力を待って返らない）。"""
        with KeysDialog(self) as dialog:
            dialog.ShowModal()

    def _on_version(self, _evt) -> None:
        """**いつビルドしたものかを確かめられるようにする。** 画面に出す。

        凍結ビルドではないので、見ただけでは中身の新しさが分からない。
        読み上げだけだと、メニューから選んだときに項目名とぶつかって
        読まれないことがある（作者の別のアプリが実機で確認。画面にした）。
        """
        text = _version_text()
        self._status.SetLabelText(text)
        self._show_info(tr("バージョン情報", "Version Information"), text)

    def _show_info(self, title: str, text: str) -> None:
        """知らせの画面を出す。**テストでは差し替える。**"""
        wx.MessageBox(text, title, wx.OK | wx.ICON_INFORMATION, self)

    def _on_close(self, evt) -> None:
        # **閉じたあとに別スレッドの結果で触らない。**
        self._alive = False
        self.controller.stop_preview()
        evt.Skip()

    # -- 読み上げ ---------------------------------------------------------

    def _report(
        self,
        message,
        *,
        ok: bool | None = None,
        sound: bool = True,
        delay_ms: int = 0,
        front: bool = False,
    ) -> None:
        """結果を伝える。**音 → 読み上げ → 画面**の順。

        `message` には `Outcome` をそのまま渡せる。**そのときは成否から
        音を選ぶ。** 文言の接頭辞（`[警告]` / `[エラー]`）だけで判断して
        いたときは、接頭辞の無い失敗（「合う素材はありませんでした」
        「プラグインのウィンドウが開いていません」など）で**成功音が
        鳴っていた。** 読み上げ利用者にとって音は最初の合図なので、
        逆になっていると気づけない。

        `delay_ms` はモーダルを閉じた直後用。すぐ読ませると、
        窓が戻る動きに重なって聞き取れない。メニューのキーで動いたときは、
        押してから `MENU_READ_MS` あける（モジュールの説明）。

        `front=True` は、このアプリを前に戻してから読む（Pro Tools を
        前に出す操作の結果）。

        読み上げをコントロールの更新より**先**に呼ぶ
        （後にすると自動読み上げがこちらの発話を上書きする）。
        """
        if hasattr(message, "message_ja"):
            if ok is None:
                ok = bool(getattr(message, "ok", True))
            message = message.message_ja
        if not message:
            return
        if sound:
            if ok is None:
                play_sound_for(message)
            else:
                play_sound("success" if ok else "failure")
        self._announce_later(
            message, max(delay_ms, self._menu_wait_ms()), front=front
        )
        # **SetLabel は使わない。** `&` を飾りの印として消してしまう
        # （「Drum & Bass.wav」「Privacy & Security」）
        self._status.SetLabelText(message.replace("\n", " "))

    def _announce_later(self, message: str, delay_ms: int, *, front: bool) -> None:
        """読み上げる。**新しいものが来たら、待っている古いものは読まない。**"""
        self._announce_seq += 1
        seq = self._announce_seq
        if front and announce_enabled() and not _app_is_active():
            self._announce_in_front(seq, message)
        elif delay_ms > 0:
            wx.CallLater(delay_ms, self._speak_if_latest, seq, message)
        else:
            announce(message)

    def _speak_if_latest(self, seq: int, message: str) -> None:
        if seq == self._announce_seq and self._alive:
            announce(message)

    def _announce_in_front(self, seq: int, message: str) -> None:
        """このアプリを前に戻し、前になってから読む。

        前に戻ると VoiceOver はまず窓とフォーカスのある所を読むので、
        前になったのを確かめてから少し待って割り込む（作者の別のアプリと同じ）。
        """
        _activate_self(self)
        deadline = time.monotonic() + FRONT_WAIT_SEC

        def wait_front() -> None:
            if seq != self._announce_seq or not self._alive:
                return
            if _app_is_active() or time.monotonic() >= deadline:
                wx.CallLater(FRONT_SETTLE_MS, self._speak_if_latest, seq, message)
                return
            wx.CallLater(50, wait_front)

        wx.CallLater(50, wait_front)


def _app_is_active() -> bool:
    app = wx.GetApp()
    try:
        return bool(app and app.IsActive())
    except Exception:
        return True


def _activate_self(frame: wx.Frame) -> None:
    """このアプリを前に出す。**読み上げを届けるためだけに使う。**"""
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass
    try:
        frame.Raise()
    except Exception:
        pass


def _static(parent, text: str, *, name: str = "") -> wx.StaticText:
    """見出し・欄名の文字。**すべてのウィジェットに名前を付ける。**

    例外は作らない。`StaticText` は
    フォーカスが当たらないので読み上げには直接効かないが、
    名前が付いていないと AX のダンプで既定名（`staticText`）になり、
    **付け忘れの調査に使えなくなる。**
    """
    st = wx.StaticText(parent, label=text)
    st.SetName(name or text)
    return st


def _note_names() -> list[str]:
    from core.notes import NOTE_NAMES

    return list(NOTE_NAMES)


def _version_text() -> str:
    """版と、`.app` の Info.plist にあるビルドの日時とコミット。

    **どの `.app` から起動したかは環境変数で受け取る**（`SFZBUILDER_APP`。
    手元の版はランチャが、配布版は `app.py` が渡す）。`__file__` を辿る方法だけでは
    見つからない。ランチャは `.app` の**外**にあるプロジェクトの `app.py` を exec
    するので、`__file__` は常にプロジェクト直下を指し、**`.app` から
    起動しても「ソースから直接起動しています」と答えていた。**
    """
    credit = tr(
        "AI（Anthropic の Claude）を使って作りました。"
        "MIT ライセンス、Copyright (c) 2026 Takahashi。",
        "Made with AI (Anthropic's Claude). MIT License, Copyright (c) 2026 Takahashi.",
    )
    plist = None
    bundle = os.environ.get("SFZBUILDER_APP", "").strip()
    if bundle:
        plist = Path(bundle) / "Contents" / "Info.plist"
    else:
        # ソースを .app の中に置いた場合の保険
        for parent in Path(__file__).resolve().parents:
            if parent.suffix == ".app":
                plist = parent / "Contents" / "Info.plist"
                break
    if plist is None or not plist.is_file():
        return (
            tr(
                f"{APP_NAME} {VERSION}。ソースから直接起動しています。"
                "ビルドの日時を見るには .app から起動してください。",
                f"{APP_NAME} {VERSION}. Running directly from source. To see the build date, "
                "start it from the .app. ",
            ) + credit
        )
    try:
        info = plistlib.loads(plist.read_bytes())
    except Exception:
        return tr(
            f"{APP_NAME} {VERSION}。バージョン情報を読めませんでした。",
            f"{APP_NAME} {VERSION}. The version information could not be read. ",
        ) + credit
    flavor = tr("配布版", "packaged version") if FROZEN else tr("手元の版", "local build")
    return (
        tr(
            f"{APP_NAME} {VERSION}（{flavor}）。"
            f"ビルド {info.get('SFZBuildDate', '不明')}、"
            f"コミット {info.get('SFZGitCommit', '不明')}。",
            f"{APP_NAME} {VERSION} ({flavor}). Build {info.get('SFZBuildDate', 'unknown')}, "
            f"commit {info.get('SFZGitCommit', 'unknown')}. ",
        )
        + credit
    )
