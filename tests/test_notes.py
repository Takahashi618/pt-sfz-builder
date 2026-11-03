"""notes.py のテスト。音名と MIDI ノート番号の変換。

ここがずれると全部がずれるので、基準点を明示的に固定しておく。
"""

from _harness import Checker

from core.notes import MIDI_MAX, MIDI_MIN, note_name, parse_note_name

c = Checker("notes")

# --- 基準点。C3 = 60（ヤマハ式）を動かさない ---
c.equal("60 は C3", note_name(60), "C3")
c.equal("36 は C1（GM のキック位置）", note_name(36), "C1")
c.equal("0 は C-2", note_name(0), "C-2")
c.equal("127 は G8", note_name(127), "G8")
c.equal("61 は C#3", note_name(61), "C#3")

# --- 逆変換 ---
c.equal("'C3' は 60", parse_note_name("C3"), 60)
c.equal("小文字 'c3' も 60", parse_note_name("c3"), 60)
c.equal("前後の空白を無視する", parse_note_name("  C3 "), 60)
c.equal("'C#3' は 61", parse_note_name("C#3"), 61)
c.equal("'C-2' は 0", parse_note_name("C-2"), 0)

# --- フラット表記。Splice のファイル名に実在する ---
c.equal("'Bb2' は 58", parse_note_name("Bb2"), 58)
c.equal("'A#2' も 58（異名同音）", parse_note_name("A#2"), 58)
c.equal("'Db3' は 61", parse_note_name("Db3"), 61)
c.equal("全角シャープ '♯' を受ける", parse_note_name("C♯3"), 61)
c.equal("全角フラット '♭' を受ける", parse_note_name("B♭2"), 58)

# --- オクターブ境界をまたぐ異名同音 ---
c.equal("'Cb3' は 59（B2 と同じ）", parse_note_name("Cb3"), 59)
c.equal("'B#3' は 72（C4 と同じ）", parse_note_name("B#3"), 72)

# --- 往復。表記ゆれを吸収しても元の番号に戻ること ---
c.check(
    "全 128 音で往復する",
    all(parse_note_name(note_name(n)) == n for n in range(MIDI_MIN, MIDI_MAX + 1)),
)

# --- 範囲外・不正入力は黙って通さない ---
c.raises("128 は範囲外", ValueError, note_name, 128)
c.raises("-1 は範囲外", ValueError, note_name, -1)
c.raises("'H3' は音名でない", ValueError, parse_note_name, "H3")
c.raises("'C' はオクターブが無い", ValueError, parse_note_name, "C")
c.raises("空文字は解釈できない", ValueError, parse_note_name, "")
c.raises("'C9' は MIDI の範囲を超える", ValueError, parse_note_name, "C9")
c.raises("'Cb-2' は下限を割る", ValueError, parse_note_name, "Cb-2")

raise SystemExit(c.summary())
