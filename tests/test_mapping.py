"""mapping.py のテスト。クロマティック配置とドラムキット配置。

主用途はクロマティック。ドラムは副用途だが、`key=` 短縮形を使うので
別経路として検証する。
"""

from _harness import Checker

from core.mapping import (
    DEFAULT_DRUM_START,
    DEFAULT_ROOT_KEY,
    DrumEntry,
    Instrument,
    Zone,
    build_chromatic,
    build_drumkit,
    to_sfz,
)
from core.sfz import SfzError, parse, render
from core.tone import ToneSettings

c = Checker("mapping")

STAMP = "2026-09-01T00:00:00+00:00"  # 固定して往復比較を可能にする


def region_opcodes(doc, index=0):
    return {op.name: op.value for op in doc.regions[index].opcodes}


# --- Zone の検証 ---
c.raises("lokey > hikey は不正", SfzError, Zone, "/a.wav", 60, 50, 60)
c.raises("範囲外のノート", SfzError, Zone, "/a.wav", 0, 128, 60)
c.raises("空のパス", SfzError, Zone, "  ", 0, 127, 60)
c.check("1 鍵盤なら is_single_key", Zone("/a.wav", 36, 36, 36).is_single_key)
c.check("幅があれば is_single_key でない", not Zone("/a.wav", 0, 127, 60).is_single_key)
c.raises("ゾーンが空の Instrument は不正", SfzError, Instrument, [])

# --- クロマティック（主用途） ---
inst = build_chromatic("/Volumes/Audio/Splice/Vox Chop C min.wav", name="Vox Chop")
c.equal("ゾーンは 1 つ", len(inst.zones), 1)
c.equal("既定のルートキーは C3", inst.zones[0].root_key, DEFAULT_ROOT_KEY)
c.equal("既定は全鍵盤（下端）", inst.zones[0].lokey, 0)
c.equal("既定は全鍵盤（上端）", inst.zones[0].hikey, 127)
c.check("クロマティックは one_shot にしない", not inst.zones[0].one_shot)

doc = to_sfz(inst, generated_at=STAMP)
ops = region_opcodes(doc)
c.equal("lokey が出る", ops["lokey"], "0")
c.equal("hikey が出る", ops["hikey"], "127")
c.equal("pitch_keycenter が出る", ops["pitch_keycenter"], "60")
c.equal("loop_mode は no_loop", ops["loop_mode"], "no_loop")
c.check("key= 短縮形は使わない", "key" not in ops)
c.equal("サンプルのパスが入る", doc.regions[0].sample, "/Volumes/Audio/Splice/Vox Chop C min.wav")
c.check("ADSR が <global> に出る", any(op.name == "ampeg_release" for op in doc.global_opcodes))

# --- ルートキーと範囲の指定 ---
narrow = build_chromatic("/a.wav", 48, lokey=36, hikey=60)
c.equal("ルートキーを指定できる", narrow.zones[0].root_key, 48)
c.equal("下端を指定できる", narrow.zones[0].lokey, 36)
c.equal("上端を指定できる", narrow.zones[0].hikey, 60)

# --- ドラムキット（副用途） ---
kit = build_drumkit(["/a/kick.wav", "/a/snare 01.wav", "/a/hat.wav"])
c.equal("ゾーンは 3 つ", len(kit.zones), 3)
c.equal("開始ノートは C1", kit.zones[0].root_key, DEFAULT_DRUM_START)
c.equal("半音ずつ上がる", kit.zones[1].root_key, DEFAULT_DRUM_START + 1)
c.check("ドラムは one_shot", all(z.one_shot for z in kit.zones))
c.check("各ゾーンは 1 鍵盤", all(z.is_single_key for z in kit.zones))

kit_doc = to_sfz(kit, generated_at=STAMP)
kit_ops = region_opcodes(kit_doc)
c.equal("key= 短縮形を使う", kit_ops["key"], "36")
c.check("lokey/hikey は書かない（key= に含まれる）", "lokey" not in kit_ops and "hikey" not in kit_ops)
c.equal("loop_mode は one_shot", kit_ops["loop_mode"], "one_shot")
c.equal("スペース入りのパスも保つ", kit_doc.regions[1].sample, "/a/snare 01.wav")

# --- ラベル付きエントリ ---
labeled = build_drumkit([DrumEntry("/a/kick.wav", "キック")], start_note=60)
c.check("ラベルが読み上げに出る", "キック" in labeled.zones[0].describe_ja())
c.check("音名が読み上げに出る", "C3" in labeled.zones[0].describe_ja())

# --- 境界 ---
c.raises("空のリストは不正", SfzError, build_drumkit, [])
c.raises(
    "鍵盤の上端を超える配置は拒む",
    SfzError,
    lambda: build_drumkit(["/a.wav"] * 4, start_note=125),
)
c.check("ちょうど上端まではよい", len(build_drumkit(["/a.wav"] * 3, start_note=125).zones) == 3)

# --- 決定性と往復 ---
c.equal(
    "generated_at を固定すれば出力は決定的",
    render(to_sfz(inst, generated_at=STAMP)),
    render(to_sfz(inst, generated_at=STAMP)),
)
c.equal("生成 → 描画 → 解析で往復する", parse(render(doc)), doc)
c.equal("ドラムキットも往復する", parse(render(kit_doc)), kit_doc)

# --- 音作りの引き継ぎ ---
with_tone = build_chromatic("/a.wav", tone=ToneSettings(cutoff=800.0))
tone_ops = {op.name: op.value for op in to_sfz(with_tone, generated_at=STAMP).global_opcodes}
c.equal("ToneSettings が <global> に反映される", tone_ops["cutoff"], "800")

raise SystemExit(c.summary())
