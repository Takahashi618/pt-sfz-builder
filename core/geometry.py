"""画面上の矩形。**定義はここだけ。**

同じ 4 つの数（x / y / w / h）を持つ型が 2 か所にあり、片方は
`center`（押す位置を出す）、もう片方は `contains`（押してよいか確かめる）
だけを持っていた。呼び出し側は座標を手で組み直して行き来していて、
**確かめずに撃つ経路を作りやすかった。**

押す前に必ず範囲を確かめる、という約束を守りやすくするために 1 つにする。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Rect"]


@dataclass(frozen=True)
class Rect:
    """左上を原点とする矩形。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def contains(self, px: int, py: int) -> bool:
        """点が中にあるか。**押す前に必ず通す。**"""
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h
