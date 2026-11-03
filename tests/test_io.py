"""atomicio.py と reloader.py のテスト。

書き込みは実ファイルを使う（一時ディレクトリ）。AppleScript は
スタブを注入するので、Windows でも全経路を通せる。
"""

import sys
import tempfile
from pathlib import Path

from _harness import Checker

from core.atomicio import read_text, write_atomic
from core.slots import PluginKind, SlotAssignment
from integration.reloader import (
    FolderWatchReload,
    KeyboardOpenReload,
    LibrarianReload,
    NullReload,
    OsascriptRunner,
    ReloadOutcome,
    ReloadRequest,
    ScriptResult,
)

c = Checker("io")

# ==========================================================================
# atomicio
# ==========================================================================

with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)

    # --- 新規に書く ---
    target = tmp / "slot01.sfz"
    written = write_atomic(target, "<region>\nsample=/a/b.wav\n")
    c.check("ファイルができる", target.is_file())
    c.equal("戻り値は書いたパス", written, target)
    c.equal("読み戻せる", read_text(target), "<region>\nsample=/a/b.wav\n")

    # --- 改行は LF に固定される ---
    write_atomic(target, "a\nb\n")
    c.equal(
        "Windows で書いても CRLF にならない",
        target.read_bytes(),
        b"a\nb\n",
    )

    # --- UTF-8 で書かれる ---
    write_atomic(target, "// スロット1\n")
    c.check("日本語が UTF-8 で入る", "スロット1".encode("utf-8") in target.read_bytes())

    # --- 上書き ---
    write_atomic(target, "new\n")
    c.equal("上書きできる", read_text(target), "new\n")

    # --- 一時ファイルが残らない ---
    leftovers = [p.name for p in tmp.iterdir() if p.name.endswith(".tmp")]
    c.equal("作業用ファイルは残らない", leftovers, [])

    # --- 親ディレクトリを作る ---
    nested = tmp / "a" / "b" / "slot02.sfz"
    write_atomic(nested, "x\n")
    c.check("無ければ親ごと作る", nested.is_file())

    # --- 空文字も書ける ---
    empty = tmp / "empty.sfz"
    write_atomic(empty, "")
    c.equal("空でも書ける", read_text(empty), "")

    # --- 失敗しても元のファイルが壊れない ---
    directory = tmp / "adir"
    directory.mkdir()
    c.raises("ディレクトリには書けない", OSError, write_atomic, directory, "x")
    c.equal(
        "失敗しても作業用ファイルは残らない",
        [p.name for p in tmp.iterdir() if p.name.endswith(".tmp")],
        [],
    )

    keep = tmp / "keep.sfz"
    write_atomic(keep, "original\n")
    c.raises("文字列以外は拒む", TypeError, write_atomic, keep, 123)
    c.equal("拒んだあとも中身は無事", read_text(keep), "original\n")

# ==========================================================================
# reloader
# ==========================================================================

SLOT = SlotAssignment(number=1, plugin=PluginKind.SFORZANDO, track_name="Inst1")
REQUEST = ReloadRequest(
    slot=SLOT,
    setting_name="SLOT_01",
    file_path="/Volumes/Audio/sfz_slots/slot01.sfz",
)


class StubRunner:
    """AppleScript の実行を差し替える。呼ばれた内容を記録する。"""

    def __init__(self, result: ScriptResult) -> None:
        self.result = result
        self.calls: list[tuple[str, list[str]]] = []

    def run(self, script, args) -> ScriptResult:
        self.calls.append((script, list(args)))
        return self.result


# --- NullReload ---
result = NullReload().reload(REQUEST)
c.equal("何もしないと skipped", result.outcome, ReloadOutcome.SKIPPED)
c.check("失敗ではない", result.ok)
c.check("次に何をすればよいか伝える", "選び直す" in result.message_ja, result.message_ja)
c.check("設定名を言う", "SLOT_01" in result.message_ja)
c.check("成功を装わない", "反映しました" not in result.message_ja)

# --- LibrarianReload（案A）---
runner = StubRunner(ScriptResult(True, output="ok"))
result = LibrarianReload(runner).reload(REQUEST)
c.equal("成功すると done", result.outcome, ReloadOutcome.DONE)
c.equal("設定選択のスクリプトを呼ぶ", runner.calls[0][0], "ax_select_setting.applescript")
c.equal("設定名を渡す", runner.calls[0][1], ["SLOT_01"])
c.check("反映したと伝える", "反映しました" in result.message_ja)

runner = StubRunner(ScriptResult(False, error="window not found"))
result = LibrarianReload(runner).reload(REQUEST)
c.equal("失敗すると failed", result.outcome, ReloadOutcome.FAILED)
c.check("ok ではない", not result.ok)
c.check("警告接頭辞を付ける", result.message_ja.startswith("[警告]"), result.message_ja)
c.check("手動の手順を案内する", "手で選び直して" in result.message_ja)
c.equal("原因を detail に残す", result.detail, "window not found")

# --- KeyboardOpenReload（案B）---
#
# **2 本立て。** 開くところ（Cmd+O）とパスを入れるところを分けてある。
# 後半は `tools/sforzando_load.py` と共有する。同じ手順を 2 か所に
# 書いていたときは、実機で詰めた待ち時間がすでに食い違っていた。
runner = StubRunner(ScriptResult(True))
result = KeyboardOpenReload(runner).reload(REQUEST)
c.equal("成功すると done", result.outcome, ReloadOutcome.DONE)
c.equal("2 本呼ぶ", len(runner.calls), 2)
c.equal("まず Cmd+O", runner.calls[0][0], "press_cmd_o.applescript")
c.equal("次にパスを入れる", runner.calls[1][0], "fill_open_dialog.applescript")
c.equal("パスを渡す", runner.calls[1][1], [REQUEST.file_path])

runner = StubRunner(ScriptResult(False, error="timeout"))
result = KeyboardOpenReload(runner).reload(REQUEST)
c.equal("失敗すると failed", result.outcome, ReloadOutcome.FAILED)
c.equal("開けなければ 2 本目は呼ばない", len(runner.calls), 1)
c.check("Cmd+O の手順を案内する", "Cmd+O" in result.message_ja, result.message_ja)
c.check("開くべきパスを言う", REQUEST.file_path in result.message_ja)

# --- OsascriptRunner ---
# 実行できない理由はプラットフォームで変わる。**両方を確かめる。**
#   Windows: AppleScript がそもそも動かない
#   macOS  : 動くが、スクリプトファイルが無い
# ここを片方だけで書くと、もう一方の OS でテストが落ちる（2026-09-04 に発生）。
runner = OsascriptRunner(scripts_dir="/nonexistent")
outcome = runner.run("whatever.applescript", [])
c.check("実行できないことが分かる", not outcome.ok)
if sys.platform == "darwin":
    c.check("理由を返す — スクリプトが無い", "見つかりません" in outcome.error, outcome.error)
else:
    c.check("理由を返す — macOS 専用", "macOS" in outcome.error, outcome.error)

# --- FolderWatchReload（既定） ---
# sforzando が置き場所を監視して自動で読み直すことが 2026-09-04 に確認できた。
# **何もしないが、SKIPPED ではなく DONE を返す。** 実際に反映されるので、
# 「人が操作しないと反映されない」と読み上げるのは誤りになる。
result = FolderWatchReload().reload(REQUEST)
c.equal("反映されたとみなす", result.outcome, ReloadOutcome.DONE)
c.check("失敗ではない", result.ok)
c.check("自動で反映されると伝える", "自動で反映" in result.message_ja, result.message_ja)
c.check("選び直しを促さない", "選び直" not in result.message_ja, result.message_ja)
c.equal("どのファイルかを控える", result.detail, REQUEST.file_path)

# NullReload との違いを明示しておく。取り違えると読み上げが変わる。
null_result = NullReload().reload(REQUEST)
c.equal("NullReload は skipped", null_result.outcome, ReloadOutcome.SKIPPED)
c.check("両者は別の文言", null_result.message_ja != result.message_ja)

raise SystemExit(c.summary())
