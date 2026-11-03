"""前面のプラグインウィンドウを AX から読む。**macOS 側の目にあたる層。**

`core/target.py` は「受け取った文字列をどう解釈するか」だけを持つ純粋な層で、
実際に AX を叩く仕事はここが受け持つ。分けてあるのは、解釈の部分を
Windows でもテストできるようにするため。

読み取りだけなので**前面化は要らない**（AXPress のような操作は背面だと
通らないが、属性の読み取りは通る）。

    osascript tools/ax_plugin_windows.applescript
      → WIN <TAB> title <TAB> track <TAB> plugin <TAB> x <TAB> y <TAB> w <TAB> h
            <TAB> vx <TAB> vy <TAB> vw <TAB> vh

書式が固定なので、解析（`parse_windows`）は純粋関数にできる。
**実機が無くても全経路をテストできる。**

2026-09-04 に実機で採れた値。

    WIN	Plug-in: sforzando	Inst1	sforzando	20	25	774	601	20	128	774	498
    WIN	Plug-in: DecentSampler	Inst1	DecentSampler	20	25	812	478	0	1164	812	375

### 描画領域の位置は当てにならない（2026-09-04 実測）

後半 4 つは `FXTDMEditView`（プラグインの描画領域）の矩形。**位置が信用できない。**

| プラグイン | 窓 | 描画領域が返した位置 | 妥当か |
| --- | --- | --- | --- |
| sforzando | (20,25) 774x601 | (20,128) | **正しい** |
| Decent Sampler | (20,25) 812x478 | (0,1164) | **窓の外。使えない** |

同じ Pro Tools・同じ日・同じ窓の位置でも割れる。**必ず検証してから使う。**

**大きさのほうは両方とも正しかった。** そこで、位置が窓の外なら
「描画領域は窓の左下に揃っている」として計算し直す。

    描画領域の左上 = (窓の左, 窓の上 + 窓の高さ − 描画領域の高さ)

この式は両方に当てはまる（どちらもヘッダの高さが 103 だった）。

    sforzando      : 25 + 601 − 498 = 128  ← AX が返した値と一致
    Decent Sampler : 25 + 478 − 375 = 128  ← AX の 1164 ではなくこちらを使う
"""

from __future__ import annotations

from core.i18n import COMMA, tr

from dataclasses import dataclass
from pathlib import Path

from core.sibling import PROJECT_ROOT
from core.target import PluginTarget, WindowInfo, choose_front_target

from .reloader import OsascriptRunner, ScriptResult, ScriptRunner, explain_error

__all__ = [
    "AxWindow",
    "AxReadResult",
    "SCRIPT_NAME",
    "parse_windows",
    "parse_session_name",
    "read_plugin_windows",
    "make_reader",
]

SCRIPT_NAME = "ax_plugin_windows.applescript"

# AppleScript が「Pro Tools が動いていない」ときに返す合図。
_NO_PRO_TOOLS = "NO_PRO_TOOLS"


@dataclass(frozen=True)
class AxWindow:
    """プラグインウィンドウ 1 枚。

    `info` が解釈に要る部分で、矩形は座標クリック用。
    **矩形は取れないことがある**ので None を許す。

    `view_*` はプラグインの描画領域（`FXTDMEditView`）。**位置は信用しない。**
    `content_origin()` を通して使うこと。
    """

    info: WindowInfo
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    view_x: int | None = None
    view_y: int | None = None
    view_width: int | None = None
    view_height: int | None = None

    @property
    def has_rect(self) -> bool:
        return None not in (self.x, self.y, self.width, self.height)

    @property
    def has_view_size(self) -> bool:
        """描画領域の**大きさ**が取れているか。位置は別に扱う。"""
        return self.view_width is not None and self.view_height is not None

    @property
    def view_origin_is_sane(self) -> bool:
        """AX が返した描画領域の位置が、窓の中に収まっているか。

        **収まっていなければ使わない。** 2026-09-04 の Decent Sampler は
        窓が (20,25) なのに描画領域を (0,1164) と返した。
        """
        if self.view_x is None or self.view_y is None:
            return False
        if not self.has_rect or not self.has_view_size:
            return False
        assert self.view_width is not None and self.view_height is not None
        if not self.contains(self.view_x, self.view_y):
            return False
        # 右下も窓の中か。1 px 分の余裕は見ない（端まで使う造りのため）
        right = self.view_x + self.view_width
        bottom = self.view_y + self.view_height
        assert self.x is not None and self.y is not None
        assert self.width is not None and self.height is not None
        return right <= self.x + self.width and bottom <= self.y + self.height

    def content_origin(self) -> tuple[int, int] | None:
        """描画領域の左上の画面座標。**検証済みの値だけを返す。**

        AX の値が妥当ならそれを使い、外れていれば
        「描画領域は窓の左下に揃っている」として計算し直す。
        どちらも出せなければ None を返す。**推測で座標を返さない。**
        """
        if self.view_origin_is_sane:
            assert self.view_x is not None and self.view_y is not None
            return self.view_x, self.view_y
        if not self.has_rect or self.view_height is None:
            return None
        assert self.x is not None and self.y is not None
        assert self.height is not None
        return self.x, self.y + self.height - self.view_height

    def contains(self, px: int, py: int) -> bool:
        """点が窓の中か。**AX が返す座標の妥当性検証に使う。**

        プラグイン内部の座標は合成値で、窓の外を指すことがある。
        使う前にここを通す。
        """
        if not self.has_rect:
            return False
        assert self.x is not None and self.y is not None
        assert self.width is not None and self.height is not None
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height


@dataclass(frozen=True)
class AxReadResult:
    """読み取りの結果。失敗しても例外は投げず、理由を持って返る。"""

    ok: bool
    windows: tuple[AxWindow, ...] = ()
    error: str = ""
    # 開いている Pro Tools セッションの名前。取れなければ空文字。
    # **スロットをセッションごとに分けるのに使う**（`core/slots.py`）。
    session_name: str = ""

    @property
    def infos(self) -> list[WindowInfo]:
        return [w.info for w in self.windows]

    def front_target(self) -> PluginTarget | None:
        """前面から順に見て、最初に解釈できた対象を返す。"""
        return choose_front_target(self.infos)

    def describe_ja(self) -> str:
        """読み上げ用。**何も見つからないことと、失敗は区別する。**

        失敗の理由が許可なら、どこで入れるかまで言う（`explain_error`）。
        """
        if not self.ok:
            return tr(
                f"プラグインウィンドウを調べられませんでした。{explain_error(self.error)}",
                f"Could not check the plugin windows. {explain_error(self.error)}",
            )
        if not self.windows:
            return tr(
                "プラグインのウィンドウが開いていません。開いてから実行してください。",
                "No plugin window is open. Open one and try again.",
            )
        target = self.front_target()
        if target is None:
            names = COMMA.join(w.info.title for w in self.windows)
            return tr(
                f"割り当て対象のプラグインではありません。開いているのは {names} です。",
                f"This is not a plugin that can be assigned. {names} is open.",
            )
        return target.describe_ja()


def _to_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


def parse_session_name(text: str) -> str:
    """出力の `SESSION` 行からセッション名を取る。無ければ空文字。

    **推測しない。** 取れなかったときは空文字のまま返し、
    呼び出し側が「分からない」として扱えるようにする。
    """
    for raw in (text or "").splitlines():
        fields = raw.split("\t")
        if fields[0] == "SESSION":
            return fields[1].strip() if len(fields) > 1 else ""
    return ""


def parse_windows(text: str) -> list[AxWindow]:
    """AppleScript の出力を解析する。**純粋関数。**

    知らない行は黙って捨てる。AppleScript は末尾に空行を付けるし、
    将来別の行種が増えても壊れないほうがよい。
    """
    windows: list[AxWindow] = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if fields[0] != "WIN":
            continue
        # 足りない分は空文字で埋める。**桁が減っても落とさない。**
        fields += [""] * (12 - len(fields))
        _, title, track, plugin, x, y, w, h, vx, vy, vw, vh = fields[:12]
        windows.append(
            AxWindow(
                info=WindowInfo(
                    title=title.strip(),
                    track_name=track.strip() or None,
                    plugin_name=plugin.strip() or None,
                ),
                x=_to_int(x),
                y=_to_int(y),
                width=_to_int(w),
                height=_to_int(h),
                view_x=_to_int(vx),
                view_y=_to_int(vy),
                view_width=_to_int(vw),
                view_height=_to_int(vh),
            )
        )
    return windows


def read_plugin_windows(runner: ScriptRunner) -> AxReadResult:
    """AppleScript を走らせて、開いているプラグインウィンドウを返す。

    Pro Tools が動いていないことは**失敗ではなく、そう伝えるべき状態**として扱う。
    """
    result: ScriptResult = runner.run(SCRIPT_NAME, [])
    if not result.ok:
        return AxReadResult(False, error=result.error or tr(
            "AppleScript が失敗しました",
            "AppleScript failed",
        ))

    output = result.output.strip()
    if output == _NO_PRO_TOOLS:
        return AxReadResult(False, error=tr(
            "Pro Tools が起動していません。",
            "Pro Tools is not running.",
        ))

    return AxReadResult(
        True,
        windows=tuple(parse_windows(result.output)),
        session_name=parse_session_name(result.output),
    )


def make_reader(scripts_dir: str | Path | None = None) -> ScriptRunner:
    """既定のスクリプト置き場（このリポジトリの `tools/`）を使う Runner。

    配布版では `.app` の中の `tools/`（`core/sibling.PROJECT_ROOT` の下）。
    """
    base = Path(scripts_dir) if scripts_dir else PROJECT_ROOT / "tools"
    return OsascriptRunner(base)
