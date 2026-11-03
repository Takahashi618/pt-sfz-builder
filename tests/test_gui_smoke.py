"""画面の回帰テスト。**耳で確かめる前に、機械で見つけられるものを見る。**

見るのは 3 つ。

1. **フォーカスの当たる部品に読み上げ名が付いているか。**
   wxWidgets の既定名（`button` `listBox` …）が残っていれば付け忘れ
2. **潰れている部品が無いか。** 入りきらない欄を sizer が高さ 0 にする。
   潰れた欄はフォーカスも通り名前も読むが、**値だけ読まれない**
3. 押したときに落ちないか（スタブを注入して全経路）

**文字の大きさを変えて回す。** どこから潰れるかは文字の大きさで動くので、
1 つの大きさだけ見ても取りこぼす。

固まらないように守っていること。

- `wx.App` は**1 プロセスに 1 つだけ**。作り直すと 2 つめで固まる
- 後始末は `frame.Destroy()` だけ。`app.Destroy()` は呼ばない
- **モーダルを開く操作は呼ばない**。`ShowModal()` は入力を待つので返らない
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import wx

from _harness import Checker

from core.slots import PluginKind, SlotLayout, SlotLedger
from core.target import PluginTarget
from integration.reloader import NullReload
from integration.service import AssignService
from core.mapping import MODE_PHRASE
from ui.controller import MODE_AUTO, AppController, AssignForm, Outcome
from ui.main_frame import MainFrame
from core.version import VERSION

c = Checker("gui_smoke")

FOCUSABLE = (wx.Button, wx.ListBox, wx.Choice, wx.TextCtrl, wx.CheckBox)
WX_DEFAULT_NAMES = {"button", "listBox", "choice", "staticText", "text", "check", ""}
FONT_SIZES = (9, 11, 14, 18)

_APP = None


def app():
    """**1 プロセスに 1 つだけ。** 作り直すと 2 つめで固まる。"""
    global _APP
    if _APP is None:
        _APP = wx.App(False)
    return _APP


class FakeEntry:
    def __init__(self, path: str, text: str, kind: str = "one_shot") -> None:
        self.path = path
        self.text = text
        self.kind = kind

    def summary(self) -> str:
        return self.text


class FakePlayer:
    """**音は出さない。** 呼ばれたことだけ分かればよい。"""

    def __init__(self) -> None:
        self.current_path = None
        self.calls: list[str] = []

    def load(self, path):
        self.current_path = str(path)
        self.calls.append("load")

    def play(self):
        self.calls.append("play")

    def stop(self):
        self.calls.append("stop")

    def toggle_play_stop(self):
        self.calls.append("toggle")

    def describe_state_ja(self):
        return "試聴中"

    def describe_state_en(self):
        return "playing"


class FakeLibrary:
    def search(self, **kwargs):
        return [
            FakeEntry("/tmp/a.wav", "ギター、120 BPM", kind="loop"),
            FakeEntry("/tmp/b.wav", "ドラム"),
        ]

    def packs(self):
        return ["Pack A", "Pack B"]

    def keys(self):
        return ["C", "Am"]


def make_controller(tmp: str) -> AppController:
    layout = SlotLayout(slots_dir=tmp)
    service = AssignService(
        SlotLedger.create(layout, [PluginKind.SFORZANDO]), NullReload()
    )
    return AppController(
        layout=layout,
        library=FakeLibrary(),
        target_reader=lambda: (
            PluginTarget(plugin=PluginKind.SFORZANDO, track_name="Inst1"),
            "トラック「Inst1」のスフォルツァンド",
            "",  # セッション名（テストでは差し替えたサービスを使うので空）
        ),
        plugin_loader=lambda path, track: Outcome(True, "読み込ませました。"),
        service=service,
        player=FakePlayer(),
    )


def walk(window):
    for child in window.GetChildren():
        yield child
        yield from walk(child)


def apply_font(frame, point_size: int) -> None:
    font = wx.Font(
        point_size,
        wx.FONTFAMILY_DEFAULT,
        wx.FONTSTYLE_NORMAL,
        wx.FONTWEIGHT_NORMAL,
    )
    for widget in [frame, *walk(frame)]:
        try:
            widget.SetFont(font)
        except Exception:
            pass
    frame.Layout()
    for widget in walk(frame):
        if isinstance(widget, wx.ScrolledWindow):
            widget.FitInside()
    wx.Yield()


app()

import ui.main_frame as mf

# **利用者のクリップボードに触らない。** 差し替えずに回していたときは、
# ビルドのたびにクリップボードが `/tmp/a.wav` に書き換わっていた。
copied: list[str] = []
mf._set_clipboard_text = lambda text: copied.append(text) or True

with tempfile.TemporaryDirectory() as tmp:
    frame = MainFrame(make_controller(tmp))
    # **モーダルを開く操作は差し替える。** 入力を待って返らない
    # （バージョン情報を画面にしたとき、テストごと止まった）。
    shown: list[tuple[str, str]] = []
    frame._show_info = lambda title, text: shown.append((title, text))
    keys_opened: list[bool] = []
    frame._show_keys = lambda: keys_opened.append(True)
    frame.Show()
    wx.Yield()

    # ======================================================================
    # 1. 読み上げ名
    # ======================================================================

    unnamed: list[str] = []
    focusable_count = 0
    for widget in walk(frame):
        if not isinstance(widget, FOCUSABLE):
            continue
        focusable_count += 1
        name = (widget.GetName() or "").strip()
        if name in WX_DEFAULT_NAMES:
            unnamed.append(f"{type(widget).__name__}: {name!r}")
    c.check("フォーカスの当たる部品がある", focusable_count >= 10, str(focusable_count))
    c.check("読み上げ名の付け忘れが無い", not unnamed, "、".join(unnamed))

    # ======================================================================
    # 2. 潰れている部品が無いか（文字の大きさを変えて回す）
    # ======================================================================

    for size in FONT_SIZES:
        apply_font(frame, size)
        collapsed = [
            f"{type(w).__name__}({w.GetName()})"
            for w in walk(frame)
            if isinstance(w, FOCUSABLE) and w.GetSize().height <= 1
        ]
        c.check(f"{size} ポイントで潰れが無い", not collapsed, "、".join(collapsed))

    # 窓を縮めても潰れないこと。**利用者は窓を縮められる。**
    apply_font(frame, 14)
    for height in (700, 420, 260):
        frame.SetSize((640, height))
        frame.Layout()
        wx.Yield()
        collapsed = [
            f"{type(w).__name__}({w.GetName()})"
            for w in walk(frame)
            if isinstance(w, FOCUSABLE) and w.GetSize().height <= 1
        ]
        c.check(f"高さ {height} でも潰れが無い", not collapsed, "、".join(collapsed))

    # ======================================================================
    # 3. メニューバー（macOS では必ず要る）
    # ======================================================================

    bar = frame.GetMenuBar()
    c.check("メニューバーがある", bar is not None)
    if bar is not None:
        titles = [bar.GetMenuLabel(i) for i in range(bar.GetMenuCount())]
        c.check("操作メニュー", "操作" in titles, str(titles))
        c.check("ヘルプメニュー", "ヘルプ" in titles, str(titles))

        # **ショートカットには必ず修飾キーを付ける。** 修飾なしの文字キーを
        # 割り当てると、一覧で頭文字を打って飛ぶ操作が使えなくなる。
        bare = []
        for i in range(bar.GetMenuCount()):
            for item in bar.GetMenu(i).GetMenuItems():
                text = item.GetItemLabel()
                if "\t" not in text:
                    continue
                accel = text.split("\t", 1)[1]
                if not any(m in accel for m in ("Ctrl", "Cmd", "Alt", "Shift")):
                    bare.append(text)
        c.check("修飾なしのショートカットが無い", not bare, "、".join(bare))

        # 作者の別のアプリと揃っているか。**同じキーが同じ意味を持つこと。**
        accels = {}
        for i in range(bar.GetMenuCount()):
            for item in bar.GetMenu(i).GetMenuItems():
                text = item.GetItemLabel()
                if "\t" in text:
                    name, accel = text.split("\t", 1)
                    accels[accel] = name
        # **`Cmd+L` は使わない。** macOS と競合する（作者の別のアプリが実測）。
        c.check("Ctrl+L を使っていない", "Ctrl+L" not in accels, str(accels))
        for accel, expect in (
            ("Ctrl+S", "設定"),
            ("Ctrl+R", "索引"),
            ("Ctrl+T", "割り当て先"),
            ("Ctrl+C", "パス"),
            ("Ctrl+I", "一覧"),          # 作者の別のアプリの「リストへ」と同じ
            ("Ctrl+Shift+L", "スロット"),
        ):
            c.check(
                f"{accel} が割り当ててある",
                any(expect in name for a, name in accels.items() if a == accel),
                str(accels),
            )

    # ======================================================================
    # 4. 押しても落ちない（**モーダルを開く操作は呼ばない**）
    # ======================================================================

    frame._on_search(None)
    wx.Yield()
    c.equal("検索結果が並ぶ", frame._results.GetCount(), 2)
    c.equal("先頭が選ばれる", frame._results.GetSelection(), 0)
    c.check("結果を読み上げる", "件" in frame._status.GetLabel(), frame._status.GetLabel())

    # --- 配置は割り当てるその場で決まる ---
    #
    # **一覧の選び直しの副作用にしない。** `SetSelection` は
    # `EVT_LISTBOX` を出さないので、検索直後の先頭の項目
    # （いちばん押される経路）に効かなかった。
    c.equal("既定は素材に合わせる", frame.form.mode, MODE_AUTO)
    c.check(
        "設定ボタンにも出る",
        "素材に合わせる" in frame._settings_btn.GetName(),
        frame._settings_btn.GetName(),
    )
    frame._select_result(0)  # 0 番はループ
    wx.Yield()
    c.check("ループでは下ごしらえが要る", frame.controller.will_render(
        [frame._selected_path()], frame.form
    ))
    frame._select_result(1)  # 1 番はワンショット
    wx.Yield()
    c.check("ワンショットでは要らない", not frame.controller.will_render(
        [frame._selected_path()], frame.form
    ))

    # --- 読み込ませる操作は UI を止めない ---
    #
    # 実測で 11 秒かかる。UI のスレッドで走らせると、その間キー入力も
    # 読み上げも止まり、画面を見ない利用者には「固まった」としか
    # 分からない（2026-09-05 のレビューで実測）。
    frame.controller.last_written = "/tmp/slot01.sfz"
    frame._on_load(None)
    c.check("押した直後に戻ってくる", frame._loading)
    c.check(
        "待つことを先に伝える",
        "10秒ほど" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    c.check("押している間はボタンを止める", not frame._load_btn.IsEnabled())
    # 二重に押させない
    frame._on_load(None)
    c.check(
        "二重押しを断る",
        "お待ちください" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    for _ in range(100):
        wx.Yield()
        if not frame._loading:
            break
        time.sleep(0.01)
    c.check("いずれ終わる", not frame._loading)
    c.check(
        "結果を読み上げる",
        frame._status.GetLabel() != "",
        frame._status.GetLabel(),
    )

    # --- バージョン情報は .app を見つけられる ---
    #
    # **ランチャは `.app` の外の `app.py` を exec する。** `__file__` を
    # 辿っても `.app` に行き着かないので、環境変数で受け取る。
    # 辿るだけだったときは、`.app` から起動しても常に
    # 「ソースから直接起動しています」と答えていた。
    import os

    saved = os.environ.pop("SFZBUILDER_APP", None)
    try:
        c.check(
            "環境変数が無ければソース起動と言う",
            "ソースから" in mf._version_text(),
            mf._version_text(),
        )
        bundle = Path(tmp) / "テスト.app"
        (bundle / "Contents").mkdir(parents=True)
        import plistlib

        (bundle / "Contents" / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "SFZBuildDate": "2026-09-05 12:00",
                    "SFZGitCommit": "abc1234",
                }
            )
        )
        os.environ["SFZBUILDER_APP"] = str(bundle)
        text = mf._version_text()
        c.check("ビルド日時を読む", "2026-09-05 12:00" in text, text)
        c.check("コミットも読む", "abc1234" in text, text)
    finally:
        os.environ.pop("SFZBUILDER_APP", None)
        if saved is not None:
            os.environ["SFZBUILDER_APP"] = saved

    # --- `&` を消さない ---
    #
    # **`SetLabel` は `&` を飾りの印として消す。** 名前に `&` のある素材やトラック、
    # 英語の許可の案内（Privacy & Security）で、読み上げに `&` が抜けていた。
    frame._report("Drum & Bass.wav", sound=False)
    c.equal("状態の表示で & が消えない", frame._status.GetLabelText(), "Drum & Bass.wav")
    real_detect = frame.controller.detect_target
    frame.controller.detect_target = lambda: Outcome(True, "トラック「R&B」")
    try:
        frame._refresh_target(announce_it=False)
    finally:
        frame.controller.detect_target = real_detect
    c.check("割り当て先のボタンで & が消えない", "R&B" in frame._target_btn.GetLabelText(), frame._target_btn.GetLabelText())

    # --- 効果音は成否に従う ---
    #
    # **文言の接頭辞だけで判断していたときは、失敗で成功音が鳴っていた。**
    # この app の失敗文言には `[エラー]` / `[警告]` が付かないものが多い
    # （「合う素材はありませんでした」など）。読み上げ利用者にとって
    # 音は最初の合図なので、逆になっていると気づけない。
    played: list[str] = []
    real_play, real_play_for = mf.play_sound, mf.play_sound_for
    mf.play_sound = lambda kind: played.append(kind)
    mf.play_sound_for = lambda msg: played.append("guessed")
    try:
        played.clear()
        frame._report(Outcome(False, "語「zzz」 に合う素材はありませんでした。"))
        c.equal("失敗なら失敗音", played, ["failure"])

        played.clear()
        frame._report(Outcome(True, "3 件見つかりました。"))
        c.equal("成功なら成功音", played, ["success"])

        played.clear()
        frame._report("[エラー] 何かおかしい", ok=False)
        c.equal("接頭辞があっても成否が優先", played, ["failure"])

        played.clear()
        frame._report("ただの通知", sound=False)
        c.equal("音を止められる", played, [])
    finally:
        mf.play_sound, mf.play_sound_for = real_play, real_play_for

    # --- パスをコピー（Cmd+C）---
    frame._results.SetSelection(0)
    frame._focused = lambda: frame._results
    frame._on_copy(None)
    wx.Yield()
    c.check(
        "コピーしたと言う",
        "コピー" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    c.equal("選んだ素材のパスを写す", copied, ["/tmp/a.wav"])

    # **文字入力欄では、選んだ文字のコピー。** メニューの Cmd+C が欄より先に
    # 受けるので、以前は欄の中でもパスをコピーしようとし、文字が写らなかった
    # （2026-10-25 に実物の窓で確かめた）。
    #
    # **本物の欄でコピーさせない**（利用者のクリップボードに写ってしまう）。
    # 欄のコピーを数えるだけの入力欄で確かめる。実物の窓で写ることは
    # 2026-10-25 に確かめた。
    class CountingText(wx.TextCtrl):
        def __init__(self, parent):
            super().__init__(parent)
            self.copies = 0

        def CanCopy(self):
            return True

        def Copy(self):
            self.copies += 1

    counting = CountingText(frame._panel)
    counting.Hide()
    copied.clear()
    frame._status.SetLabel("")
    frame._focused = lambda: counting
    frame._on_copy(None)
    wx.Yield()
    c.equal("入力欄では欄のコピーにする", counting.copies, 1)
    c.equal("入力欄ではパスを写さない", copied, [])
    c.check(
        "入力欄では「素材を選んで」と言わない",
        "選んでください" not in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    counting.Destroy()
    frame._focused = lambda: frame._results
    frame._results.SetSelection(wx.NOT_FOUND)
    frame._on_copy(None)
    wx.Yield()
    c.check("選んでいなければ促す", "選んでください" in frame._status.GetLabel())

    # --- バージョン情報（画面に出す）---
    frame._on_version(None)
    wx.Yield()
    c.check("何か答える", frame._status.GetLabel() != "", frame._status.GetLabel())
    c.equal("画面に出す", [title for title, _ in shown], ["バージョン情報"])
    c.check("版を言う", any(VERSION in text for _, text in shown), str(shown))
    c.check("AI で作ったことを言う", any("Claude" in text for _, text in shown), str(shown))

    # --- 試聴（スペース）---
    frame._results.SetSelection(0)
    frame._on_preview(None)
    wx.Yield()
    c.check(
        "試聴の結果を読み上げる",
        frame._status.GetLabel() != "",
        frame._status.GetLabel(),
    )

    frame._on_detect(None)
    wx.Yield()
    c.check(
        "割り当て先がボタンの名前に入る",
        "Inst1" in frame._target_btn.GetName(),
        frame._target_btn.GetName(),
    )
    c.check(
        "ラベルも同じ",
        frame._target_btn.GetLabel() == frame._target_btn.GetName(),
    )

    # **ワンショットを選んで「素材に合わせる」のまま実行する。**
    # 既定の経路をそのまま通す（ループだと ffmpeg が要る）。
    frame._select_result(1)
    frame._on_assign(None)
    wx.Yield()
    c.check(
        "割り当ての結果を読み上げる",
        "割り当てました" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    c.check(
        "どの配置にしたかも言う",
        "鍵盤全体に広げる" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    c.check("書いた先を覚えている", frame.controller.last_written is not None)

    # 何も選ばずに割り当てると、選ぶよう促す
    frame._results.SetSelection(wx.NOT_FOUND)
    frame._on_assign(None)
    wx.Yield()
    c.check(
        "選んでいなければ促す",
        "選んでください" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )

    # **モーダルを開かせない。** confirm=False で通す。
    # 消すのは「使っていない」と読み上げた一覧だけ（数え直さない）。
    frame._on_clean(None, confirm=False)
    wx.Yield()
    c.check(
        "片付けの結果を読み上げる",
        frame._status.GetLabel() != "",
        frame._status.GetLabel(),
    )

    # --- 一覧へ移動と、選択の復帰 ---
    # **選択が無いとスペースも上下も効かない。** 利用者からは
    # 「操作できない」に見える（作者の別のアプリで同じ不具合があった）。
    frame._results.SetSelection(wx.NOT_FOUND)
    frame._on_focus_list(None)
    wx.Yield()
    c.equal("一覧へ移ると先頭が選ばれる", frame._results.GetSelection(), 0)

    frame._results.SetSelection(wx.NOT_FOUND)
    frame._ensure_list_selection()
    c.equal("選択が無ければ戻す", frame._results.GetSelection(), 0)
    frame._results.SetSelection(1)
    frame._ensure_list_selection()
    c.equal("選択があれば変えない", frame._results.GetSelection(), 1)

    frame._on_slots(None)
    wx.Yield()
    c.check(
        "スロットの一覧を読み上げる",
        "スロット" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )

    frame._on_keys(None)
    wx.Yield()
    c.equal("キー操作の一覧を画面で開く", keys_opened, [True])
    c.check("閉じたら言う", "閉じました" in frame._status.GetLabel(), frame._status.GetLabel())

    # ======================================================================
    # 4-b. 読み上げの間合い（2026-10-25 のレビュー）
    # ======================================================================
    #
    # 能動読み上げは 10-24 に借り先が直るまで届いていなかった。届くように
    # なったので、ほかのアプリが実機で詰めた約束を入れた。

    spoken: list[str] = []
    real_announce = mf.announce
    mf.announce = lambda message: spoken.append(message)
    try:
        # **メニューのキーで動いた結果は、押してから 800 ミリ秒あける。**
        # VoiceOver はまずメニューの項目名を読むので、すぐ読ませるとぶつかる。
        c.equal("メニューでなければ待たない", frame._menu_wait_ms(), 0)
        frame._from_menu(lambda e: frame._report("メニューの結果", sound=False))(None)
        c.equal("メニューの結果はすぐには読まない", spoken, [])
        for _ in range(150):
            wx.Yield()
            if spoken:
                break
            time.sleep(0.01)
        c.equal("あけてから読む", spoken, ["メニューの結果"])
        c.equal("メニューの印は残さない", frame._menu_at, None)

        # **新しい読み上げが来たら、待っている古いものは読まない。**
        spoken.clear()
        frame._report("古い知らせ", sound=False, delay_ms=150)
        frame._report("新しい知らせ", sound=False)
        for _ in range(40):
            wx.Yield()
            time.sleep(0.01)
        c.equal("古いものは読まない", spoken, ["新しい知らせ"])

        # **前に戻すのは、読み上げを届けるため。** 読み上げを止めてある
        # テストとビルドでは、フォーカスを奪わない。
        activated: list[bool] = []
        real_activate = mf._activate_self
        mf._activate_self = lambda w: activated.append(True)
        try:
            spoken.clear()
            frame._report("読み込ませました。", ok=True, front=True)
            c.equal("読み上げを止めてあれば前に出さない", activated, [])
            c.equal("読み上げそのものは呼ぶ（止めるのは借り先）", spoken, ["読み込ませました。"])
        finally:
            mf._activate_self = real_activate
    finally:
        mf.announce = real_announce

    # **割り当ては二重に始めない。** 下ごしらえの間に Enter をもう一度押すと、
    # 同じ割り当てを 2 回していた（`wx.Yield()` の中で入れ子に走る）。
    frame._select_result(1)
    frame._assigning = True
    frame._on_assign(None)
    c.check(
        "割り当て中は断る",
        "いま割り当てています" in frame._status.GetLabel(),
        frame._status.GetLabel(),
    )
    frame._assigning = False

    # **消すものが無ければ聞かない。** 文言の言い回しで判断していたときは、
    # 言い方が変わると「消してよいですか」と聞く道があった。
    asked: list[str] = []
    real_box = mf.wx.MessageBox
    mf.wx.MessageBox = lambda *a, **k: asked.append(a[0]) or wx.NO
    try:
        frame._on_clean(None)
        wx.Yield()
        c.equal("無いものは消してよいか聞かない", asked, [])
    finally:
        mf.wx.MessageBox = real_box

    # --- キー操作の一覧とメニューが食い違わない ---
    #
    # **利用者は説明を信じて操作する。** メニューのキーを足したり変えたりして、
    # 一覧だけ古いままだと実害が大きい。
    from ui.keys_dialog import KEY_HELP, KeysDialog, key_rows

    words = {"Ctrl": "コマンド", "Shift": "シフト", "Alt": "オプション"}
    menu_keys = set()
    for i in range(bar.GetMenuCount()):
        for item in bar.GetMenu(i).GetMenuItems():
            label = item.GetItemLabel()
            if "\t" in label:
                accel = label.split("\t", 1)[1]
                menu_keys.add("+".join(words.get(k, k) for k in accel.split("+")))
    help_keys = {key for _, key, _ in KEY_HELP}
    c.check(
        "メニューのキーは全部一覧にある",
        menu_keys <= help_keys,
        "一覧に無い: " + "、".join(sorted(menu_keys - help_keys)),
    )
    global_keys = {key for place, key, _ in KEY_HELP if place == "全体" and key.startswith("コマンド")}
    c.check(
        "一覧の「全体」のキーは全部メニューにある",
        global_keys <= menu_keys,
        "メニューに無い: " + "、".join(sorted(global_keys - menu_keys)),
    )
    c.equal("一覧の行は 1 項目 1 行", len(key_rows()), len(KEY_HELP))
    c.check("場所から言う", key_rows()[0].startswith("検索語の欄で"), key_rows()[0])

    # 一覧の画面そのもの（開くだけ。ShowModal は呼ばない）
    keys = KeysDialog(frame)
    wx.Yield()
    keys_list = [w for w in walk(keys) if isinstance(w, wx.ListBox)]
    c.equal("一覧が 1 つある", len(keys_list), 1)
    if keys_list:
        c.equal("全部の行が並ぶ", keys_list[0].GetCount(), len(KEY_HELP))
        c.equal("先頭が選ばれている", keys_list[0].GetSelection(), 0)
    unnamed = [
        f"{type(w).__name__}: {w.GetName()!r}"
        for w in walk(keys)
        if isinstance(w, FOCUSABLE) and (w.GetName() or "").strip() in WX_DEFAULT_NAMES
    ]
    c.check("一覧の画面にも名前が付いている", not unnamed, "、".join(unnamed))
    keys.Destroy()
    wx.Yield()

    # ======================================================================
    # 5. 大きさを決め打ちしていない
    # ======================================================================

    area = wx.Display(0).GetClientArea()
    size = frame.GetSize()
    c.check("画面の作業領域に収まる", size.height <= area.height, f"{size} / {area}")
    c.check("最小の大きさが決まっている", frame.GetMinSize().height > 0)

    # ======================================================================
    # 6. 割り当ての設定ダイアログ（Cmd+S）
    # ======================================================================
    #
    # **`ShowModal` は呼ばない。** 入力を待つのでテストが返らない。
    # 組み立てと値の受け渡しだけ見る。

    from ui.assign_dialog import SPANS, AssignDialog

    original = AssignForm(
        mode=MODE_PHRASE,
        root_key="F",
        octave=4,
        tone_preset="こもらせる",
        phrase_span=24,
        target_bpm="128",
    )
    dialog = AssignDialog(frame, original)
    wx.Yield()

    # 読み上げ名の付け忘れ
    unnamed = [
        f"{type(w).__name__}: {w.GetName()!r}"
        for w in walk(dialog)
        if isinstance(w, FOCUSABLE) and (w.GetName() or "").strip() in WX_DEFAULT_NAMES
    ]
    c.check("ダイアログにも名前が付いている", not unnamed, "、".join(unnamed))

    # 潰れが無いか。**文字の大きさを変えて回す。**
    for size in FONT_SIZES:
        apply_font(dialog, size)
        collapsed = [
            f"{type(w).__name__}({w.GetName()})"
            for w in walk(dialog)
            if isinstance(w, FOCUSABLE) and w.GetSize().height <= 1
        ]
        c.check(f"ダイアログ {size} ポイントで潰れ無し", not collapsed, "、".join(collapsed))

    # **渡した設定がそのまま戻ること。** 開いて閉じただけで値が変わると、
    # 気づかないうちに別の音が載る。
    #
    # **文字の大きさを変えたダイアログでは調べない。** macOS では
    # `SetFont` が `wx.Choice` の選択を外すので、上で回した個体は使えない。
    # 実運用で文字の大きさが実行中に変わることは無い。
    dialog.Destroy()
    wx.Yield()
    dialog = AssignDialog(frame, original)
    wx.Yield()
    got = dialog.result()
    c.equal("配置が保たれる", got.mode, original.mode)
    c.equal("ルートキーが保たれる", got.root_key, original.root_key)
    c.equal("オクターブが保たれる", got.octave, original.octave)
    c.equal("音作りが保たれる", got.tone_preset, original.tone_preset)
    c.equal("範囲が保たれる", got.phrase_span, original.phrase_span)
    c.equal("テンポが保たれる", got.target_bpm, original.target_bpm)

    # 決定と取り消しのボタンが日本語になっている
    ok_btn = dialog.FindWindow(wx.ID_OK)
    cancel_btn = dialog.FindWindow(wx.ID_CANCEL)
    c.check("決定ボタンがある", isinstance(ok_btn, wx.Button))
    c.check("取り消しボタンがある", isinstance(cancel_btn, wx.Button))
    if isinstance(ok_btn, wx.Button):
        c.equal("決定は日本語", ok_btn.GetLabel(), "決定")
    if isinstance(cancel_btn, wx.Button):
        c.equal("取り消しも日本語", cancel_btn.GetLabel(), "取り消し")

    c.equal("範囲の選択肢は 3 つ", len(SPANS), 3)
    dialog.Destroy()
    wx.Yield()

    frame.Destroy()
    wx.Yield()

raise SystemExit(c.summary())
