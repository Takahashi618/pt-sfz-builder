"""ルートキー（`pitch_keycenter`）の決定。

クロマティック演奏では、ここが正しくないと「C の鍵盤を押したのに C# が鳴る」
ことになる。段階的に落とす。

    1. ファイル名から読む   splicename.parse() の pitch_class
         ↓ 取れない、または確信度が低い
    2. 音を聴いて推定する   keydetect.detect_key()
         ↓ 推定にも確信が無い
    3. 既定 C3(60) を使い、「推定できなかった」と伝える

**オクターブは決められない。** ファイル名の「Cmin」にも、音から求めるクロマ
（12 ピッチクラスに畳んだ分布）にも、オクターブの情報が無い。既定では C3 の
オクターブ（60〜71）に収め、利用者が変えられるようにしてある。

借りている部品への依存は関数の中で解決する。見つからなくても落ちず、
ファイル名からの読み取りを諦めるだけにする。
"""

from __future__ import annotations

from .i18n import tr

from dataclasses import dataclass, field
from typing import Any, Protocol

from .sibling import load_ptcore, part_key_label, part_message
from .notes import MIDDLE_C_NOTE, MIDDLE_C_OCTAVE, MIDI_MAX, MIDI_MIN, note_name

__all__ = [
    "DEFAULT_OCTAVE",
    "CONFIDENT",
    "KeyReading",
    "RootKeyResult",
    "KeyAnalyzer",
    "SpliceKeyAnalyzer",
    "pitch_class_to_note",
    "read_key_from_filename",
    "decide_root_key",
]

# C3 の属するオクターブ。pitch_class 0〜11 が MIDI 60〜71 に載る。
DEFAULT_OCTAVE = MIDDLE_C_OCTAVE

# splicename / keydetect と語彙を合わせてある（"high" / "medium" / "low" / "none"）。
CONFIDENT = frozenset({"high", "medium"})


@dataclass(frozen=True)
class KeyReading:
    """キーの読み取り結果。

    ファイル名から読んでも音から推定しても同じ形にする。こうしておくと
    `decide_root_key` が両者を同じ手続きで扱える。
    """

    pitch_class: int | None = None
    quality: str | None = None  # "major" / "minor" / None
    confidence: str = "none"
    label: str = tr("不明", "unknown")
    note_ja: str = ""  # 読み取れなかった理由など

    @classmethod
    def unknown(cls, note_ja: str = "") -> "KeyReading":
        return cls(note_ja=note_ja)

    @property
    def found(self) -> bool:
        return self.pitch_class is not None

    @property
    def is_confident(self) -> bool:
        return self.found and self.confidence in CONFIDENT


@dataclass(frozen=True)
class RootKeyResult:
    """決まったルートキーと、その根拠。"""

    note: int
    source: str  # "filename" / "audio" / "default"
    confidence: str
    label: str
    message_ja: str
    warnings: tuple[str, ...] = field(default=())

    def describe_ja(self) -> str:
        """警告まで含めた読み上げ文言。"""
        if not self.warnings:
            return self.message_ja
        return self.message_ja + " " + " ".join(self.warnings)


class KeyAnalyzer(Protocol):
    """音を聴いてキーを推定するもの。

    実装を差し替えられるようにしてあるのは、音声ファイルの読み込みが遅く、
    テストで毎回走らせたくないため。Windows のテストではスタブを注入する。
    """

    def analyze(self, path: str) -> KeyReading: ...


# --------------------------------------------------------------------------
# ピッチクラス → MIDI ノート番号
# --------------------------------------------------------------------------


def pitch_class_to_note(pitch_class: int, octave: int = DEFAULT_OCTAVE) -> int:
    """ピッチクラス（0〜11）を MIDI ノート番号にする。

    ファイル名の「Cmin」にはオクターブが無いので、どの高さを原音とみなすかは
    決められない。既定では C3 のオクターブに収める。

    >>> pitch_class_to_note(0)
    60
    >>> pitch_class_to_note(9)
    69
    >>> pitch_class_to_note(0, octave=1)
    36
    """
    if not 0 <= pitch_class <= 11:
        raise ValueError(tr(
            f"ピッチクラスが範囲外です: {pitch_class}",
            f"The pitch class is out of range: {pitch_class}",
        ))
    note = MIDDLE_C_NOTE + (octave - MIDDLE_C_OCTAVE) * 12 + pitch_class
    if not MIDI_MIN <= note <= MIDI_MAX:
        raise ValueError(
            tr(
                f"オクターブ {octave} ではノート番号が範囲外になります: {note}",
                f"Octave {octave} puts the note number out of range: {note}",
            )
        )
    return note


# --------------------------------------------------------------------------
# 借りている部品の読み込み（見つからなくても落ちない）
# --------------------------------------------------------------------------

def _load_splicename() -> Any:
    """`ptcore.splicename` を借りる。無ければ None。"""
    return load_ptcore("splicename")


def _load_keydetect() -> Any:
    """`ptcore.keydetect` を借りる。無ければ None。"""
    return load_ptcore("keydetect")


# --------------------------------------------------------------------------
# 読み取り
# --------------------------------------------------------------------------


def read_key_from_filename(filename: str) -> KeyReading:
    """ファイル名からキーを読む。借りている部品の `ptcore/splicename.py` を使う。

    Splice のファイル名は `Karra Vox Chop 120bpm Cmin.wav` のような形で、
    キーが埋め込まれていることが多い。**音を読む必要がないので速い。**
    """
    module = _load_splicename()
    if module is None:
        return KeyReading.unknown(tr(
            "借りている部品が見つからないため、ファイル名からは読めません",
            "Could not read the file name, because a borrowed part was not found",
        ))

    parsed = module.parse(filename)
    if parsed.pitch_class is None:
        return KeyReading.unknown()
    return KeyReading(
        pitch_class=parsed.pitch_class,
        quality=parsed.key_quality,
        confidence=parsed.key_confidence,
        label=part_key_label(parsed.key_label),
    )


class SpliceKeyAnalyzer:
    """`keydetect` で音からキーを推定する `KeyAnalyzer` の実装。

    音声ファイルを読むので遅い。**テストでは注入しない。**
    """

    def analyze(self, path: str) -> KeyReading:
        module = _load_keydetect()
        if module is None:
            return KeyReading.unknown(tr(
                "借りている部品が見つからないため、音からは推定できません",
                "Could not estimate from the sound, because a borrowed part was not found",
            ))

        estimate = module.detect_key(path)
        if estimate.key is None:
            return KeyReading.unknown()
        return KeyReading(
            pitch_class=estimate.pitch_class,
            quality=estimate.quality,
            confidence=estimate.confidence,
            label=part_key_label(estimate.key_label),
        )


# --------------------------------------------------------------------------
# 決定
# --------------------------------------------------------------------------


def _relative_major(reading: KeyReading) -> int:
    """平行調を同一視するため、マイナーを平行メジャーへ寄せる。

    A マイナーと C メジャーは同じ音階なので、**食い違いの検出では**
    同じものとして扱う（`keydetect.transposition_agrees` と同じ考え方）。

    ただし **`pitch_keycenter` にはこの値を使わない。** 原音の高さは
    主音そのもので、A マイナーの主音は A、C メジャーの主音は C である。
    ここで寄せるのは照合のときだけ。
    """
    assert reading.pitch_class is not None
    if reading.quality == "minor":
        return (reading.pitch_class + 3) % 12
    return reading.pitch_class % 12


def _disagreement(name: KeyReading, audio: KeyReading) -> str | None:
    """ファイル名と音の食い違いを、確信が持てるときだけ文言にする。

    確信度が high のときしか警告しないのは、それ以下では推定が外れることも
    多く、毎回言われても判断材料にならないため（`keydetect.review_key` と同じ方針）。
    """
    if not (name.found and audio.found):
        return None
    if _relative_major(name) == _relative_major(audio):
        return None
    if audio.confidence != "high":
        return None
    return tr(
        f"[警告] 音から推定したキーは{audio.label}で、"
        f"ファイル名の{name.label}と食い違います。"
        "ルートキーを確かめてください。",
        f"[Warning] The key estimated from the sound is {audio.label}, but the file name says "
        f"{name.label}. Please check the root key.",
    )


def _message(note: int, source: str, reading: KeyReading | None) -> str:
    """読み上げ用の本文。接頭辞は付けない（情報はそのまま読ませる規約）。"""
    name = note_name(note)
    if source == "filename" and reading is not None:
        head = tr(
            f"ルートキー {name}。ファイル名の{reading.label}から決めました。",
            f"Root key {name}, from {reading.label} in the file name.",
        )
    elif source == "audio" and reading is not None:
        head = tr(
            f"ルートキー {name}。音から推定した{reading.label}を使いました。",
            f"Root key {name}, using {reading.label} estimated from the sound.",
        )
    else:
        return tr(
            f"ルートキー {name}。キーを推定できなかったので既定値です。"
            "鳴らして確かめ、必要なら変えてください。",
            f"Root key {name}. The key could not be estimated, so this is the default. Play "
            "it to check, and change it if needed.",
        )
    if reading is not None and reading.confidence not in CONFIDENT:
        head += tr(
            "確信度は低いので、鳴らして確かめてください。",
            " Confidence is low, so play it to check.",
        )
    return head


def decide_root_key(
    filename: str,
    *,
    octave: int = DEFAULT_OCTAVE,
    audio_path: str | None = None,
    analyzer: KeyAnalyzer | None = None,
) -> RootKeyResult:
    """ルートキーを決める。

    Args:
        filename: サンプルのファイル名（パスでもよい）。
        octave: 原音とみなすオクターブ。既定は C3 の 3。
        audio_path: 音を聴くときのパス。省略時は `filename` を使う。
        analyzer: 音からの推定器。**None なら音を聴かない**（速い）。
            渡すと、ファイル名が読めているときでも照合のために聴く。

    確信のある読み取りを優先し、どちらも確信が無ければ値のある方を使う。
    何も得られなければ既定の C3 に落として、その旨を読み上げる。
    **推定できないことは失敗ではない**ので、例外にはしない。
    """
    warnings: list[str] = []

    from_name = read_key_from_filename(filename)

    from_audio = KeyReading.unknown()
    if analyzer is not None:
        try:
            from_audio = analyzer.analyze(audio_path or filename)
        except Exception as exc:  # noqa: BLE001
            # ルートキーは既定値でも作業を続けられる。ここで落とすと
            # サンプル 1 つのせいで全体が止まってしまう。
            warnings.append(tr(
                f"[警告] 音からのキー推定に失敗しました: {exc}",
                f"[Warning] Estimating the key from the sound failed: {part_message(str(exc))}",
            ))

    disagreement = _disagreement(from_name, from_audio)
    if disagreement is not None:
        warnings.append(disagreement)

    candidates = ((from_name, "filename"), (from_audio, "audio"))

    # 1) 確信のある読み取り。2) 確信は無いが値はある読み取り。
    for require_confidence in (True, False):
        for reading, source in candidates:
            if not reading.found:
                continue
            if require_confidence and not reading.is_confident:
                continue
            note = pitch_class_to_note(reading.pitch_class, octave)
            return RootKeyResult(
                note=note,
                source=source,
                confidence=reading.confidence,
                label=reading.label,
                message_ja=_message(note, source, reading),
                warnings=tuple(warnings),
            )

    # 3) 何も得られなかった
    note = pitch_class_to_note(0, octave)
    for reading in (from_name, from_audio):
        if reading.note_ja:
            warnings.append(tr(f"[警告] {reading.note_ja}", f"[Warning] {reading.note_ja}"))
    return RootKeyResult(
        note=note,
        source="default",
        confidence="none",
        label=tr("不明", "unknown"),
        message_ja=_message(note, "default", None),
        warnings=tuple(warnings),
    )
