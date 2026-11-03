"""axread.py のテスト。

**AppleScript は実行しない。** スタブの Runner を注入して、
出力の解析と、そこから読み上げ文言に至るまでの全経路を通す。
書式が固定なので、実機が無くても検証できる。
"""

from collections.abc import Sequence

from _harness import Checker

from core.slots import PluginKind
from integration.axread import (
    AxReadResult,
    AxWindow,
    SCRIPT_NAME,
    parse_windows,
    read_plugin_windows,
)
from integration.reloader import ScriptResult

c = Checker("axread")


class StubRunner:
    """決まった結果を返すだけ。呼ばれた引数も記録する。"""

    def __init__(self, result: ScriptResult) -> None:
        self.result = result
        self.calls: list[tuple[str, list[str]]] = []

    def run(self, script: str, args: Sequence[str]) -> ScriptResult:
        self.calls.append((script, list(args)))
        return self.result


# 2026-09-04 に実機で採れた出力そのまま（末尾の空行も含む）。
REAL = "WIN\tPlug-in: sforzando\tInst1\tsforzando\t20\t25\t774\t601\t20\t128\t774\t498\n\n"
# 同日、同じ窓の位置で Decent Sampler が返した値。**描画領域の位置が窓の外。**
REAL_DECENT = "WIN\tPlug-in: DecentSampler\tInst1\tDecentSampler\t20\t25\t812\t478\t0\t1164\t812\t375\n"

# ==========================================================================
# parse_windows — 純粋関数
# ==========================================================================

windows = parse_windows(REAL)
c.equal("実機の出力から 1 枚読める", len(windows), 1)
w = windows[0]
c.equal("タイトル", w.info.title, "Plug-in: sforzando")
c.equal("トラック名", w.info.track_name, "Inst1")
c.equal("プラグイン名", w.info.plugin_name, "sforzando")
c.equal("矩形 x", w.x, 20)
c.equal("矩形 y", w.y, 25)
c.equal("矩形 幅", w.width, 774)
c.equal("矩形 高さ", w.height, 601)
c.check("矩形が揃っている", w.has_rect)

c.check("窓の中の点", w.contains(100, 200))
c.check("窓の左上は含む", w.contains(20, 25))
c.check("窓の右下は含まない", not w.contains(20 + 774, 25 + 601))
c.check("窓の外の点", not w.contains(5, 5))

c.equal("空文字なら 0 枚", parse_windows(""), [])
c.equal("空白だけでも 0 枚", parse_windows("\n \n"), [])
c.equal("知らない行は捨てる", parse_windows("HELLO\tfoo\n"), [])

# 取れなかった項目は空文字で来る。**推測で埋めず None にする。**
partial = parse_windows("WIN\tPlug-in: sforzando\t\t\t\t\t\t\n")
c.equal("欠けても 1 枚は読める", len(partial), 1)
c.equal("トラック名が空なら None", partial[0].info.track_name, None)
c.equal("プラグイン名が空なら None", partial[0].info.plugin_name, None)
c.equal("矩形が空なら None", partial[0].x, None)
c.check("矩形は揃っていない", not partial[0].has_rect)
c.check("矩形が無ければ contains は False", not partial[0].contains(0, 0))

# 桁が足りない行でも落とさない
short = parse_windows("WIN\tPlug-in: sforzando\tInst1\n")
c.equal("桁が足りなくても読める", len(short), 1)
c.equal("足りない分は None", short[0].width, None)

# 複数枚。**前面から順**であることが呼び出し側の前提。
two = parse_windows(
    "WIN\tPlug-in: sforzando\tInst1\tsforzando\t20\t25\t774\t601\t20\t128\t774\t498\n"
    "WIN\tPlug-in: Decent Sampler\tInst2\tDecent Sampler\t50\t60\t900\t700\t50\t163\t900\t597\n"
)
c.equal("2 枚読める", len(two), 2)
c.equal("1 枚目が前面", two[0].info.track_name, "Inst1")
c.equal("2 枚目", two[1].info.plugin_name, "Decent Sampler")


# ==========================================================================
# 描画領域の位置 — **AX の値を検証してから使う**
# ==========================================================================

sfor = parse_windows(REAL)[0]
c.equal("sforzando の描画領域 x", sfor.view_x, 20)
c.equal("sforzando の描画領域 y", sfor.view_y, 128)
c.equal("sforzando の描画領域の大きさ", (sfor.view_width, sfor.view_height), (774, 498))
c.check("大きさが取れている", sfor.has_view_size)
c.check("sforzando の位置は妥当", sfor.view_origin_is_sane)
c.equal("そのまま採用する", sfor.content_origin(), (20, 128))

# **同じ日・同じ窓の位置で、Decent Sampler は窓の外を返した。**
dec = parse_windows(REAL_DECENT)[0]
c.equal("Decent Sampler が返した位置", (dec.view_x, dec.view_y), (0, 1164))
c.check("窓の外なので妥当でない", not dec.view_origin_is_sane)
# 窓の左下に揃えて計算し直す: 25 + 478 - 375 = 128
c.equal("計算し直した位置", dec.content_origin(), (20, 128))
c.equal("sforzando と同じ高さに来る", dec.content_origin()[1], sfor.content_origin()[1])

# 右下がはみ出す場合も弾く
overflow = parse_windows("WIN\tPlug-in: X\tT\tsforzando\t20\t25\t100\t100\t20\t25\t500\t500\n")[0]
c.check("右下がはみ出せば妥当でない", not overflow.view_origin_is_sane)

# 描画領域が取れていない
none_view = parse_windows("WIN\tPlug-in: X\tT\tsforzando\t20\t25\t100\t100\t\t\t\t\n")[0]
c.check("大きさが無い", not none_view.has_view_size)
c.check("位置も妥当でない", not none_view.view_origin_is_sane)
c.equal("計算もできないので None", none_view.content_origin(), None)

# 窓の矩形すら無ければ None。**推測で座標を返さない。**
nothing = parse_windows("WIN\tPlug-in: X\tT\tsforzando\t\t\t\t\t\t\t812\t375\n")[0]
c.equal("窓が無ければ None", nothing.content_origin(), None)

# ==========================================================================
# read_plugin_windows — Runner を介した経路
# ==========================================================================

runner = StubRunner(ScriptResult(True, output=REAL))
result = read_plugin_windows(runner)
c.check("成功する", result.ok)
c.equal("スクリプト名を渡す", runner.calls, [(SCRIPT_NAME, [])])
c.equal("1 枚", len(result.windows), 1)
c.equal("WindowInfo を取り出せる", len(result.infos), 1)

target = result.front_target()
c.check("対象を解釈できる", target is not None)
c.equal("プラグイン種別", target.plugin, PluginKind.SFORZANDO)
c.equal("トラック名は加工しない", target.track_name, "Inst1")
c.check("読み上げにトラック名が入る", "Inst1" in result.describe_ja(), result.describe_ja())
c.check("読み上げは日本語のプラグイン名", "スフォルツァンド" in result.describe_ja())

# Pro Tools が動いていない
runner = StubRunner(ScriptResult(True, output="NO_PRO_TOOLS"))
result = read_plugin_windows(runner)
c.check("Pro Tools 未起動は ok=False", not result.ok)
c.check("理由を言う", "Pro Tools" in result.error, result.error)
c.check("読み上げにも理由が出る", "Pro Tools" in result.describe_ja())

# ウィンドウが 1 枚も開いていない。**失敗ではない。**
runner = StubRunner(ScriptResult(True, output=""))
result = read_plugin_windows(runner)
c.check("開いていないのは失敗ではない", result.ok)
c.equal("0 枚", len(result.windows), 0)
c.equal("対象は None", result.front_target(), None)
c.check("開いてほしいと伝える", "開いて" in result.describe_ja(), result.describe_ja())

# AppleScript 自体が失敗した
runner = StubRunner(ScriptResult(False, error="スクリプトが見つかりません"))
result = read_plugin_windows(runner)
c.check("失敗は ok=False", not result.ok)
c.check("理由を持って返る", "見つかりません" in result.error)
c.check("例外は投げない", isinstance(result, AxReadResult))

# 対象外のプラグインが前面
runner = StubRunner(
    ScriptResult(True, output="WIN\tPlug-in: Battery 4\tInst1\tBattery 4\t0\t0\t10\t10\n")
)
result = read_plugin_windows(runner)
c.check("読み取り自体は成功", result.ok)
c.equal("解釈できない", result.front_target(), None)
c.check("対象外だと伝える", "対象のプラグインではありません" in result.describe_ja(), result.describe_ja())
c.check("何が開いているかを言う", "Battery 4" in result.describe_ja())

# 対象外が前面、対象が背面。**背面でも拾う。**
runner = StubRunner(
    ScriptResult(
        True,
        output=(
            "WIN\tPlug-in: Battery 4\tInst1\tBattery 4\t0\t0\t10\t10\n"
            "WIN\tPlug-in: sforzando\tInst2\tsforzando\t20\t25\t774\t601\n"
        ),
    )
)
result = read_plugin_windows(runner)
target = result.front_target()
c.check("背面の対象を拾う", target is not None)
c.equal("背面のトラック名", target.track_name, "Inst2")

# AxWindow を直接組み立てる経路（案 C の座標検証で使う）
bare = AxWindow(info=result.infos[0])
c.check("矩形なしでも作れる", not bare.has_rect)

raise SystemExit(c.summary())
