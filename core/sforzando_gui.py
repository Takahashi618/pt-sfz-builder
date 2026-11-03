"""sforzando の画面上の位置。**実測ではなく、プラグイン自身の定義から取っている。**

sforzando（ARIA エンジン）の画面は XML で定義されていて、部品の位置と大きさが
テキストで読める。2026-09-04 に発見。

    /Library/Application Support/Plogue/sforzando/GUI/gui.xml
      <GUI w="774" h="498" ...>
        <FileMenu param="DID_FILENAME" x="90" y="20" w="157" h="19" ... />

**この 774x498 は AX から読める `FXTDMEditView` の大きさと完全に一致する。**

    AXGroup title=FXTDMEditView pos=20,128 size=774,498

つまり XML の座標は描画領域の左上からのオフセットそのもので、**拡大縮小も
オフセットの補正も要らない**。座標をピクセル単位で探し当てる作業が丸ごと消える。

    画面座標 = FXTDMEditView の左上 + XML の座標

座標を描画領域からの比率で持つやり方もあるが、
比率にする必要すらない。**寸法が定義ファイルに書いてあるものは、そこから取る。**

### 版が上がったら座標も変わりうる

ここの定数は v1.982 の gui.xml に由来する。版が変わると動きうるので、
`definition_problems` で実物と突き合わせられるようにしてある。
**食い違ったら、このファイルではなく実物を正とする。**

### 鍵盤の座標は入れていない

`<Keyboard>` には `offset0`〜`offset5` という 6 個の値があり、黒鍵は 5 個しか
無いので**意味が確定できなかった**。推測で書くと、押したつもりの音と違う音が
鳴っても気づけない。鍵盤は MIDI キーボードから弾く前提とし、ここには入れない。

OS 非依存。座標を計算するだけなので Windows でもテストできる。
"""

from __future__ import annotations

from .i18n import tr

import re

from .geometry import Rect


__all__ = [
    "GUI_WIDTH",
    "GUI_HEIGHT",
    "SOURCE_XML",
    "SOURCE_VERSION",
    "Rect",
    "FILE_MENU",
    "PRESET_MENU",
    "TAB_STRIP_Y",
    "ELEMENTS",
    "FILE_MENU_ITEMS",
    "FILE_MENU_ITEM_DX",
    "FILE_MENU_ROW_HEIGHT",
    "to_screen",
    "center_of",
    "file_menu_item_point",
    "definition_problems",
]

# gui.xml の <GUI w= h=>。AX の FXTDMEditView の size と一致すること。
GUI_WIDTH = 774
GUI_HEIGHT = 498

SOURCE_XML = "/Library/Application Support/Plogue/sforzando/GUI/gui.xml"
SOURCE_VERSION = "1982"  # AriaSetup.xml の version


# 読み込み中のファイル名が出ている場所。**ここを押すと読み込みのメニューが出る。**
# SFZ を読ませる唯一の入口なので、案 C で使うのはここ 1 点だけ。
FILE_MENU = Rect(90, 20, 157, 19)

# Pro Tools の Librarian とは別物。ARIA 自身のプリセット選択。
PRESET_MENU = Rect(521, 76, 247, 18)

# 下段のタブ（Info / Controls / FX / Settings）が並ぶ帯の上端。
TAB_STRIP_Y = 78

ELEMENTS: dict[str, Rect] = {
    "file_menu": FILE_MENU,
    "preset_menu": PRESET_MENU,
}


def to_screen(rect: Rect, view_x: int, view_y: int) -> Rect:
    """描画領域の左上（AX の FXTDMEditView の pos）を足して画面座標にする。"""
    return Rect(rect.x + view_x, rect.y + view_y, rect.w, rect.h)


def _attrs(text: str) -> dict[str, str]:
    return dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', text))


def definition_problems(text: str) -> list[str]:
    """gui.xml の中身が、ここの座標の前提と合っているか。**食い違いを返す**（合えば空）。

    **押す前に確かめる。** 配布版はほかの人の Mac で動き、sforzando の版が
    違うことがある。定義が変わっていれば押す位置もずれているので、
    押さずに「版が違う」と言う（違う所を押すより安全）。
    読み込ませる道具が使う。**純粋関数。**
    """
    problems: list[str] = []
    root = re.search(r"<GUI\b([^>]*)>", text or "")
    if root is None:
        return [tr("画面の大きさ（GUI）が書かれていない", "The window size (GUI) is not written")]
    attrs = _attrs(root.group(1))
    try:
        size = (int(attrs.get("w", "0")), int(attrs.get("h", "0")))
    except ValueError:
        size = (0, 0)
    if size != (GUI_WIDTH, GUI_HEIGHT):
        problems.append(
            tr(
                f"描画領域の大きさが違う: {size[0]}x{size[1]}"
                f"（前提は {GUI_WIDTH}x{GUI_HEIGHT}）",
                f"The drawing area has a different size: {size[0]}x{size[1]} (expected "
                f"{GUI_WIDTH}x{GUI_HEIGHT})",
            )
        )
    found = re.search(r'<FileMenu\b[^>]*param="DID_FILENAME"[^>]*>', text)
    if found is None:
        problems.append(tr(
            "ファイル名の欄（DID_FILENAME の FileMenu）が見つからない",
            "The file name field (FileMenu of DID_FILENAME) was not found",
        ))
        return problems
    a = _attrs(found.group(0))
    try:
        actual = (int(a["x"]), int(a["y"]), int(a["w"]), int(a["h"]))
    except (KeyError, ValueError):
        problems.append(tr(
            "ファイル名の欄の位置が読めない",
            "The position of the file name field cannot be read",
        ))
        return problems
    expected = (FILE_MENU.x, FILE_MENU.y, FILE_MENU.w, FILE_MENU.h)
    if actual != expected:
        problems.append(tr(
            f"ファイル名の欄の位置が違う: {actual}（前提は {expected}）",
            f"The file name field is in a different position: {actual} (expected {expected})",
        ))
    return problems


def center_of(name: str, view_x: int, view_y: int) -> tuple[int, int]:
    """部品の中心の画面座標。**押す位置はいつも中心にする。**

    端を押すと、版が上がって数ピクセル動いたときに外れる。
    """
    if name not in ELEMENTS:
        raise KeyError(tr(
            f"知らない部品です: {name}（{', '.join(ELEMENTS)}）",
            f"Unknown element: {name} ({', '.join(ELEMENTS)})",
        ))
    return to_screen(ELEMENTS[name], view_x, view_y).center


# --------------------------------------------------------------------------
# ファイル名欄を押すと出るメニュー
# --------------------------------------------------------------------------
#
# **ここだけは定義ファイルに書かれていない。** gui.xml には <PopupOverlay> が
# あるだけで、項目も位置も書かれていない。2026-09-04 に画面を測って求めた。
#
#   empty       スロットを空にする
#   import      ファイルを選んで読み込む → **macOS 標準の「Please select file」**
#   reload      いま読んでいるファイルを読み直す ← **再読込のトリガー**
#   TableWarp2  サブメニュー（使わない）
#
# import と reload が標準ダイアログを開くので、**そこから先は VoiceOver で完結する。**
#
# 値はクリック位置からの相対。**押す位置を固定すれば、メニューが
# クリック位置に出るのか部品に固定なのかを問わず、同じ値で足りる。**
# 実測は (188, 157) を押したとき。
#
# 測り方（再現できるように残す）:
#   1. sforzando の File メニューを開く
#   2. screencapture -x -R20,25,774,601 で撮る
#   3. 箱の内側だけを見て、明るい画素が並ぶ行を拾う
#      （左隣の INSTRUMENT 欄の文字が混ざるので x の下限を切ること）
#
# **版が上がったら測り直す。** 定義ファイル由来ではないので、
# `definition_problems` では検証できない。

FILE_MENU_ITEM_DX = 30  # 文字は +12〜+48 に出る。中ほどを押す
FILE_MENU_ROW_HEIGHT = 21

FILE_MENU_ITEMS: dict[str, int] = {
    "empty": 12,
    "import": 33,
    "reload": 54,
}


def file_menu_item_point(name: str, click_x: int, click_y: int) -> tuple[int, int]:
    """ファイルメニューの項目を押す画面座標。

    `click_x` / `click_y` は**メニューを開くために押した位置**。
    """
    if name not in FILE_MENU_ITEMS:
        raise KeyError(
            tr(
                f"知らない項目です: {name}（{', '.join(FILE_MENU_ITEMS)}）",
                f"Unknown item: {name} ({', '.join(FILE_MENU_ITEMS)})",
            )
        )
    return click_x + FILE_MENU_ITEM_DX, click_y + FILE_MENU_ITEMS[name]
