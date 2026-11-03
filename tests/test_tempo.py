"""tempo.py のテスト。**ファイルは作らない。** 判断だけを見る。

要点は 3 つ。

1. **倍率が「元のテンポ ÷ 目標のテンポ」であること**
2. **倍・半分のテンポを考えること**（170 の素材は 85 のセッションにそのまま合う）
3. **分からないときは変えないこと**（推測で伸縮すると気づけない）
"""

from _harness import Checker

from core.tempo import (
    BPM_MAX,
    BPM_MIN,
    decide_tempo,
    read_bpm_from_filename,
    stretch_for,
    tempo_tag,
)

c = Checker("tempo")

LOOP = "91V_HT_145_bass_synth_ballet_reese_Am.wav"
SLOW = "OS_LL_85_Drum_Loop_New_York.wav"
NO_BPM = "kick.wav"

# ==========================================================================
# ファイル名からテンポを読む
# ==========================================================================

reading = read_bpm_from_filename(LOOP)
c.equal("145 を読む", reading.bpm, 145)
c.check("確信度が付く", reading.known)
c.equal("パスでも読める", read_bpm_from_filename("/a/b/" + LOOP).bpm, 145)
c.check("読めなければ known は False", not read_bpm_from_filename(NO_BPM).known)
c.equal("読めなければ None", read_bpm_from_filename(NO_BPM).bpm, None)

# ==========================================================================
# 倍率 — 元のテンポ ÷ 目標のテンポ
# ==========================================================================

d = decide_tempo(LOOP, 128)
c.check("145 から 128 で 1 より大きい", d.ratio > 1)
c.check("倍率が合っている", abs(d.ratio - 145 / 128) < 1e-9, str(d.ratio))
c.equal("元のテンポ", d.source_bpm, 145)
c.equal("目標のテンポ", d.target_bpm, 128)
c.check("変えると分かる", d.changes)
c.check("読み上げに両方のテンポが出る", "145" in d.message_ja and "128" in d.message_ja)
c.check("遅くすると言う", "遅く" in d.message_ja, d.message_ja)

# 素直に計算すると 85/128 = 0.664（縮む）だが、**倍テンポの解釈のほうが
# 1 に近い**（170/128 = 1.328）。伸縮が小さいほうを採る。
fast = decide_tempo(SLOW, 128)
c.check("倍テンポの解釈を採る", fast.doubled, str(fast))
c.check("倍率は 170/128", abs(fast.ratio - 170 / 128) < 1e-9, str(fast.ratio))
c.check("素直な計算より 1 に近い", abs(fast.ratio - 1) < abs(85 / 128 - 1))

# 解釈を止めれば縮む
straight = decide_tempo(SLOW, 128, allow_half_double=False)
c.check("止めれば縮む", straight.ratio < 1, str(straight.ratio))
c.check("倍率は 85/128", abs(straight.ratio - 85 / 128) < 1e-9)

# ==========================================================================
# 倍・半分のテンポ
# ==========================================================================

# **85 の素材は 170 のセッションにそのまま合う。** 倍テンポの解釈。
same = decide_tempo(SLOW, 170)
c.check("倍テンポなら変えない", not same.changes)
c.equal("倍率は 1", same.ratio, 1.0)
# **85 は 170 の「半分」。** 倍にして合わせたので doubled が立つ。
c.check("2 倍とみなしたと分かる", same.doubled)
c.check("そう解釈したと言う", "半分のテンポ" in same.message_ja, same.message_ja)

# 逆向き: 170 の素材を 85 のセッションで使う → 170 は 85 の倍テンポ
double_src = decide_tempo("X_170_loop.wav", 85)
c.check("半分にして合わせる", double_src.halved, str(double_src))
c.check("倍率は 1", abs(double_src.ratio - 1.0) < 1e-9)
c.check("倍テンポと言う", "倍テンポ" in double_src.message_ja, double_src.message_ja)

# 145 を 70 のセッションで使う → 145 を半分（72.5）とみなすほうが近い
half = decide_tempo(LOOP, 70)
c.check("半分の解釈を採る", half.halved)
c.check("引き伸ばしが小さい", abs(half.ratio - 1) < 0.1, str(half.ratio))
c.check("そう解釈したと言う", "半分" in half.message_ja, half.message_ja)
# **整数に丸めない。** 145 の半分は 72.5
c.check("72.5 と言う", "72.5" in half.message_ja, half.message_ja)

# 解釈を止めれば素直に計算する
plain = decide_tempo(LOOP, 70, allow_half_double=False)
c.check("止めれば 2 倍以上になる", plain.ratio > 2, str(plain.ratio))
c.check("大きな伸縮は警告する", any("荒れる" in w for w in plain.warnings), str(plain.warnings))

# --------------------------------------------------------------------------
# **荒れない範囲に収まっているなら、素直な倍率を使う。**
# --------------------------------------------------------------------------
#
# 1 への近さだけで選んでいたときは、90 のループを 128 のセッションへ
# 入れると「180 とみなして遅くする」を採っていた。速めたい素材が
# 半分の速さで鳴る（2026-09-05 のレビューで判明）。

up = decide_tempo("Hip Hop Loop 90bpm Amin.wav", 128)
c.check("90 から 128 は速くする", up.ratio < 1.0, str(up.ratio))
c.check("倍テンポとみなさない", not up.doubled and not up.halved, str(up))
c.check("倍率は 90/128", abs(up.ratio - 90 / 128) < 1e-9, str(up.ratio))
c.check("速くすると言う", "速く" in up.message_ja, up.message_ja)
c.check("荒れる警告は出さない", not up.warnings, str(up.warnings))

# 100 を 150 へ（ちょうど範囲の端）も素直に速くする
edge = decide_tempo("X_100_loop.wav", 150)
c.check("端でも素直に速くする", abs(edge.ratio - 100 / 150) < 1e-9, str(edge.ratio))
c.check("端でも読み替えない", not edge.doubled and not edge.halved, str(edge))

# 範囲の外へ出て初めて読み替える
outside = decide_tempo("X_200_loop.wav", 128)
c.check("範囲の外なら読み替える", outside.halved, str(outside))
c.check("読み替えれば範囲に収まる", abs(outside.ratio - 100 / 128) < 1e-9, str(outside.ratio))

# ==========================================================================
# 変えない場合
# ==========================================================================

c.check("目標が無ければ変えない", not decide_tempo(LOOP, None).changes)
c.check("目標が無いと言う", "変えません" in decide_tempo(LOOP, None).message_ja)

unknown = decide_tempo(NO_BPM, 128)
c.check("元が分からなければ変えない", not unknown.changes)
c.check("理由を言う", "読めなかった" in unknown.describe_ja(), unknown.describe_ja())

# 同じテンポなら変えない
c.check("同じなら変えない", not decide_tempo(LOOP, 145).changes)

# 範囲外
out = decide_tempo(LOOP, BPM_MAX + 1)
c.check("目標が範囲外なら変えない", not out.changes)
c.check("警告を出す", any("範囲外" in w for w in out.warnings), str(out.warnings))
c.check("下限より下も弾く", not decide_tempo(LOOP, BPM_MIN - 1).changes)

# 元のテンポを指定できる（ファイル名より優先）
override = decide_tempo(NO_BPM, 128, source_bpm=160)
c.check("指定した元のテンポを使う", override.changes)
c.equal("指定値が入る", override.source_bpm, 160)
c.check("倍率が合う", abs(override.ratio - 160 / 128) < 1e-9)

# ==========================================================================
# ファイル名の印
# ==========================================================================

c.equal("変えないなら印は空", tempo_tag(decide_tempo(LOOP, None)), "")
c.equal("元と目標の両方が入る", tempo_tag(decide_tempo(LOOP, 128)), "b145to128")
# **片方だけだと取り違える。** 元のテンポを指定し直したとき、
# 古い下ごしらえを使い回してしまう。
c.check(
    "元が違えば別の印",
    tempo_tag(decide_tempo(NO_BPM, 128, source_bpm=160))
    != tempo_tag(decide_tempo(NO_BPM, 128, source_bpm=150)),
)

# ==========================================================================
# 伸縮 1 件分
# ==========================================================================

r = stretch_for("/a/loop.wav", decide_tempo(LOOP, 128), "/out")
c.check("加工が要る", not r.is_original)
c.check("出力先は置き場所の中", r.dest.startswith("/out/"))
c.check("印が名前に入る", "b145to128" in r.dest, r.dest)
c.check("倍率が入る", abs(r.tempo_ratio - 145 / 128) < 1e-9)

# **変えないなら元のファイルをそのまま指す。** 同じ中身のコピーを作らない。
same_r = stretch_for("/a/loop.wav", decide_tempo(LOOP, None), "/out")
c.check("加工は要らない", same_r.is_original)
c.equal("元をそのまま指す", same_r.dest, "/a/loop.wav")
c.equal("倍率は 1", same_r.tempo_ratio, 1.0)
c.check("読み上げは元のまま", "元のまま" in same_r.describe_ja())

# `render_phrase` が扱える形か（source / dest / tempo_ratio）
for name in ("source", "dest", "tempo_ratio"):
    c.check(f"{name} を持つ", hasattr(r, name))

raise SystemExit(c.summary())
