"""sforzando_gui.py のテスト。

**座標の正しさそのものは実物の XML と突き合わせて確かめる。**
ここで見るのは計算のほう。
描画領域の左上を足して画面座標にする、その一点。
"""

from _harness import Checker

from core.sforzando_gui import (
    FILE_MENU,
    FILE_MENU_ITEMS,
    FILE_MENU_ROW_HEIGHT,
    GUI_HEIGHT,
    GUI_WIDTH,
    Rect,
    center_of,
    file_menu_item_point,
    to_screen,
)

c = Checker("sforzando_gui")

# 2026-09-04 に AX から採れた FXTDMEditView の実測値。
VIEW_X, VIEW_Y = 20, 128
VIEW_W, VIEW_H = 774, 498

c.equal("描画領域の幅は AX の実測と一致", GUI_WIDTH, VIEW_W)
c.equal("描画領域の高さは AX の実測と一致", GUI_HEIGHT, VIEW_H)

# --- Rect ---
c.equal("中心を出せる", Rect(0, 0, 10, 20).center, (5, 10))
c.equal("奇数でも整数で返す", Rect(0, 0, 7, 7).center, (3, 3))
c.equal("原点がずれていても中心", Rect(100, 200, 10, 20).center, (105, 210))

# --- to_screen ---
moved = to_screen(FILE_MENU, VIEW_X, VIEW_Y)
c.equal("画面座標 x", moved.x, VIEW_X + FILE_MENU.x)
c.equal("画面座標 y", moved.y, VIEW_Y + FILE_MENU.y)
c.equal("大きさは変わらない", (moved.w, moved.h), (FILE_MENU.w, FILE_MENU.h))
c.equal("原点が 0 なら素通し", to_screen(FILE_MENU, 0, 0), FILE_MENU)

# --- center_of ---
point = center_of("file_menu", VIEW_X, VIEW_Y)
c.equal("ファイルメニューの中心", point, (VIEW_X + 90 + 78, VIEW_Y + 20 + 9))
c.equal("実機での押す位置", point, (188, 157))

# **押す点は必ず描画領域の中に入っていること。** 外れていたら座標の取り違え。
px, py = point
c.check("描画領域の中にある x", VIEW_X <= px < VIEW_X + VIEW_W, str(point))
c.check("描画領域の中にある y", VIEW_Y <= py < VIEW_Y + VIEW_H, str(point))

preset = center_of("preset_menu", VIEW_X, VIEW_Y)
px, py = preset
c.check("プリセットメニューも領域内 x", VIEW_X <= px < VIEW_X + VIEW_W, str(preset))
c.check("プリセットメニューも領域内 y", VIEW_Y <= py < VIEW_Y + VIEW_H, str(preset))
c.check("ファイルメニューとは別の場所", preset != point)

c.raises("知らない部品は弾く", KeyError, center_of, "nope", VIEW_X, VIEW_Y)

# 窓を動かしても同じ 1 組の値で足りる、が要点。
c.equal(
    "窓が動いても相対位置は同じ",
    (
        center_of("file_menu", 300, 400)[0] - 300,
        center_of("file_menu", 300, 400)[1] - 400,
    ),
    (point[0] - VIEW_X, point[1] - VIEW_Y),
)

# --- ファイルメニューの項目 ---
# 2026-09-04 に (188, 157) を押して測った実測値。
CLICK = (188, 157)

c.equal("empty の位置", file_menu_item_point("empty", *CLICK), (218, 169))
c.equal("import の位置", file_menu_item_point("import", *CLICK), (218, 190))
c.equal("reload の位置", file_menu_item_point("reload", *CLICK), (218, 211))

c.equal("行の間隔は一定", FILE_MENU_ITEMS["import"] - FILE_MENU_ITEMS["empty"], FILE_MENU_ROW_HEIGHT)
c.equal("次の行も同じ間隔", FILE_MENU_ITEMS["reload"] - FILE_MENU_ITEMS["import"], FILE_MENU_ROW_HEIGHT)

# **項目はクリック位置より下に出る。** 上に出ると解釈が変わる
for name, dy in FILE_MENU_ITEMS.items():
    c.check(f"{name} はクリック位置より下", dy > 0, str(dy))

# 押す位置がずれてもついてくる
c.equal(
    "メニューを開く位置を変えても相対は同じ",
    file_menu_item_point("reload", 300, 400),
    (300 + 30, 400 + 54),
)

c.raises("知らない項目は弾く", KeyError, file_menu_item_point, "nope", 0, 0)

raise SystemExit(c.summary())
