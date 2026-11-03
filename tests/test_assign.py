"""assign.py のテスト。割り当て計画の全分岐。

Pro Tools も macOS も無い状態で、判断が正しいかを確かめる。
`.sfz` の中身まで計画に入っているので、書き出す前に内容を検証できる。
"""

from _harness import Checker

from core.assign import (
    AssignPlan,
    AssignRequest,
    SampleRef,
    commit_assignment,
    describe_success_ja,
    plan_assignment,
)
from core.mapping import MODE_CHROMATIC, MODE_DRUMKIT
from core.rootkey import KeyReading
from core.slots import PluginKind, SlotLayout, SlotLedger
from core.target import PluginTarget
from core.tone import get_preset

c = Checker("assign")

SFZ = PluginKind.SFORZANDO
STAMP = "2026-09-01T00:00:00+00:00"

TARGET = PluginTarget(plugin=SFZ, track_name="Inst1", raw_title="Plug-in: sforzando")
VOX = SampleRef("/Volumes/Audio/Splice/Karra Vox Chop 120bpm Cmin.wav")


def fresh_ledger(slot_count: int = 4) -> SlotLedger:
    layout = SlotLayout(slots_dir="/Volumes/Audio/sfz_slots", slot_count=slot_count)
    return SlotLedger.create(layout, plugins=[SFZ])


def plan(**kwargs):
    """既定の要求で計画を立てる。ledger も返す。"""
    ledger = kwargs.pop("ledger", None) or fresh_ledger()
    request = AssignRequest(
        target=kwargs.pop("target", TARGET),
        samples=kwargs.pop("samples", [VOX]),
        **kwargs,
    )
    return plan_assignment(request, ledger, generated_at=STAMP), ledger


class StubAnalyzer:
    def __init__(self, reading: KeyReading) -> None:
        self.reading = reading

    def analyze(self, path: str) -> KeyReading:
        return self.reading


# --- 正常系（クロマティック） ---
result, ledger = plan()
c.check("計画が立つ", result.ok, result.message_ja)
c.equal("スロット 1 が使われる", result.slot.number, 1)
c.equal("ファイル名からルートキーが決まる", result.root_key, 60)
c.equal(
    "出力先のパス",
    result.sfz_path,
    "/Volumes/Audio/sfz_slots/slot01.sfz",
)
c.equal("設定名", result.setting_name, "SLOT_01")
c.check("SFZ の中身まで作る", result.sfz_text is not None)
c.check("サンプルのパスが SFZ に入る", VOX.path in result.sfz_text)
c.check("sample= は行の最後", result.sfz_text.rstrip().endswith(VOX.path))
c.check("全鍵盤に広がる", "lokey=0" in result.sfz_text and "hikey=127" in result.sfz_text)
c.check("ルートキーが数値で入る", "pitch_keycenter=60" in result.sfz_text)
c.check("読み上げに音名が出る", "C3" in result.message_ja, result.message_ja)
c.check("注意は無い", not result.notes, str(result.notes))

# --- 台帳は計画では動かない。書けてから載せる ---
#
# **中止したときに台帳が動いていないこと**が要る。動いていると、
# 実体の無い音色が台帳に残り、スロットも埋まったままになる。
c.equal("計画だけでは結び付けない", ledger.get(SFZ, 1).track_name, None)
c.equal("計画だけでは種別も入らない", ledger.get(SFZ, 1).mode, None)
c.check("スロットは空きのまま", ledger.get(SFZ, 1).is_free)

commit_assignment(result, ledger)
c.equal("載せると台帳にトラック名が入る", ledger.get(SFZ, 1).track_name, "Inst1")
c.equal("種別が記録される", ledger.get(SFZ, 1).mode, MODE_CHROMATIC)
c.check("完了時の読み上げは過去形", "割り当てました" in describe_success_ja(result))

# 中止した計画は載せない
stopped = AssignPlan(ok=False, message_ja="[警告] 駄目")
c.equal("中止した計画は載らない", commit_assignment(stopped, ledger), None)

# --- ルートキーの明示指定 ---
result, _ = plan(root_key=67)
c.equal("指定値が使われる", result.root_key, 67)
c.check("指定値と読み上げる", "指定値" in result.message_ja, result.message_ja)
c.check("SFZ にも入る", "pitch_keycenter=67" in result.sfz_text)

result, _ = plan(root_key=200)
c.check("範囲外は中止する", not result.ok)
c.check("エラー接頭辞を付ける", result.message_ja.startswith("[エラー]"), result.message_ja)

# --- オクターブ指定 ---
result, _ = plan(octave=1)
c.equal("オクターブを下げられる", result.root_key, 36)

# --- 音からの推定を使う ---
result, _ = plan(
    samples=[SampleRef("/a/kick_01.wav")],
    analyzer=StubAnalyzer(KeyReading(9, "minor", "high", "Aマイナー")),
)
c.equal("ファイル名が読めなければ音を使う", result.root_key, 69)

# --- 食い違いの注意が引き継がれる ---
result, _ = plan(analyzer=StubAnalyzer(KeyReading(9, "minor", "high", "Aマイナー")))
c.check("ルートキーの警告が計画に載る", any("[警告]" in n for n in result.notes), str(result.notes))

# --- 対応していない形式 ---
result, _ = plan(samples=[SampleRef("/a/loop.mp3")])
c.check("mp3 は中止する", not result.ok)
c.check("警告接頭辞", result.message_ja.startswith("[警告]"), result.message_ja)
c.check("使える形式を伝える", "wav" in result.message_ja)

result, _ = plan(samples=[SampleRef("/a/noext")])
c.check("拡張子なしも中止する", not result.ok)

result, _ = plan(samples=[SampleRef("/a/a.wav"), SampleRef("/a/b.mp3")], mode=MODE_DRUMKIT)
c.check("1 つでも駄目なら中止する", not result.ok)

# --- サンプルが無い ---
result, _ = plan(samples=[])
c.check("空なら中止する", not result.ok)

# --- クロマティックに複数渡した ---
result, _ = plan(samples=[VOX, SampleRef("/a/b.wav"), SampleRef("/a/c.wav")])
c.check("実行はする", result.ok)
c.check("先頭だけ使うと伝える", any("先頭の1個" in n for n in result.notes), str(result.notes))
c.check("先頭のパスが入る", VOX.path in result.sfz_text)

# --- ドラムキット ---
result, _ = plan(
    samples=[SampleRef("/a/kick.wav"), SampleRef("/a/snare 01.wav"), SampleRef("/a/hat.wav")],
    mode=MODE_DRUMKIT,
)
c.check("計画が立つ", result.ok, result.message_ja)
c.check("key= 短縮形を使う", "key=36" in result.sfz_text)
c.check("one_shot になる", "loop_mode=one_shot" in result.sfz_text)
c.check("開始ノートを読み上げる", "C1" in result.message_ja, result.message_ja)
c.check("スペース入りのパスが壊れない", "/a/snare 01.wav" in result.sfz_text)

result, _ = plan(
    samples=[SampleRef(f"/a/{i}.wav") for i in range(4)],
    mode=MODE_DRUMKIT,
    start_note=125,
)
c.check("鍵盤の上端を超えたら中止する", not result.ok)
c.check("理由を伝える", "上端" in result.message_ja, result.message_ja)

# --- ドラムキットでもテンポの判断を読み上げる ---
#
# **黙っていると「合わせたつもり」で使い続けることになる。**
# 以前はドラムキットの分岐だけ `_note_tempo` を通さず、
# 「読めなかった」も「[警告] N 倍まで伸縮します」も捨てていた。

result, _ = plan(
    samples=[SampleRef("/a/kick.wav"), SampleRef("/a/snare.wav")],
    mode=MODE_DRUMKIT,
    target_bpm=128,
)
c.check("読めなかったことを伝える", result.notes, str(result.notes))
c.check(
    "何個読めなかったか言う",
    any("2個は元のテンポ" in n for n in result.notes),
    str(result.notes),
)

result, _ = plan(
    samples=[SampleRef("/a/Loop 90bpm.wav"), SampleRef("/a/kick.wav")],
    mode=MODE_DRUMKIT,
    target_bpm=128,
)
c.check(
    "合わせた数を言う",
    any("1個をセッションのテンポに合わせます" in n for n in result.notes),
    str(result.notes),
)
c.check(
    "合わせなかった分も言う",
    any("1個は元のテンポ" in n for n in result.notes),
    str(result.notes),
)

# **ワンショットは伸縮しない。** 名前に BPM が入っていても、
# 1 発ものの長さを変えると音そのものが変わる。
result, _ = plan(
    samples=[
        SampleRef("/a/OS_Snare_One_Shot_90.wav", kind="one_shot"),
        SampleRef("/a/Loop 90bpm.wav"),
    ],
    mode=MODE_DRUMKIT,
    target_bpm=128,
)
c.check(
    "ワンショットはそのままだと言う",
    any("ワンショットなので" in n for n in result.notes),
    str(result.notes),
)
c.check(
    "ワンショットは元のパスを指す",
    "/a/OS_Snare_One_Shot_90.wav" in result.sfz_text,
    result.sfz_text,
)
c.equal("下ごしらえはループの 1 個だけ", len(result.renders), 1)

# 大きな伸縮の警告も落とさない
result, _ = plan(
    samples=[SampleRef("/a/Loop 60bpm.wav")],
    mode=MODE_DRUMKIT,
    target_bpm=128,
    allow_half_double=False,
)
c.check(
    "荒れる警告を伝える",
    any("荒れる" in n for n in result.notes),
    str(result.notes),
)

# --- 空きスロットが尽きる ---
small = fresh_ledger(slot_count=1)
first, _ = plan(ledger=small)
# **埋まるのは載せてから。** 計画を立てただけでは埋まらない。
commit_assignment(first, small)
result = plan_assignment(
    AssignRequest(
        target=PluginTarget(plugin=SFZ, track_name="Inst2"), samples=[VOX]
    ),
    small,
    generated_at=STAMP,
)
c.check("空きが無ければ中止する", not result.ok)
c.check("解除を促す", "解除" in result.message_ja, result.message_ja)

# --- 曖昧なトラック名 ---
risky = PluginTarget(plugin=SFZ, track_name="Kick", insert_slot="a", ambiguous=True)
result, _ = plan(target=risky)
c.check("実行はする", result.ok)
c.check("曖昧さを警告する", any("曖昧" in n for n in result.notes), str(result.notes))

# --- ループ素材の注意 ---
result, _ = plan(samples=[SampleRef(VOX.path, kind="loop")])
c.check("速さが変わると伝える", any("速さも変わります" in n for n in result.notes), str(result.notes))
result, _ = plan(samples=[SampleRef(VOX.path, kind="one_shot")])
c.check("ワンショットには言わない", not any("速さ" in n for n in result.notes))

# --- 音作りが SFZ に載る ---
result, _ = plan(tone=get_preset("こもらせる"))
c.check("フィルターが入る", "cutoff=800" in result.sfz_text)

# --- known_slot_number は台帳より優先 ---
ledger = fresh_ledger()
result = plan_assignment(
    AssignRequest(target=TARGET, samples=[VOX], known_slot_number=3),
    ledger,
    generated_at=STAMP,
)
c.equal("指定されたスロットを使う", result.slot.number, 3)
c.check("パスも追随する", result.sfz_path.endswith("slot03.sfz"), result.sfz_path)

# --- 決定性 ---
a, _ = plan()
b, _ = plan()
c.equal("同じ入力なら同じ SFZ になる", a.sfz_text, b.sfz_text)

# --- 中止時は台帳を汚さない ---
clean = fresh_ledger()
plan_assignment(
    AssignRequest(target=TARGET, samples=[SampleRef("/a/x.mp3")]), clean, generated_at=STAMP
)
c.check("失敗しても結び付きは残らない", all(s.is_free for s in clean.slots_of(SFZ)))


# --- 書き出せない名前でも、例外で止まらない（2026-10-25）---
#
# `.sfz` は 1 行 1 オプコード。名前やパスに改行があると `SfzDocument` が
# `SfzError` を投げる。ここだけ計画の try の外にあったので、画面まで
# 素通りして読み上げ無しで止まっていた。
weird = SampleRef("/a/行が\n分かれた.wav")
result, weird_ledger = plan(samples=[weird])
c.check("改行のある名前は中止する", not result.ok)
c.check("理由を言う", "改行" in result.message_ja, result.message_ja)
c.check("台帳は汚さない", all(s.is_free for s in weird_ledger.slots_of(SFZ)))


# --- ルートキーをどう決めたかは、割り当てたあとにも言う（2026-10-25）---
#
# 計画の文にしか入っていなかったので、既定値に落ちたときの
# 「鳴らして確かめてください」が割り当ての結果では消えていた。
result, _ = plan(samples=[SampleRef("/a/no_key_here.wav")])
c.check("自動で決めたら言う", "既定値" in result.root_note, result.root_note)
result, _ = plan(root_key=62)
c.equal("自分で決めた値は言い直さない", result.root_note, "")
result, _ = plan(mode=MODE_DRUMKIT, samples=[VOX, SampleRef("/a/k.wav")])
c.equal("ドラムキットはルートキーを使わない", result.root_note, "")

raise SystemExit(c.summary())
