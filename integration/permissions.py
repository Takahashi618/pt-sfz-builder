"""アクセシビリティの許可。**確かめるのと、設定の画面を開くところまで。**

このアプリは Pro Tools の画面を読み（System Events）、sforzando の画面を
合成マウスで押す。どちらもアクセシビリティの許可が要る。

**許可を入れるのは利用者本人。** ここは、許可があるかを確かめることと、
システム設定の画面を開くことだけをする（入り切りはしない）。
作者の別のアプリの「アクセシビリティの設定を開く」と同じ作り。

**合成マウスは、許可が無いと黙って何もしない**（エラーにならない）。
押したつもりで先へ進むと、「ファイルを選ぶ画面が出ない」という
分かりにくい失敗になるので、押す前にここで確かめる。

macOS 専用。pyobjc が無ければ「分からない」として扱う（落とさない）。
"""

from __future__ import annotations

import subprocess
import sys

__all__ = [
    "ACCESSIBILITY_PANE",
    "is_trusted",
    "request_trust_prompt",
    "open_accessibility_settings",
]

# システム設定の「プライバシーとセキュリティ」→「アクセシビリティ」の画面
ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)


def is_trusted() -> bool | None:
    """このアプリにアクセシビリティの許可があるか。**分からなければ None。**

    macOS は許可を「起動したアプリ」に付けるので、このアプリから起こした
    道具（読み込ませる道具）の中で呼んでも、アプリの許可が答えになる。
    """
    if sys.platform != "darwin":
        return None
    try:
        import ApplicationServices as AS
    except ImportError:
        return None
    try:
        return bool(AS.AXIsProcessTrusted())
    except Exception:
        return None


def request_trust_prompt() -> None:
    """macOS に「このアプリが許可を求めている」と知らせる（許可の一覧に載せる）。

    **利用者が明示的に頼んだときだけ呼ぶ**（操作メニュー）。入り切りはしない。
    """
    if sys.platform != "darwin":
        return
    try:
        import ApplicationServices as AS

        AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True})
    except Exception:
        pass


def open_accessibility_settings() -> bool:
    """システム設定のアクセシビリティの画面を開く。開けたら True。"""
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(
            ["open", ACCESSIBILITY_PANE], check=True, capture_output=True, timeout=10
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
