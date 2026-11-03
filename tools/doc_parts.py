"""マニュアルのうち「コードから作る部分」を作り直す。

    python3.14 -X utf8 tools/doc_parts.py
        docs/manual.html と manual_en.html を今のコードに合わせ、txt も作り直す
    python3.14 -X utf8 tools/doc_parts.py --check
        合わせる必要があるかだけ調べる（あれば 1 で終わる。書き換えない）

キーの一覧・メニュー・タブで止まる欄の並び・設定の項目と初めの値は、手で書き写すと
必ずずれる。**本物の窓とメニューと設定の画面を
作って読み**、文書の印の間に差し込む。印は HTML のコメントなので、読み上げにも txt にも出ない:

    <!-- gen:keys -->
    …ここが作り直される…
    <!-- /gen:keys -->

キーの一覧はアプリの「キー操作の一覧」（ui/keys_dialog.py の KEY_HELP）と同じものを載せる。
利用者がアプリの中で聞く文と、マニュアルの文をそろえるため。
版の番号は <span class="version">…</span> と <title> を core/version.py に合わせる。

画面の言語は起動したときに決まるので、言語ごとに別のプロセスで動かす
（`--lang ja` / `--lang en`。付けなければ両方を順に）。Mac の言語によらず、
日本語のマニュアルには日本語の表、英語のマニュアルには英語の表が入る。

★窓は作るが表示しない。Pro Tools にもつながず、索引は空のもの、スロットは一時フォルダ。
★文書にある印を生成側が知らなければ止める（綴り違いの印は、黙って古い中身のまま残る）。
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
# 言語 → (正本の HTML, 作る txt)
MANUALS = {"ja": (DOCS / "manual.html", DOCS / "manual.txt"),
           "en": (DOCS / "manual_en.html", DOCS / "manual_en.txt")}


def _lang_argument() -> str | None:
    """`--lang`（`--lang=en` も）を先に読む。画面の言語は import の前に決める。"""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=sorted(MANUALS))
    return pre.parse_known_args()[0].lang


LANG = _lang_argument() or "ja"
os.environ["SFZBUILDER_LANG"] = LANG
os.environ["SM_SILENT"] = "1"
os.environ["SM_NO_ANNOUNCE"] = "1"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from core.i18n import tr  # noqa: E402
from core.version import BUNDLE_NAME, ENGLISH_NAME, VERSION  # noqa: E402

MARK_RE = re.compile(
    r"(<!-- gen:(?P<name>[a-z_]+) -->)(?P<body>.*?)(<!-- /gen:(?P=name) -->)", re.S
)
VERSION_SPAN_RE = re.compile(r'(<span class="version">)[^<]*(</span>)')
TITLE_RE = tr(re.compile(rf"(<title>{re.escape(BUNDLE_NAME)} マニュアル（)[^）<]*(）)"),
              re.compile(rf"(<title>{re.escape(ENGLISH_NAME)} Manual \()[^)<]*(\))"))

# wx のアクセラレータの書き方 → 読み上げる名前（macOS の wx では Ctrl がコマンド）
KEY_WORDS = tr({"Ctrl": "コマンド", "Shift": "シフト", "Alt": "オプション", "RawCtrl": "コントロール"},
              {"Ctrl": "Command", "RawCtrl": "Control", "Alt": "Option"})


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def key_display(accel: str) -> str:
    return tr("+", "-").join(KEY_WORDS.get(token, token) for token in accel.split("+") if token)


def count_word(n: int) -> str:
    """「3 つ」「11 項目」のように数える（10 以上を「11 つ」としない）。"""
    return f"{n} つ" if n < 10 else f"{n} 項目"


def table(lead: str, head: tuple, rows: list[tuple]) -> str:
    """表の前に「何の表か・何行・どの列か」を段落で言う。

    caption は txt で表のあとに出るので使わない。
    """
    heads = "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
    quoted = [f"“{h}”" for h in head]
    en_cols = ", ".join(quoted[:-1]) + f" and {quoted[-1]}"
    ja_cols = "".join(f"「{h}」" for h in head)
    intro = tr(
        f"{esc(lead)}表は {len(rows)} 行で、列は{ja_cols}の {count_word(len(head))}です。",
        f"{esc(lead)} The table has {len(rows)} rows and {len(head)} columns: {esc(en_cols)}.",
    )
    lines = [
        f"<p>{intro}</p>",
        "<table>",
        f"<thead><tr>{heads}</tr></thead>",
        "<tbody>",
    ]
    lines += ["<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows]
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)


# wx が付ける既定の名前（読み上げ名を付けていない部品）
_WX_DEFAULT_NAMES = {"button", "text", "choice", "check", "listBox", "panel"}


def _ax_label(ctrl) -> str:
    """macOS のアクセシビリティの名前（VoiceOver が読む名前）。取れなければ空。

    **wx の GetName では分からない**（macOS では入力欄に SetName が効かない。
    読み上げ名は借りた `label_control` が下地の NSView に付ける）。
    """
    try:
        import objc

        view = objc.objc_object(c_void_p=ctrl.GetHandle())
        label = view.accessibilityLabel()
    except Exception:
        return ""
    return str(label) if label else ""


def spoken_name(ctrl) -> str:
    """VoiceOver が読む名前の最初の文（「。」まで）。長い説明は表では省く。"""
    name = _ax_label(ctrl) or ctrl.GetName()
    if not name or name in _WX_DEFAULT_NAMES:
        name = ctrl.GetLabel()
    name = re.sub(r"\s*\(&?\w\)$", "", name).replace("&", "")
    return name.split(tr("。", ". "), 1)[0].strip()


def kind_of(ctrl) -> str:
    import wx

    kinds = (
        (wx.TextCtrl, tr("入力欄", "Text field")),
        (wx.Choice, tr("選択肢", "Pop-up menu")),
        (wx.CheckBox, tr("チェック", "Checkbox")),
        (wx.ListBox, tr("一覧", "List")),
        (wx.Button, tr("ボタン", "Button")),
    )
    for cls, label in kinds:
        if isinstance(ctrl, cls):
            return label
    return type(ctrl).__name__


def value_of(ctrl) -> str:
    """設定の画面の初めの値。値を持たない部品は「値なし」と書く（空欄にしない。7 節）。"""
    import wx

    if isinstance(ctrl, wx.CheckBox):
        return tr("入れる", "Checked") if ctrl.GetValue() else tr("外す", "Unchecked")
    if isinstance(ctrl, wx.Choice):
        return ctrl.GetStringSelection() or tr("値なし", "No value")
    if isinstance(ctrl, wx.TextCtrl):
        return ctrl.GetValue() or tr("空欄", "Empty")
    return tr("値なし", "No value")


def focusable(parent) -> list:
    """タブで止まる部品を、止まる順（作った順）に。板（ScrolledWindow）の中まで見る。"""
    import wx

    skip = (wx.StaticText, wx.StaticBox, wx.StaticLine, wx.ScrollBar)
    out = []
    for child in parent.GetChildren():
        if isinstance(child, skip):
            continue
        if isinstance(child, (wx.ScrolledWindow, wx.Panel)) and not isinstance(
            child, (wx.ListBox, wx.Choice)
        ):
            out += focusable(child)
            continue
        if not child.AcceptsFocusFromKeyboard():
            continue
        out.append(child)
    return out


class _EmptyLibrary:
    entries: list = []

    def search(self, **_kwargs):
        return []

    def keys(self):
        return []


def read_ui() -> dict:
    """本物の窓・メニュー・設定の画面を作って読む（窓は出さない）。"""
    import wx

    from core.slots import SlotLayout
    from ui.assign_dialog import AssignDialog
    from ui.controller import AppController, AssignForm
    from ui.keys_dialog import KEY_HELP
    from ui.main_frame import MainFrame

    tmp = Path(tempfile.mkdtemp(prefix="sfz_doc_parts_"))
    app = wx.App(False)
    # アプリと同じ訳語を使う（標準のボタンの文字）
    locale = wx.Locale(tr(wx.LANGUAGE_JAPANESE, wx.LANGUAGE_ENGLISH))
    controller = AppController(
        layout=SlotLayout(slots_dir=str(tmp)),
        library=_EmptyLibrary(),
        target_reader=lambda: (None, "", ""),
    )
    frame = MainFrame(controller)
    try:
        menu_rows = []
        bar = frame.GetMenuBar()
        for i in range(bar.GetMenuCount()):
            for item in bar.GetMenu(i).GetMenuItems():
                if item.IsSeparator():
                    continue
                label, _tab, accel = item.GetItemLabel().partition("\t")
                keys = key_display(accel) if accel else tr("なし（メニューから選ぶ）", "None (choose from the menu)")
                menu_rows.append((bar.GetMenuLabelText(i), label, keys))
        tab_rows = [
            (str(n), spoken_name(c), kind_of(c))
            for n, c in enumerate(focusable(frame._panel), 1)
        ]
        dialog = AssignDialog(frame, AssignForm())
        try:
            setting_rows = [
                (spoken_name(c), kind_of(c), value_of(c)) for c in focusable(dialog)
            ]
        finally:
            dialog.Destroy()
    finally:
        frame.Destroy()
        del locale
        del app
    key_rows = [(place, key, action) for place, key, action in KEY_HELP]
    return {
        "keys": key_rows,
        "menus": menu_rows,
        "tabs": tab_rows,
        "settings": setting_rows,
    }


def build_parts(ui: dict) -> dict[str, str]:
    return {
        "keys": table(
            tr("アプリの中の「キー操作の一覧」（コマンド+シフト+K）と同じものです。",
               "This is the same as the Keyboard Commands list in the app (Command-Shift-K)."),
            tr(("場所", "キー", "動作"), ("Where", "Key", "What it does")),
            ui["keys"],
        ),
        "menus": table(
            tr("メニューバーの項目です。VO+M でメニューバーへ移り、左右の矢印でメニューを選びます。"
               "キーのある項目は、どの欄にいてもそのキーで使えます。",
               "These are the items in the menu bar. Press VO-M to move to the menu bar, and use the Left "
               "and Right arrows to choose a menu. Items with a key work with that key from any field."),
            tr(("メニュー", "項目", "キー"), ("Menu", "Item", "Key")),
            ui["menus"],
        ),
        "tabs": table(
            tr("主画面でタブを押したときに止まる場所を、止まる順に並べました。"
               "名前は VoiceOver が読む名前の最初の文です。シフト+タブで逆の順に戻ります。",
               "These are the places Tab stops in the main window, in order. The name is the first sentence "
               "of what VoiceOver reads. Shift-Tab goes back in reverse order."),
            tr(("順", "読み上げられる名前", "種類"), ("Order", "Spoken name", "Kind")),
            ui["tabs"],
        ),
        "settings": table(
            tr("コマンド+S の「割り当ての設定」の画面に並ぶ項目です。"
               "タブで止まる順に、VoiceOver が読む名前の最初の文と、"
               "アプリを初めて開いたときの値を書きました。",
               "These are the items in the Assign Settings window (Command-S), in Tab order, with the first "
               "sentence of what VoiceOver reads and the value when the app is first opened."),
            tr(("読み上げられる名前", "種類", "初めの値"), ("Spoken name", "Kind", "Initial value")),
            ui["settings"],
        ),
    }


def apply(text: str, parts: dict[str, str]) -> str:
    names = {m.group("name") for m in MARK_RE.finditer(text)}
    unknown = names - set(parts)
    if unknown:
        raise SystemExit(f"[エラー] 生成側が知らない印があります: {sorted(unknown)}")
    missing = set(parts) - names
    if missing:
        raise SystemExit(f"[エラー] 文書に印がありません: {sorted(missing)}")

    def fill(m) -> str:
        return f"{m.group(1)}\n{parts[m.group('name')]}\n{m.group(4)}"

    text = MARK_RE.sub(fill, text)
    text = VERSION_SPAN_RE.sub(lambda m: f"{m.group(1)}{VERSION}{m.group(2)}", text)
    return TITLE_RE.sub(lambda m: f"{m.group(1)}{VERSION}{m.group(2)}", text)


def txt_of(html_text: str) -> str:
    from html_to_txt import DocumentToText

    parser = DocumentToText()
    parser.feed(html_text)
    return parser.render()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="マニュアルのうちコードから作る部分を作り直す")
    ap.add_argument("--check", action="store_true", help="書き換えずに、古いかどうかだけ調べる")
    ap.add_argument("--lang", choices=sorted(MANUALS), help="1 つの言語だけ（付けなければ両方）")
    args = ap.parse_args(argv)
    if args.lang is None:
        # 言語は起動したときに決まるので、言語ごとに別のプロセスで動かす
        extra = ["--check"] if args.check else []
        codes = [
            subprocess.run([sys.executable, "-X", "utf8", __file__, "--lang", lang] + extra, cwd=ROOT).returncode
            for lang in MANUALS
        ]
        return max(codes)
    manual, manual_txt = MANUALS[LANG]
    source = manual.read_text(encoding="utf-8")
    new = apply(source, build_parts(read_ui()))
    new_txt = txt_of(new)
    old_txt = manual_txt.read_text(encoding="utf-8-sig") if manual_txt.is_file() else ""
    stale = new != source or new_txt.replace("\r\n", "\n") != old_txt.replace("\r\n", "\n")
    if args.check:
        print(
            f"マニュアル（{LANG}）は古いです。tools/doc_parts.py で作り直してください"
            if stale
            else f"マニュアル（{LANG}）は今のコードと合っています"
        )
        return 1 if stale else 0
    manual.write_text(new, encoding="utf-8")
    manual_txt.write_text(new_txt, encoding="utf-8-sig", newline="\r\n")
    print(f"作り直しました: {manual.name}（{len(new)} 字）、{manual_txt.name}（{len(new_txt)} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
