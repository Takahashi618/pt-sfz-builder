"""tone.py のテスト。単位の取り違えと、リリース下限の強制。

`ampeg_sustain` を dB と取り違えると無音になる。ここで型と範囲を固定しておく。
"""

from _harness import Checker

from core.sfz import SfzError
from core.tone import (
    PRESETS,
    RELEASE_MIN_SEC,
    ToneSettings,
    get_preset,
    preset_names,
)

c = Checker("tone")


def opcodes_of(tone: ToneSettings) -> dict[str, str]:
    return {op.name: op.value for op in tone.to_opcodes()}


# --- 既定値 ---
default = ToneSettings()
c.equal("既定でフィルターは無し", default.cutoff, None)
c.equal("既定のサステインは 100 パーセント", default.sustain, 100.0)

# --- 範囲の検証。単位を取り違えたら通さない ---
c.raises("サステイン 101 は範囲外", SfzError, ToneSettings, 0.001, 0.0, 101.0)
c.raises("サステイン -6 は範囲外（dB のつもりの値）", SfzError, ToneSettings, 0.001, 0.0, -6.0)
c.raises("アタック 101 秒は範囲外", SfzError, ToneSettings, 101.0)
c.raises("カットオフ 10Hz は範囲外", SfzError, lambda: ToneSettings(cutoff=10.0))
c.raises("カットオフ 30000Hz は範囲外", SfzError, lambda: ToneSettings(cutoff=30000.0))
c.raises("レゾナンス 50dB は範囲外", SfzError, lambda: ToneSettings(resonance=50.0))
c.raises("知らないフィルター種別", SfzError, lambda: ToneSettings(fil_type="moog_ladder"))

# --- リリース下限。0 だと鍵盤を離した瞬間にクリックノイズが出る ---
c.equal("リリース 0 は下限へ引き上げる", ToneSettings(release=0.0).normalized().release, RELEASE_MIN_SEC)
c.equal("下限以上はそのまま", ToneSettings(release=0.5).normalized().release, 0.5)
c.equal("書き出しにも下限が効く", opcodes_of(ToneSettings(release=0.0))["ampeg_release"], "0.02")

# --- 書き出すオプコード ---
ops = opcodes_of(ToneSettings())
c.check("ADSR の 4 つが出る", {"ampeg_attack", "ampeg_decay", "ampeg_sustain", "ampeg_release"} <= set(ops))
c.check("cutoff=None ならフィルターを書かない", "cutoff" not in ops and "fil_type" not in ops)
c.check("hold=0 なら ampeg_hold を書かない", "ampeg_hold" not in ops)

ops_f = opcodes_of(ToneSettings(cutoff=800.0, resonance=3.0, hold=0.5))
c.equal("cutoff が Hz で出る", ops_f["cutoff"], "800")
c.equal("fil_type が出る", ops_f["fil_type"], "lpf_2p")
c.equal("resonance が dB で出る", ops_f["resonance"], "3")
c.equal("hold>0 なら書く", ops_f["ampeg_hold"], "0.5")
c.check("resonance=0 なら書かない", "resonance" not in opcodes_of(ToneSettings(cutoff=800.0)))

# --- 読み上げ。単位を言葉にする ---
desc = ToneSettings(cutoff=800.0).describe_ja()
c.check("サステインに単位が付く", "パーセント" in desc, desc)
c.check("秒に単位が付く", "秒" in desc, desc)
c.check("カットオフに単位が付く", "ヘルツ" in desc, desc)
c.check("フィルター無しは明示する", "フィルターなし" in ToneSettings().describe_ja())

# --- プリセット ---
c.check("プリセットが 1 つ以上ある", len(PRESETS) >= 1)
c.check(
    "全プリセットが読み上げ可能",
    all(get_preset(name).describe_ja() for name in preset_names()),
)
c.check(
    "全プリセットのリリースが下限以上",
    all(get_preset(n).normalized().release >= RELEASE_MIN_SEC for n in preset_names()),
)
c.raises("知らないプリセット名", SfzError, get_preset, "存在しない名前")

raise SystemExit(c.summary())
