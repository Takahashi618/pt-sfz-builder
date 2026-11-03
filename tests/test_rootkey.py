"""rootkey.py のテスト。ルートキーの決定と、その根拠の伝え方。

ファイル名の解析は実物の `ptcore/splicename.py` を使う。
音からの推定はスタブに差し替える（音声ファイルの読み込みは遅く、
テストで毎回走らせるものではない）。
"""

from _harness import Checker

from core.rootkey import (
    KeyReading,
    decide_root_key,
    pitch_class_to_note,
    read_key_from_filename,
)

c = Checker("rootkey")


class StubAnalyzer:
    """音からの推定を差し替えるスタブ。呼ばれたパスを記録する。"""

    def __init__(self, reading: KeyReading) -> None:
        self.reading = reading
        self.calls: list[str] = []

    def analyze(self, path: str) -> KeyReading:
        self.calls.append(path)
        return self.reading


class FailingAnalyzer:
    """音が読めない状況を作る。"""

    def analyze(self, path: str) -> KeyReading:
        raise OSError("音声ファイルを読めません")


# --- ピッチクラス → MIDI ノート ---
c.equal("C は既定オクターブで 60", pitch_class_to_note(0), 60)
c.equal("A は 69", pitch_class_to_note(9), 69)
c.equal("B は 71（既定オクターブの上端）", pitch_class_to_note(11), 71)
c.equal("octave=1 なら C は 36", pitch_class_to_note(0, 1), 36)
c.raises("12 はピッチクラスの範囲外", ValueError, pitch_class_to_note, 12)
c.raises("-1 はピッチクラスの範囲外", ValueError, pitch_class_to_note, -1)
c.raises("octave=9 は MIDI の範囲を超える", ValueError, pitch_class_to_note, 0, 9)

# --- ファイル名からの読み取り（実物の splicename を使う） ---
reading = read_key_from_filename("Karra Vox Chop 120bpm Cmin.wav")
c.check("Cmin を読み取れる", reading.found)
c.equal("ピッチクラスは 0", reading.pitch_class, 0)
c.equal("マイナーと分かる", reading.quality, "minor")
c.equal("確信度は high", reading.confidence, "high")
c.equal("読み上げラベル", reading.label, "Cマイナー")

c.equal(
    "フラット表記はシャープに正規化される",
    read_key_from_filename("Vocal Loop 124 Dbmin.wav").pitch_class,
    1,
)
c.check("キーの無い名前は found=False", not read_key_from_filename("kick_01.wav").found)

# splicename の既知の癖。先頭の単独キー表記はベンダー略号とみなされる。
# 誤って 'Fx_pack_...' の F をキーと読むより安全なので、そのまま受け入れる。
c.check(
    "先頭の単独キーは prefix と誤認される（既知の癖）",
    not read_key_from_filename("Bb_bass_loop_90.wav").found,
)
c.check(
    "同じ表記でも中間にあれば読める",
    read_key_from_filename("bass_loop_Bb_90.wav").found,
)

# --- ファイル名経路 ---
res = decide_root_key("Karra Vox Chop 120bpm Cmin.wav")
c.equal("ファイル名から決まる", res.source, "filename")
c.equal("C3 になる", res.note, 60)
c.check("警告は出ない", not res.warnings)
c.check("読み上げに音名が入る", "C3" in res.message_ja, res.message_ja)
c.equal("オクターブを下げられる", decide_root_key("Warm Pad Fmin.wav", octave=1).note, 41)

# --- analyzer を渡さなければ音を聴かない ---
silent = StubAnalyzer(KeyReading(9, "minor", "high", "Aマイナー"))
decide_root_key("Karra Vox Chop 120bpm Cmin.wav")
c.check("analyzer なしでは音を聴かない", not silent.calls)

# --- 音からの経路 ---
stub = StubAnalyzer(KeyReading(9, "minor", "high", "Aマイナー"))
res = decide_root_key("kick_01.wav", analyzer=stub)
c.equal("ファイル名が読めなければ音を使う", res.source, "audio")
c.equal("A3 になる", res.note, 69)
c.equal("audio_path 省略時はファイル名を渡す", stub.calls[-1], "kick_01.wav")

stub2 = StubAnalyzer(KeyReading(9, "minor", "high", "Aマイナー"))
decide_root_key("kick_01.wav", audio_path="/tmp/kick.wav", analyzer=stub2)
c.equal("audio_path を渡せばそちらを聴く", stub2.calls[-1], "/tmp/kick.wav")

# --- 食い違いの検出 ---
loud = StubAnalyzer(KeyReading(9, "minor", "high", "Aマイナー"))
res = decide_root_key("Karra Vox Chop 120bpm Cmin.wav", analyzer=loud)
c.equal("確信のあるファイル名を優先する", res.source, "filename")
c.check("音を聴いて照合している", bool(loud.calls))
c.check("食い違いを警告する", any("[警告]" in w for w in res.warnings), str(res.warnings))

quiet = StubAnalyzer(KeyReading(9, "minor", "low", "Aマイナー"))
res = decide_root_key("Karra Vox Chop 120bpm Cmin.wav", analyzer=quiet)
c.check("確信度が低い食い違いは警告しない", not res.warnings, str(res.warnings))

# Cmin の平行調は D#maj。同じ音階なので食い違いとしない。
parallel = StubAnalyzer(KeyReading(3, "major", "high", "D#メジャー"))
res = decide_root_key("Karra Vox Chop 120bpm Cmin.wav", analyzer=parallel)
c.check("平行調は食い違いとしない", not res.warnings, str(res.warnings))
c.equal("ルートキーは主音のまま（平行調へ寄せない）", res.note, 60)

# --- 確信が無くても、値があれば使う ---
weak = StubAnalyzer(KeyReading(7, "minor", "low", "Gマイナー"))
res = decide_root_key("kick_01.wav", analyzer=weak)
c.equal("確信が低くても値があれば採用する", res.source, "audio")
c.equal("G3 になる", res.note, 67)
c.check("確信度の低さを伝える", "確信度は低い" in res.message_ja, res.message_ja)

# --- 何も得られない ---
res = decide_root_key("kick_01.wav")
c.equal("既定に落ちる", res.source, "default")
c.equal("既定は C3", res.note, 60)
c.equal("確信度は none", res.confidence, "none")
c.check("推定できなかったと伝える", "推定できなかった" in res.message_ja, res.message_ja)

# --- 推定器が落ちても作業を止めない ---
res = decide_root_key("kick_01.wav", analyzer=FailingAnalyzer())
c.equal("既定で続行する", res.source, "default")
c.check("失敗を警告する", any("[警告]" in w for w in res.warnings), str(res.warnings))

# --- 読み上げ文言 ---
res = decide_root_key("Karra Vox Chop 120bpm Cmin.wav", analyzer=loud)
c.check("describe_ja は警告まで含む", "[警告]" in res.describe_ja())
c.check(
    "警告が無ければ describe_ja は message_ja と同じ",
    decide_root_key("kick_01.wav").describe_ja() == decide_root_key("kick_01.wav").message_ja,
)

raise SystemExit(c.summary())
