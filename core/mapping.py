"""サンプルを鍵盤へ配置する方針と、その中間表現。

**この層は出力書式に依存しない。** sforzando（.sfz）に出すか
Decent Sampler（.dspreset）に出すかは実機検証の結果で決まるため、
判断のロジックだけを先に固めておく（DESIGN_SFZ.md「10.」参照）。

    build_chromatic / build_drumkit  ->  Instrument   （書式非依存）
                                            |
                                            +--> to_sfz()      -> SfzDocument
                                            +--> to_dspreset() -> 将来
"""

from __future__ import annotations

from .i18n import plural, tr

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .sfz import Opcode, Region, SfzDocument, SfzError
from .notes import MIDI_MAX, MIDI_MIN, note_name
from .tone import ToneSettings

__all__ = [
    "MIDI_MIN",
    "MIDI_MAX",
    "DEFAULT_ROOT_KEY",
    "DEFAULT_DRUM_START",
    "MODE_CHROMATIC",
    "MODE_DRUMKIT",
    "MODE_PHRASE",
    "Zone",
    "Instrument",
    "DrumEntry",
    "build_chromatic",
    "build_phrase",
    "build_drumkit",
    "to_sfz",
]

DEFAULT_ROOT_KEY = 60  # C3（ヤマハ式。notes.MIDDLE_C_NOTE と揃える）
DEFAULT_DRUM_START = 36  # C1。GM のキックの位置

# 配置の種別。ゾーンの形から推定することもできるが、推定は脆いので明示的に持つ。
# 台帳（core/slots.py）が読み上げの文言を変えるのに使う。
MODE_CHROMATIC = "chromatic"
MODE_DRUMKIT = "drumkit"
# 速さを変えずに鍵盤へ広げる。**鍵盤ごとに下ごしらえしたファイルを使う**
# （`core/phrase.py`）。ゾーンの形はクロマティックと違い、1 鍵盤 1 ゾーン
# だがルートキーはずらさない。
MODE_PHRASE = "phrase"


@dataclass(frozen=True)
class Zone:
    """1 つのサンプルが鳴る鍵盤の範囲。"""

    sample_path: str
    lokey: int
    hikey: int
    root_key: int
    one_shot: bool = False
    label: str = ""

    def __post_init__(self) -> None:
        for name, note in (
            ("lokey", self.lokey),
            ("hikey", self.hikey),
            ("root_key", self.root_key),
        ):
            if not MIDI_MIN <= note <= MIDI_MAX:
                raise SfzError(tr(
                    f"{name} が MIDI ノートの範囲外です: {note}",
                    f"{name} is out of the MIDI note range: {note}",
                ))
        if self.lokey > self.hikey:
            raise SfzError(tr(
                f"lokey が hikey を超えています: {self.lokey} > {self.hikey}",
                f"lokey is above hikey: {self.lokey} > {self.hikey}",
            ))
        if not self.sample_path.strip():
            raise SfzError(tr("sample_path が空です", "sample_path is empty"))

    @property
    def is_single_key(self) -> bool:
        """1 鍵盤だけに割り当てられているか。SFZ の key= 短縮形が使える条件。"""
        return self.lokey == self.hikey == self.root_key

    def describe_ja(self) -> str:
        name = self.label or self.sample_path.rsplit("/", 1)[-1]
        if self.is_single_key:
            return tr(f"{name}、{note_name(self.root_key)}", f"{name}, {note_name(self.root_key)}")
        span = tr(
            "全鍵盤",
            "the whole keyboard",
        ) if (self.lokey, self.hikey) == (MIDI_MIN, MIDI_MAX) else (
            tr(
                f"{note_name(self.lokey)}から{note_name(self.hikey)}",
                f"{note_name(self.lokey)} to {note_name(self.hikey)}",
            )
        )
        return tr(
            f"{name}、ルートキー{note_name(self.root_key)}、{span}",
            f"{name}, root key {note_name(self.root_key)}, {span}",
        )


@dataclass
class Instrument:
    """鍵盤への配置ひとそろい。書式に依存しない。"""

    zones: list[Zone]
    tone: ToneSettings = field(default_factory=ToneSettings)
    name: str = ""
    notes: list[str] = field(default_factory=list)
    mode: str = MODE_CHROMATIC

    def __post_init__(self) -> None:
        if not self.zones:
            raise SfzError(tr("ゾーンが 1 つもありません", "There are no zones"))
        if self.mode not in (MODE_CHROMATIC, MODE_DRUMKIT, MODE_PHRASE):
            raise SfzError(tr(
                f"知らない配置種別です: {self.mode!r}",
                f"Unknown mapping type: {self.mode!r}",
            ))

    def describe_ja(self) -> str:
        if self.mode == MODE_PHRASE:
            # **「N 個のサンプル」と言わない。** 中身は同じフレーズで、
            # 鍵盤ごとに下ごしらえした版があるだけ。数を言うと別物に聞こえる。
            root = self.zones[0].root_key
            name = self.zones[0].label or self.zones[0].sample_path.rsplit("/", 1)[-1]
            return tr(
                f"{name}、ルートキー{note_name(root)}、"
                f"{note_name(self.zones[0].lokey)}から"
                f"{note_name(self.zones[-1].hikey)}、速さを保つ",
                f"{name}, root key {note_name(root)}, {note_name(self.zones[0].lokey)} to "
                f"{note_name(self.zones[-1].hikey)}, keeping speed",
            )
        if len(self.zones) == 1:
            return self.zones[0].describe_ja()
        return tr(
            f"{len(self.zones)}個のサンプル、{note_name(self.zones[0].root_key)}から順に配置",
            f"{plural(len(self.zones), 'sample')}, arranged in order from "
            f"{note_name(self.zones[0].root_key)}",
        )


@dataclass(frozen=True)
class DrumEntry:
    """ドラムキット 1 鍵盤分の指定。"""

    sample_path: str
    label: str = ""


def build_chromatic(
    sample_path: str,
    root_key: int = DEFAULT_ROOT_KEY,
    *,
    name: str = "",
    tone: ToneSettings | None = None,
    lokey: int = MIDI_MIN,
    hikey: int = MIDI_MAX,
    notes: Sequence[str] | None = None,
) -> Instrument:
    """1 つのサンプルを鍵盤全体に配置する（主用途）。

    既定では全鍵盤に広げる。**音量を鍵盤位置で減衰させない**（amp_keytrack を
    使わない）のは意図的で、位置によって勝手に音量が変わると、
    何が起きているのか耳で判断しにくくなるため。

    どこまで実用的に鳴るかは素材によるので、利用者が耳で決められるようにする。
    """
    zone = Zone(
        sample_path=sample_path,
        lokey=lokey,
        hikey=hikey,
        root_key=root_key,
        one_shot=False,  # 鍵盤を離したらリリースに入る
        label=name,
    )
    return Instrument(
        zones=[zone],
        tone=tone or ToneSettings(),
        name=name,
        notes=list(notes or []),
        mode=MODE_CHROMATIC,
    )


def build_phrase(
    plan,
    *,
    name: str = "",
    tone: ToneSettings | None = None,
    notes: Sequence[str] | None = None,
) -> Instrument:
    """速さを変えずに鍵盤へ広げる（`core/phrase.py` の計画から組み立てる）。

    **1 鍵盤 1 ゾーン。だがルートキーはずらさない。**
    ずらしてしまうと再生速度が 1 になり、下ごしらえした長さのまま鳴る。

        <region> lokey=k hikey=k pitch_keycenter=root sample=<k 用のファイル>

    `plan` は `core/phrase.py` の `PhrasePlan`。型で縛らないのは、
    `mapping` が `phrase` に依存しないようにするため（逆向きの依存が無い）。
    """
    zones = [
        Zone(
            sample_path=render.dest,
            lokey=render.key,
            hikey=render.key,
            root_key=render.root_key,
            one_shot=False,
            label=name,
        )
        for render in plan.renders
    ]
    return Instrument(
        zones=zones,
        tone=tone or ToneSettings(),
        name=name,
        notes=list(notes or []),
        mode=MODE_PHRASE,
    )


def build_drumkit(
    entries: Sequence[DrumEntry | str],
    *,
    start_note: int = DEFAULT_DRUM_START,
    name: str = "",
    tone: ToneSettings | None = None,
    notes: Sequence[str] | None = None,
) -> Instrument:
    """1 鍵盤 1 サンプルで、開始ノートから半音ずつ上へ並べる（副用途）。

    ``one_shot=True`` にするので、鍵盤を離しても最後まで鳴りきる。
    ドラムではこれが正しい挙動。
    """
    if not entries:
        raise SfzError(tr("配置するサンプルがありません", "There are no samples to arrange"))
    last_note = start_note + len(entries) - 1
    if last_note > MIDI_MAX:
        raise SfzError(
            tr(
                f"{len(entries)}個を{note_name(start_note)}から並べると"
                f"鍵盤の上端を超えます（{note_name(MIDI_MAX)}まで）",
                f"{plural(len(entries), 'sample')} from {note_name(start_note)} would go past the "
                f"top of the keyboard (up to {note_name(MIDI_MAX)})",
            )
        )

    zones: list[Zone] = []
    for offset, entry in enumerate(entries):
        item = DrumEntry(entry) if isinstance(entry, str) else entry
        note = start_note + offset
        zones.append(
            Zone(
                sample_path=item.sample_path,
                lokey=note,
                hikey=note,
                root_key=note,
                one_shot=True,
                label=item.label,
            )
        )
    return Instrument(
        zones=zones,
        tone=tone or ToneSettings(),
        name=name,
        notes=list(notes or []),
        mode=MODE_DRUMKIT,
    )


def to_sfz(
    instrument: Instrument,
    *,
    generated_at: str | None = None,
) -> SfzDocument:
    """Instrument を SfzDocument に変換する。

    ``generated_at`` を差し替えられるようにしてあるのはテストのため
    （現在時刻が入ると往復テストで文字列比較ができない）。
    """
    stamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    comments: list[str] = []
    if instrument.name:
        comments.append(instrument.name)
    comments.append(tr(f"生成: {stamp}", f"Generated: {stamp}"))
    comments.extend(instrument.notes)

    regions: list[Region] = []
    for zone in instrument.zones:
        opcodes: list[Opcode] = []
        if zone.is_single_key:
            # key= は lokey / hikey / pitch_keycenter を一度に設定する短縮形。
            # 3 つがずれる事故が起きない。
            opcodes.append(Opcode.number("key", zone.root_key))
        else:
            opcodes.append(Opcode.number("lokey", zone.lokey))
            opcodes.append(Opcode.number("hikey", zone.hikey))
            opcodes.append(Opcode.number("pitch_keycenter", zone.root_key))
        opcodes.append(Opcode("loop_mode", "one_shot" if zone.one_shot else "no_loop"))
        regions.append(Region(sample=zone.sample_path, opcodes=opcodes))

    return SfzDocument(
        regions=regions,
        global_opcodes=instrument.tone.to_opcodes(),
        comments=comments,
    )
