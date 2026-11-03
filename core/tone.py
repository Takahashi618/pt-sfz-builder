"""音作り（ADSR とフィルター）の設定。

要件は「ADSR とフィルター程度。それ以上は Pro Tools 側の AAX プラグインで」。
LFO・ベロシティレイヤー・ラウンドロビンは扱わない。

単位を取り違えやすいので、ここに集約して型と検査を効かせる。

- attack / decay / release / hold : **秒**
- sustain                        : **パーセント**（dB ではない）
- cutoff                         : **Hz**
- resonance                      : **dB**
"""

from __future__ import annotations

from .i18n import COMMA, plural, tr

from dataclasses import dataclass

from .sfz import Opcode, SfzError

__all__ = [
    "RELEASE_MIN_SEC",
    "FILTER_TYPES",
    "ToneSettings",
    "PRESETS",
    "preset_names",
    "get_preset",
]

# リリースを 0 にすると鍵盤を離した瞬間に波形が断ち切られ、クリックノイズが出る。
# 利用者が 0 を入れてもここまで引き上げる。
RELEASE_MIN_SEC = 0.02

# sforzando（ARIA）が解釈するフィルター種別のうち、本ツールで使うもの
FILTER_TYPES: dict[str, str] = {
    "lpf_1p": tr("ローパス 6dB/oct", "Low-pass 6 dB per octave"),
    "lpf_2p": tr("ローパス 12dB/oct", "Low-pass 12 dB per octave"),
    "lpf_4p": tr("ローパス 24dB/oct", "Low-pass 24 dB per octave"),
    "hpf_1p": tr("ハイパス 6dB/oct", "High-pass 6 dB per octave"),
    "hpf_2p": tr("ハイパス 12dB/oct", "High-pass 12 dB per octave"),
    "hpf_4p": tr("ハイパス 24dB/oct", "High-pass 24 dB per octave"),
    "bpf_2p": tr("バンドパス 12dB/oct", "Band-pass 12 dB per octave"),
    "brf_2p": tr("バンドリジェクト 12dB/oct", "Band-reject 12 dB per octave"),
}


@dataclass(frozen=True)
class ToneSettings:
    """1 音色分の ADSR とフィルター。

    ``cutoff`` が None のときはフィルターを一切書き出さない。
    「開放したつもりで高い値を書く」より、書かないほうが確実に素通しになる。
    """

    attack: float = 0.001
    decay: float = 0.0
    sustain: float = 100.0
    release: float = 0.08
    hold: float = 0.0

    fil_type: str = "lpf_2p"
    cutoff: float | None = None
    resonance: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("attack", self.attack),
            ("decay", self.decay),
            ("release", self.release),
            ("hold", self.hold),
        ):
            if not 0.0 <= value <= 100.0:
                raise SfzError(tr(
                    f"{name} は 0〜100 秒の範囲です: {value}",
                    f"{name} must be 0 to 100 seconds: {value}",
                ))
        if not 0.0 <= self.sustain <= 100.0:
            raise SfzError(
                tr(
                    f"sustain は 0〜100 パーセントの範囲です（dB ではありません）: {self.sustain}",
                    f"sustain must be 0 to 100 percent (not dB): {self.sustain}",
                )
            )
        if self.cutoff is not None and not 20.0 <= self.cutoff <= 22000.0:
            raise SfzError(tr(
                f"cutoff は 20〜22000 ヘルツの範囲です: {self.cutoff}",
                f"cutoff must be 20 to 22000 hertz: {self.cutoff}",
            ))
        if not 0.0 <= self.resonance <= 40.0:
            raise SfzError(tr(
                f"resonance は 0〜40 デシベルの範囲です: {self.resonance}",
                f"resonance must be 0 to 40 decibels: {self.resonance}",
            ))
        if self.fil_type not in FILTER_TYPES:
            raise SfzError(tr(
                f"未対応のフィルター種別です: {self.fil_type!r}",
                f"Unsupported filter type: {self.fil_type!r}",
            ))

    def normalized(self) -> "ToneSettings":
        """リリースの下限を適用した設定を返す。"""
        if self.release >= RELEASE_MIN_SEC:
            return self
        return ToneSettings(
            attack=self.attack,
            decay=self.decay,
            sustain=self.sustain,
            release=RELEASE_MIN_SEC,
            hold=self.hold,
            fil_type=self.fil_type,
            cutoff=self.cutoff,
            resonance=self.resonance,
        )

    def to_opcodes(self) -> list[Opcode]:
        """SFZ の <global> に書き出すオプコード列を返す。"""
        tone = self.normalized()
        opcodes = [
            Opcode.number("ampeg_attack", tone.attack),
            Opcode.number("ampeg_decay", tone.decay),
            Opcode.number("ampeg_sustain", tone.sustain),
            Opcode.number("ampeg_release", tone.release),
        ]
        if tone.hold > 0:
            opcodes.insert(1, Opcode.number("ampeg_hold", tone.hold))
        if tone.cutoff is not None:
            opcodes.append(Opcode("fil_type", tone.fil_type))
            opcodes.append(Opcode.number("cutoff", tone.cutoff))
            if tone.resonance > 0:
                opcodes.append(Opcode.number("resonance", tone.resonance))
        return opcodes

    def describe_ja(self) -> str:
        """読み上げ用の説明。単位を言葉にする（数値だけでは何の値か分からない）。"""
        tone = self.normalized()
        parts = [
            tr(f"アタック{_sec_ja(tone.attack)}", f"attack {_sec_ja(tone.attack)}"),
            tr(f"ディケイ{_sec_ja(tone.decay)}", f"decay {_sec_ja(tone.decay)}"),
            tr(
                f"サステイン{_num_ja(tone.sustain)}パーセント",
                f"sustain {_num_ja(tone.sustain)} percent",
            ),
            tr(f"リリース{_sec_ja(tone.release)}", f"release {_sec_ja(tone.release)}"),
        ]
        if tone.hold > 0:
            parts.insert(1, tr(f"ホールド{_sec_ja(tone.hold)}", f"hold {_sec_ja(tone.hold)}"))
        if tone.cutoff is None:
            parts.append(tr("フィルターなし", "no filter"))
        else:
            parts.append(
                tr(
                    f"{FILTER_TYPES[tone.fil_type]}、カットオフ{_num_ja(tone.cutoff)}ヘルツ",
                    f"{FILTER_TYPES[tone.fil_type]}, cutoff {_num_ja(tone.cutoff)} hertz",
                )
            )
            if tone.resonance > 0:
                parts.append(tr(
                    f"レゾナンス{_num_ja(tone.resonance)}デシベル",
                    f"resonance {plural(tone.resonance, 'decibel')}",
                ))
        return COMMA.join(parts)


def _num_ja(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _sec_ja(value: float) -> str:
    return tr(f"{_num_ja(value)}秒", plural(value, "second"))


# 名前付きプリセット。毎回 5 つの値を入力させないための組。
# 名前は読み上げでそのまま読まれるので、記号を含めず短くしてある。
PRESETS: dict[str, ToneSettings] = {
    tr("そのまま", "As is"): ToneSettings(
        attack=0.001, decay=0.0, sustain=100.0, release=0.08, cutoff=None
    ),
    tr("やわらかい立ち上がり", "Soft attack"): ToneSettings(
        attack=0.15, decay=0.0, sustain=100.0, release=0.3, cutoff=None
    ),
    tr("短く切る", "Cut short"): ToneSettings(
        attack=0.001, decay=0.12, sustain=0.0, release=0.05, cutoff=None
    ),
    tr("こもらせる", "Muffled"): ToneSettings(
        attack=0.001,
        decay=0.0,
        sustain=100.0,
        release=0.08,
        fil_type="lpf_2p",
        cutoff=800.0,
    ),
    tr("ワンショット", "One-shot"): ToneSettings(
        attack=0.001, decay=0.0, sustain=100.0, release=RELEASE_MIN_SEC, cutoff=None
    ),
}

DEFAULT_PRESET = tr("そのまま", "As is")


def preset_names() -> list[str]:
    """プリセット名の一覧。UI の選択肢に使う。"""
    return list(PRESETS)


def get_preset(name: str) -> ToneSettings:
    """名前からプリセットを取り出す。"""
    try:
        return PRESETS[name]
    except KeyError:
        raise SfzError(tr(
            f"知らないプリセット名です: {name!r}",
            f"Unknown preset name: {name!r}",
        )) from None
