"""integration/sforzando_load.py のテスト。**押さない。Pro Tools にも触らない。**

読み込ませる道具のうち、判断の部分（どの画面を押すか・前に出たか・
押す位置・sforzando の版）を、AX の出力を差し替えて確かめる。
実際に押す道は実機でしか確かめられない。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from _harness import Checker

from core import sforzando_gui as gui
from integration import sforzando_load as loader
from integration.axread import parse_windows
from integration.reloader import explain_error, permission_hint

c = Checker("loader")

ROOT = Path(__file__).resolve().parents[1]

# 2026-09-04 の実測（sforzando と Decent Sampler が同じ位置に開く）
SFZ_INST1 = "WIN\tPlug-in: sforzando\tInst1\tsforzando\t20\t25\t774\t601\t20\t128\t774\t498"
SFZ_INST2 = "WIN\tPlug-in: sforzando\tInst2\tsforzando\t20\t25\t774\t601\t20\t128\t774\t498"
DECENT = "WIN\tPlug-in: DecentSampler\tInst3\tDecentSampler\t20\t25\t812\t478\t0\t1164\t812\t375"


def windows(*lines: str):
    return parse_windows("SESSION\t261024_1\n" + "\n".join(lines) + "\n")


# ==========================================================================
# どの画面を押すか
# ==========================================================================
#
# **割り当てたトラックの画面だけを押す。** 以前は「いちばん前の sforzando」を
# 押していたので、割り当てたあとに別のトラックの画面を開くと、そちらに
# 読み込ませていた（2026-10-25 のレビュー）。

chosen, why = loader.choose_window(windows(SFZ_INST2, SFZ_INST1), "Inst1")
c.check("前に別のトラックがあっても、割り当てたトラックを選ぶ", chosen is not None, why)
c.equal("選んだトラック", chosen.info.track_name if chosen else None, "Inst1")

chosen, why = loader.choose_window(windows(SFZ_INST1), "inst1 ")
c.check("大文字小文字と前後の空白は区別しない", chosen is not None, why)

chosen, why = loader.choose_window(windows(SFZ_INST2), "Inst1")
c.equal("割り当てたトラックの画面が無ければ押さない", chosen, None)
c.check("どのトラックかを言う", "「Inst1」" in why, why)
c.check("開いている画面も言う", "「Inst2」" in why, why)

chosen, why = loader.choose_window(windows(DECENT), "Inst1")
c.equal("sforzando の画面が無ければ押さない", chosen, None)
c.check("開くように言う", "開いていません" in why, why)

chosen, why = loader.choose_window(windows(DECENT, SFZ_INST2), "")
c.equal(
    "トラックを渡さなければ、いちばん前の sforzando（手で試すとき）",
    chosen.info.track_name if chosen else None,
    "Inst2",
)

# ==========================================================================
# 前に出たか
# ==========================================================================
#
# **前に出たことを確かめてから押す。** 別のプラグインの画面が同じ位置に
# 重なっていると、そちらを押してしまう。

target = windows(SFZ_INST1)[0]
c.check("いちばん前なら押す", loader.is_front(windows(SFZ_INST1, DECENT), target))
c.check("別のプラグインが前なら押さない", not loader.is_front(windows(DECENT, SFZ_INST1), target))
c.check(
    "別のトラックの sforzando が前なら押さない",
    not loader.is_front(windows(SFZ_INST2, SFZ_INST1), target),
)
moved = "WIN\tPlug-in: sforzando\tInst1\tsforzando\t60\t25\t774\t601\t60\t128\t774\t498"
c.check("同じトラックでも位置が違えば別の画面とみなす", not loader.is_front(windows(moved), target))
c.check("画面が 1 つも無ければ押さない", not loader.is_front([], target))

# ==========================================================================
# 押す位置
# ==========================================================================

planned = loader.click_points(target, "import")
c.check("押す位置が決まる", not isinstance(planned, str), str(planned))
if not isinstance(planned, str):
    open_at, item_at, allowed = planned
    # gui.xml 由来の (20+90+78, 128+20+9) と、実測のメニューの位置
    c.equal("ファイル名の欄", open_at, (188, 157))
    c.equal("import の項目", item_at, (218, 190))
    c.check("どちらも画面の中", allowed.contains(*open_at) and allowed.contains(*item_at))

no_rect = parse_windows("WIN\tPlug-in: sforzando\tInst1\tsforzando\n")[0]
c.check("画面の位置が分からなければ押さない", isinstance(loader.click_points(no_rect, "import"), str))

# ==========================================================================
# sforzando の版（画面の定義）
# ==========================================================================
#
# **定義が前提と違えば押さない。** 配布版はほかの人の Mac の、違う版の
# sforzando で動くことがある。違う所を押すより、押さないほうが安全。

good_xml = (
    '<GUI w="774" h="498" image="backer_main.png">\n'
    '  <FileMenu param="DID_FILENAME" x="90" y="20" w="157" h="19" />\n'
    "</GUI>\n"
)
c.equal("前提どおりなら食い違いは無い", gui.definition_problems(good_xml), [])
c.check(
    "大きさが違えば食い違い",
    gui.definition_problems(good_xml.replace('w="774"', 'w="800"')) != [],
)
c.check(
    "ファイル名の欄が動けば食い違い",
    gui.definition_problems(good_xml.replace('x="90"', 'x="96"')) != [],
)
c.check("欄が無ければ食い違い", gui.definition_problems('<GUI w="774" h="498">') != [])
c.check("定義そのものが無ければ食い違い", gui.definition_problems("") != [])

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "gui.xml"
    c.check("ファイルが無ければ押さない", loader.gui_problems(str(path)) != [])
    path.write_text(good_xml, encoding="utf-8")
    c.equal("ファイルが前提どおりなら押せる", loader.gui_problems(str(path)), [])

# この Mac に sforzando が入っていれば、実物の定義も前提どおりのはず
if Path(gui.SOURCE_XML).is_file():
    c.equal("実物の定義も前提どおり", loader.gui_problems(), [])

# ==========================================================================
# 引数
# ==========================================================================

c.equal(
    "import とパスとトラック",
    loader._parse(["import", "/s/slot01.sfz", "--track", "Inst 1"]),
    ("import", "/s/slot01.sfz", "Inst 1", False),
)
c.equal(
    "--dry-run",
    loader._parse(["--dry-run", "reload"]),
    ("reload", "", "", True),
)
c.check("import にパスが無ければ断る", isinstance(loader._parse(["import"]), str))
c.check("知らない操作は断る", isinstance(loader._parse(["load"]), str))
c.check("--track の名前が無ければ断る", isinstance(loader._parse(["empty", "--track"]), str))

# ==========================================================================
# 許可が無いときの言い方
# ==========================================================================
#
# **配布版を初めて開いた人が必ず通る。** osascript のエラーは英語交じりの
# 長い文で、読み上げで聞いても直し方が分からない。番号で見分ける。

hint = permission_hint("execution error: Not authorized to send Apple events to System Events. (-1743)")
c.check("オートメーションの許可", "オートメーション" in hint, hint)
c.check("どれをオンにするか言う", "System Events" in hint, hint)
hint = permission_hint("System Events でエラーが起きました: osascript には補助アクセスは許可されていません。 (-25211)")
c.check("アクセシビリティの許可（新しい番号）", "アクセシビリティ" in hint, hint)
c.check("設定の開き方まで言う", "アクセシビリティの設定を開く" in hint, hint)
c.check("古い番号でも分かる", "アクセシビリティ" in permission_hint("(-1719)"))
c.equal("許可と関係なければ空", permission_hint("NO_PLUGIN_WINDOW"), "")
c.equal("分からないものは元の文のまま", explain_error(" 何かの失敗 "), "何かの失敗")

# ==========================================================================
# 道具がそろっているか（--check）。**別のプロセスで、アプリと同じ入口から**
# ==========================================================================
#
# 配布版を作るときは、組み上げた .app の中から同じことをする（`app.py --selftest`）。

done = subprocess.run(
    [sys.executable, str(ROOT / "app.py"), "--sforzando-load", "--check"],
    capture_output=True,
    text=True,
    timeout=120,
)
c.equal("--check は通る", done.returncode, 0)
c.check(
    "読み上げる一文を最後に出す",
    (done.stdout or "").strip().splitlines()[-1].startswith("MESSAGE\t"),
    done.stdout + done.stderr,
)
c.equal(
    "道具の AppleScript は全部ある",
    [name for name in loader.SCRIPTS if not (ROOT / "tools" / name).is_file()],
    [],
)

raise SystemExit(c.summary())
