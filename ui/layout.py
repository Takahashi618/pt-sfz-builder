"""窓の大きさを決めるときの小物。主画面と設定の画面で使う。**定義はここだけ。**"""

from __future__ import annotations

import wx

__all__ = ["display_area"]


def display_area(window: wx.Window) -> wx.Rect:
    """窓のある画面の作業領域。**窓がどの画面にも無いときは主画面。**

    `wx.Display.GetFromWindow` は窓が画面の外にあると `NOT_FOUND`（-1）を返し、
    そのまま `wx.Display(-1)` にすると wx が止まる（作ったばかりで、まだ
    出していない窓でも起こりうる）。
    """
    index = wx.Display.GetFromWindow(window)
    if index == wx.NOT_FOUND:
        index = 0
    return wx.Display(index).GetClientArea()
