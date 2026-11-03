"""合成マウス。**プラグインの描画領域を押すための最小限の道具。**

sforzando の画面は AX に出ないので、押すには座標を撃つしかない。
座標そのものは推測ではなく、プラグインの定義 XML から取れている
（`core/sforzando_gui.py`）。ここは「その点を安全に押す」だけを受け持つ。

守っていること:

- **滑らかに動かす。** カーソルを瞬間移動させてクリックすると、
  ホバー状態を経ないプラグインは無反応になる（UVI などの JUCE 系で実証済み）。
  ARIA が同じかは不明だが、滑らかに動かして損はない
- **押す前に矩形の中か確かめる。** 座標を検証せずに撃つと、
  窓の外や別のアプリを押してしまう。**外れていたら撃たずに失敗を返す**
- **カーソルを元の位置へ戻す。** 利用者のポインタが飛んだままにしない
- ダブルクリックは clickState を 1→2 で送る（速い 2 連打とは別物）

macOS 専用。Quartz（pyobjc）を使うが、**import では落とさない**。
Windows でも型として扱えないとテストが書けなくなるため。
"""

from __future__ import annotations

from core.i18n import tr

import sys
import time
from dataclasses import dataclass

from core.geometry import Rect

__all__ = [
    "ClickResult",
    "Rect",
    "available",
    "cursor_position",
    "click",
]

# 滑らかな移動の刻み。細かすぎても遅いだけなので、この程度で足りる。
MOVE_STEPS = 24
MOVE_INTERVAL_SEC = 0.006
SETTLE_SEC = 0.08  # 移動してからボタンを下ろすまでの間


@dataclass(frozen=True)
class ClickResult:
    ok: bool
    message_ja: str
    point: tuple[int, int] | None = None


def available() -> bool:
    """この環境で合成マウスが使えるか。"""
    if sys.platform != "darwin":
        return False
    try:
        import Quartz  # noqa: F401
    except ImportError:
        return False
    return True


def cursor_position() -> tuple[float, float] | None:
    """今のカーソル位置。取れなければ None。"""
    if not available():
        return None
    import Quartz

    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return float(point.x), float(point.y)


def _post(event) -> None:
    import Quartz

    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _move_to(x: float, y: float) -> None:
    import Quartz

    _post(
        Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft
        )
    )


def _move_smooth(x: float, y: float) -> None:
    """今の位置から目標まで、少しずつ動かす。**瞬間移動しない。**"""
    start = cursor_position()
    if start is None:
        _move_to(x, y)
        return
    sx, sy = start
    for step in range(1, MOVE_STEPS + 1):
        ratio = step / MOVE_STEPS
        _move_to(sx + (x - sx) * ratio, sy + (y - sy) * ratio)
        time.sleep(MOVE_INTERVAL_SEC)


def click(
    x: int,
    y: int,
    *,
    allowed: Rect | None = None,
    count: int = 1,
    restore_cursor: bool = True,
) -> ClickResult:
    """(x, y) を押す。**allowed の外なら撃たずに失敗を返す。**

    `count=2` でダブルクリック。clickState を 1→2 で送るので、
    速いシングルクリック 2 回とは区別される。
    """
    if not available():
        return ClickResult(False, tr(
            "合成マウスはこの環境では使えません（macOS 専用）",
            "The synthetic mouse is not available here (macOS only)",
        ))
    if allowed is not None and not allowed.contains(x, y):
        return ClickResult(
            False,
            tr(
                f"({x}, {y}) は押してよい範囲の外です。撃ちませんでした。",
                f"({x}, {y}) is outside the allowed area. Nothing was pressed.",
            ),
            (x, y),
        )

    import Quartz

    origin = cursor_position() if restore_cursor else None
    _move_smooth(float(x), float(y))
    time.sleep(SETTLE_SEC)

    for state in range(1, count + 1):
        down = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, (x, y), Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventSetIntegerValueField(down, Quartz.kCGMouseEventClickState, state)
        _post(down)
        time.sleep(0.04)
        up = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, (x, y), Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventSetIntegerValueField(up, Quartz.kCGMouseEventClickState, state)
        _post(up)
        if state < count:
            time.sleep(0.06)

    if origin is not None:
        time.sleep(0.15)
        _move_smooth(*origin)

    return ClickResult(True, tr(f"({x}, {y}) を押しました。", f"Pressed ({x}, {y})."), (x, y))
