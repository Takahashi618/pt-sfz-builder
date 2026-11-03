"""MIDI ノート番号と音名の相互変換。

C3 = 60（ヤマハ式）を基準にする。Pro Tools と Kontakt の既定表記に合わせたもの。

**SFZ には音名表記を書かない。** `pitch_keycenter=c4` の `c4` が 60 か 72 かは
実装によって割れるため、SFZ へ出すのは常に数値にする。この変換は
**読み上げと利用者入力の解釈だけ**に使う。

OS 非依存。文字列と整数の計算だけなので Windows でテストできる。
"""

from __future__ import annotations

import re

__all__ = [
    "MIDI_MIN",
    "MIDI_MAX",
    "MIDDLE_C_NOTE",
    "MIDDLE_C_OCTAVE",
    "NOTE_NAMES",
    "note_name",
    "parse_note_name",
]

# 表示に使う音名。フラットは受け取るが、返すのは常にシャープ表記に統一する。
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

MIDI_MIN = 0
MIDI_MAX = 127
MIDDLE_C_NOTE = 60
MIDDLE_C_OCTAVE = 3

_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# 例: "C3" "C#4" "Bb2" "A-1"。オクターブは負値もありうる（C-2 = 0）。
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def note_name(note: int) -> str:
    """MIDI ノート番号を音名表記にする。C3 = 60。

    読み上げで「60」ではなく「C3」と言えるようにするためのもの。

    >>> note_name(60)
    'C3'
    >>> note_name(36)
    'C1'
    """
    if not MIDI_MIN <= note <= MIDI_MAX:
        raise ValueError(f"MIDI ノート番号が範囲外です: {note}")
    octave = (note - MIDDLE_C_NOTE) // 12 + MIDDLE_C_OCTAVE
    return f"{NOTE_NAMES[note % 12]}{octave}"


def parse_note_name(name: str) -> int:
    """音名表記を MIDI ノート番号にする。note_name の逆変換。

    フラット表記も受け付ける（Splice のファイル名に `Bb` `Db` が現れるため）。
    返すのは常に数値なので、以降の処理で表記ゆれを気にしなくてよい。

    >>> parse_note_name("C3")
    60
    >>> parse_note_name("Bb2")
    58
    >>> parse_note_name("A#2")
    58
    """
    text = name.strip().replace("♯", "#").replace("♭", "b")
    matched = _NOTE_RE.match(text)
    if matched is None:
        raise ValueError(f"音名として解釈できません: {name!r}")

    letter, accidental, octave_text = matched.groups()
    semitone = _PITCH_CLASS[letter.upper()]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1

    note = semitone + (int(octave_text) - MIDDLE_C_OCTAVE) * 12 + MIDDLE_C_NOTE
    if not MIDI_MIN <= note <= MIDI_MAX:
        # Cb-2 や B#8 のように、表記は正しいが MIDI の範囲外になる場合がある
        raise ValueError(f"MIDI ノート番号が範囲外です: {name!r} -> {note}")
    return note
