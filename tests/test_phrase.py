"""phrase.py のテスト。**ファイルは作らない。** 計画だけを見る。

要点は 1 つ。**あらかじめ変える長さの倍率が、SFZ の再生速度比と
同じであること。** ここが合っていれば、再生時に相殺されて元の長さに戻る。
"""

from _harness import Checker

from core.notes import MIDI_MAX, MIDI_MIN
from core.phrase import (
    PHRASE_SPAN_DEFAULT,
    PHRASE_SPAN_MAX,
    PhraseError,
    phrase_filename,
    plan_phrase,
)

c = Checker("phrase")

SRC = "/Volumes/Audio/Splice/Bass Loop 120.wav"
OUT = "/Volumes/Audio/sfz_slots/rendered"

# ==========================================================================
# 倍率 — ここが本体
# ==========================================================================

plan = plan_phrase(SRC, 60, span=12, out_dir=OUT)
c.equal("上下 12 半音で 25 鍵盤", len(plan.renders), 25)
c.equal("下端", plan.lokey, 48)
c.equal("上端", plan.hikey, 72)
c.equal("ルートキーを覚えている", plan.root_key, 60)

by_key = {r.key: r for r in plan.renders}

# **1 オクターブ上は 2 倍。** SFZ が 2 倍速で鳴らすので、
# あらかじめ 2 倍の長さにしておけば元に戻る。
c.check("1 オクターブ上は 2 倍", abs(by_key[72].tempo_ratio - 2.0) < 1e-9,
        str(by_key[72].tempo_ratio))
c.check("1 オクターブ下は 0.5 倍", abs(by_key[48].tempo_ratio - 0.5) < 1e-9,
        str(by_key[48].tempo_ratio))
c.equal("ルートは 1 倍", by_key[60].tempo_ratio, 1.0)

# 半音ごとに 2^(1/12) 倍
step = 2.0 ** (1 / 12)
for key in range(49, 73):
    want = by_key[key - 1].tempo_ratio * step
    got = by_key[key].tempo_ratio
    if abs(got - want) > 1e-9:
        c.check(f"{key} の倍率が半音ぶん", False, f"期待 {want} / 実際 {got}")
        break
else:
    c.check("半音ごとに 2 の 12 乗根倍", True)

# **相殺されること。** これが目的そのもの。
for r in plan.renders:
    played = r.tempo_ratio / (2.0 ** (r.offset / 12.0))
    if abs(played - 1.0) > 1e-9:
        c.check(f"{r.key} で相殺されない", False, str(played))
        break
else:
    c.check("どの鍵盤でも再生後の長さが元に戻る", True)

# ==========================================================================
# ルートキーはずらさない
# ==========================================================================

c.check(
    "どのゾーンも pitch_keycenter は同じ",
    all(r.root_key == 60 for r in plan.renders),
)
c.equal("ルートだけ加工が要らない", sum(1 for r in plan.renders if r.is_original), 1)
c.equal("作るファイル数", plan.work_count, 24)

# ==========================================================================
# ファイル名 — 同じ素材・同じ半音数なら同じ名前
# ==========================================================================

c.equal(
    "同じ条件なら同じ名前",
    phrase_filename(SRC, 3),
    phrase_filename(SRC, 3),
)
c.check("半音数が違えば別の名前", phrase_filename(SRC, 3) != phrase_filename(SRC, 4))
# **名前だけで決めない。** 別のパックに同じファイル名があると衝突する。
c.check(
    "元のパスが違えば別の名前",
    phrase_filename("/a/Loop.wav", 0) != phrase_filename("/b/Loop.wav", 0),
)
c.check("元の名前が入る", "Bass Loop 120" in phrase_filename(SRC, 0))
c.check("半音数が符号付きで入る", "p+03" in phrase_filename(SRC, 3))
c.check("下は負号で入る", "p-03" in phrase_filename(SRC, -3))
c.check("ルートは +00", "p+00" in phrase_filename(SRC, 0))
c.check("拡張子は wav", phrase_filename(SRC, 0).endswith(".wav"))
# Windows のパスでも名前が取れる
c.check("Windows のパス", "Loop" in phrase_filename(r"C:\Splice\Loop.wav", 0))

# 出力先が付く
c.check("置き場所が前に付く", plan.renders[0].dest.startswith(OUT + "/"))
c.check("末尾のスラッシュは重ねない", "//" not in plan_phrase(SRC, 60, span=1, out_dir=OUT + "/").renders[0].dest)

# ==========================================================================
# 範囲の切り詰め
# ==========================================================================

# **MIDI の外へは作らない。**
low = plan_phrase(SRC, 2, span=12, out_dir=OUT)
c.equal("下端で切り詰める", low.lokey, MIDI_MIN)
c.equal("上端はそのまま", low.hikey, 14)
c.check("鍵盤数が減る", len(low.renders) < 25)

high = plan_phrase(SRC, 125, span=12, out_dir=OUT)
c.equal("上端で切り詰める", high.hikey, MIDI_MAX)
c.equal("下端はそのまま", high.lokey, 113)

# ==========================================================================
# 受け付けない指定
# ==========================================================================

c.raises("空のパス", PhraseError, plan_phrase, "", 60, out_dir=OUT)
c.raises("空白だけのパス", PhraseError, plan_phrase, "   ", 60, out_dir=OUT)
c.raises("ルートキーが範囲外", PhraseError, plan_phrase, SRC, 128, out_dir=OUT)
c.raises("ルートキーが負", PhraseError, plan_phrase, SRC, -1, out_dir=OUT)
c.raises("置き場所が空", PhraseError, plan_phrase, SRC, 60, out_dir="")
c.raises("範囲が 0", PhraseError, plan_phrase, SRC, 60, span=0, out_dir=OUT)
c.raises("範囲が広すぎる", PhraseError, plan_phrase, SRC, 60, span=PHRASE_SPAN_MAX + 1, out_dir=OUT)

# 上限ちょうどは通る
c.equal(
    "上限は通る",
    len(plan_phrase(SRC, 60, span=PHRASE_SPAN_MAX, out_dir=OUT).renders),
    PHRASE_SPAN_MAX * 2 + 1,
)

# ==========================================================================
# 読み上げ
# ==========================================================================

small = plan_phrase(SRC, 60, span=2, out_dir=OUT)
text = small.describe_ja()
c.check("ルートキーを言う", "C3" in text, text)
c.check("範囲を言う", "A#2" in text and "D3" in text, text)
c.check("速さを保つと言う", "速さを変えず" in text, text)
c.check("作る個数を言う", "4個" in text, text)

by = {r.key: r for r in small.renders}
c.check("ルートは元のままと言う", "元のまま" in by[60].describe_ja())
c.check("上は「上」と言う", "上" in by[62].describe_ja(), by[62].describe_ja())
c.check("下は「下」と言う", "下" in by[58].describe_ja(), by[58].describe_ja())
# **「伸ばす」と言わない。** 下へ移すときは縮むので嘘になる
c.check("縮む側で「伸ばす」と言わない", "伸ばす" not in by[58].describe_ja())

c.equal("既定の範囲", PHRASE_SPAN_DEFAULT, 12)

raise SystemExit(c.summary())
