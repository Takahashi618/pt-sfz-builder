"""target.py のテスト。プラグインウィンドウの解釈。

実機（2026-08-07 実測）の書式を第一に据え、書式が違った場合の
フォールバックも通す。S4 で確定したら、使わない経路を削る。
"""

from _harness import Checker

from core.slots import PluginKind
from core.target import (
    PluginTarget,
    WindowInfo,
    build_target,
    choose_front_target,
    detect_plugin,
    parse_window_title,
    split_insert_marker,
)

c = Checker("target")

SFZ = PluginKind.SFORZANDO
DS = PluginKind.DECENT_SAMPLER

# --- プラグイン種別の判定 ---
c.equal("タイトルから sforzando", detect_plugin("Plug-in: sforzando"), SFZ)
c.equal("大文字小文字を無視", detect_plugin("PLUG-IN: SFORZANDO"), SFZ)
c.equal("Decent Sampler を拾う", detect_plugin("Plug-in: Decent Sampler"), DS)
c.equal("知らないプラグインは None", detect_plugin("Plug-in: Kontakt 8"), None)
c.equal("空文字は None", detect_plugin(""), None)
c.equal("None を渡しても落ちない", detect_plugin(None), None)
c.equal("先に渡した方を優先する", detect_plugin("sforzando", "Decent Sampler"), SFZ)
c.equal("空を飛ばして次を見る", detect_plugin(None, "Decent Sampler"), DS)
c.equal(
    "トラック名に紛れても末尾のプラグイン名を採る",
    detect_plugin("Decent Sampler bus - sforzando"),
    SFZ,
)

# --- 実機の書式（主経路）---
window = WindowInfo(
    title="Plug-in: sforzando", track_name="Inst1", plugin_name="sforzando"
)
target = build_target(window)
c.check("解釈できる", target is not None)
c.equal("プラグイン種別", target.plugin, SFZ)
c.equal("Track Selector の値をそのまま使う", target.track_name, "Inst1")
c.check("曖昧ではない", not target.ambiguous)
c.equal("元のタイトルを保つ", target.raw_title, "Plug-in: sforzando")
c.check("読み上げにトラック名が出る", "Inst1" in target.describe_ja())
c.check("読み上げは日本語ラベル", "スフォルツァンド" in target.describe_ja())

# Track Selector の値は加工しない。末尾が英字1文字でも切り落とさない。
tricky = build_target(WindowInfo(title="Plug-in: sforzando", track_name="Kick a"))
c.equal("Track Selector 由来は末尾を切らない", tricky.track_name, "Kick a")
c.equal("インサートも付けない", tricky.insert_slot, None)

# Plugin Selector があればタイトルが読めなくてもよい
c.equal(
    "Plugin Selector だけでも判定できる",
    build_target(WindowInfo(title="", track_name="Inst1", plugin_name="sforzando")).plugin,
    SFZ,
)

# --- タイトルの解釈 ---
c.equal(
    "Plug-in: 形式はトラック名を含まない",
    parse_window_title("Plug-in: sforzando"),
    (SFZ, None),
)
c.equal(
    "ハイフン区切りならトラック名が取れる",
    parse_window_title("Audio 1 - sforzando"),
    (SFZ, "Audio 1"),
)
c.equal(
    "コロン区切りも読める",
    parse_window_title("Kick: Decent Sampler"),
    (DS, "Kick"),
)
c.equal("空タイトル", parse_window_title(""), (None, None))
c.equal("知らないプラグイン", parse_window_title("Audio 1 - Kontakt 8"), (None, None))

# --- インサート表記の切り離し ---
c.equal("明示的な Insert a", split_insert_marker("Audio 1 Insert a"), ("Audio 1", "a", False))
c.equal("括弧つき", split_insert_marker("Audio 1 (b)"), ("Audio 1", "b", False))
c.equal("角括弧つき", split_insert_marker("Audio 1 [c]"), ("Audio 1", "c", False))
c.equal("単独の1文字は曖昧", split_insert_marker("Kick a"), ("Kick", "a", True))
c.equal("表記が無ければそのまま", split_insert_marker("Kick Drum"), ("Kick Drum", None, False))
c.equal(
    "全体が1文字なら切り離さない（名前を失う）",
    split_insert_marker("a"),
    ("a", None, False),
)
c.equal("k 以降は対象外", split_insert_marker("Track k"), ("Track k", None, False))

# --- フォールバック経路（Track Selector が無い）---
fallback = build_target(WindowInfo(title="Audio 1 - sforzando"))
c.equal("タイトルからトラック名を取る", fallback.track_name, "Audio 1")
c.check("曖昧ではない", not fallback.ambiguous)

risky = build_target(WindowInfo(title="Kick a - sforzando"))
c.equal("末尾1文字はインサートとみなす", risky.track_name, "Kick")
c.equal("スロットを拾う", risky.insert_slot, "a")
c.check("ただし曖昧と印を付ける", risky.ambiguous)
c.check("読み上げで注意を促す", "確かめて" in risky.describe_ja(), risky.describe_ja())

# --- 解釈できない場合 ---
c.equal("トラック名が取れなければ None", build_target(WindowInfo(title="Plug-in: sforzando")), None)
c.equal("プラグインが違えば None", build_target(WindowInfo(title="Plug-in: Kontakt 8", track_name="Inst1")), None)
c.equal("空の WindowInfo は None", build_target(WindowInfo()), None)
c.equal(
    "空白だけのトラック名は採らない",
    build_target(WindowInfo(title="Plug-in: sforzando", track_name="   ")),
    None,
)

# --- 前面から選ぶ ---
windows = [
    WindowInfo(title="Mix: Session"),
    WindowInfo(title="Plug-in: Kontakt 8", track_name="Inst9"),
    WindowInfo(title="Plug-in: sforzando", track_name="Inst1"),
]
chosen = choose_front_target(windows)
c.equal("解釈できた最初のものを採る", chosen.track_name, "Inst1")
c.equal("対象が無ければ None", choose_front_target([WindowInfo(title="Mix: Session")]), None)
c.equal("空のリストは None", choose_front_target([]), None)

# --- 同一性 ---
c.equal(
    "同じ入力からは同じ対象ができる",
    build_target(window),
    PluginTarget(plugin=SFZ, track_name="Inst1", raw_title="Plug-in: sforzando"),
)

raise SystemExit(c.summary())
