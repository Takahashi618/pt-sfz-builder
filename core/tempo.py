"""素材のテンポをセッションに合わせる。

### 何が問題か

Splice のループは素材ごとにテンポが違う。**セッションのテンポと合わないと
そのままでは使えない。** 145 BPM のループを 128 BPM の曲で弾いても噛み合わない。

### どう解く

**再生する長さを変える。** 音程は変えない伸縮（ffmpeg の `atempo`）を使う。

    出力の長さ ÷ 入力の長さ = 元のテンポ ÷ 目標のテンポ

    145 BPM の素材を 128 BPM で鳴らす → 遅くする → 長くする
    ratio = 145 / 128 = 1.133

`core/phrase.py`（速さを保つ配置）と**掛け合わせて使う**。
鍵盤ごとの倍率にテンポの倍率を掛ければ、
**どの鍵盤でもセッションのテンポで鳴る。**

### 倍・半分のテンポを考える

170 BPM の素材を 85 BPM のセッションで使うとき、素直に計算すると 2 倍に
引き伸ばすことになる。**だが 170 は 85 の倍テンポなので、そのままで合う。**

そこで**元のテンポを半分・2 倍にした場合も試し、1 に近いものを採る。**
音楽的にはこれが期待される振る舞いで、引き伸ばしも最小で済む。

### 元のテンポが分からないとき

**変えない。** 推測で伸縮すると、合っていないことに気づけないまま
使い続けることになる。読み上げで「分からなかった」と伝える。

OS 非依存。借りている部品を遅延 import するが、**見つからなくても落ちない**
（`core/rootkey.py` と同じ方針）。
"""

from __future__ import annotations

from .i18n import tr

import math
from dataclasses import dataclass, field
from pathlib import Path

from .phrase import phrase_filename
from .sibling import load_ptcore

__all__ = [
    "BPM_MIN",
    "BPM_MAX",
    "RATIO_WARN_HIGH",
    "RATIO_WARN_LOW",
    "TempoReading",
    "TempoDecision",
    "read_bpm_from_filename",
    "decide_tempo",
    "tempo_tag",
    "StretchRender",
    "stretch_for",
]

# 受け付ける BPM の範囲。外は打ち間違いとみなす。
BPM_MIN = 20
BPM_MAX = 400

# ここを超えて伸縮すると音が荒れる。止めはしないが伝える。
RATIO_WARN_HIGH = 1.5
RATIO_WARN_LOW = 1 / 1.5


@dataclass(frozen=True)
class TempoReading:
    """ファイル名から読めたテンポ。"""

    bpm: int | None = None
    confidence: str = "none"

    @property
    def known(self) -> bool:
        return self.bpm is not None


@dataclass(frozen=True)
class TempoDecision:
    """テンポをどう変えるか決めた結果。"""

    ratio: float  # 出力の長さ ÷ 入力の長さ。1.0 なら変えない
    source_bpm: int | None = None
    target_bpm: int | None = None
    doubled: bool = False  # 元のテンポを 2 倍とみなした
    halved: bool = False  # 元のテンポを半分とみなした
    message_ja: str = ""
    warnings: tuple[str, ...] = field(default=())

    @property
    def changes(self) -> bool:
        return abs(self.ratio - 1.0) > 1e-9

    def describe_ja(self) -> str:
        if not self.warnings:
            return self.message_ja
        return self.message_ja + " " + " ".join(self.warnings)


def read_bpm_from_filename(filename: str) -> TempoReading:
    """ファイル名からテンポを読む。読めなければ `known` が False。"""
    module = load_ptcore("splicename")
    if module is None:
        return TempoReading()
    name = Path(filename).name
    try:
        parsed = module.parse(name)
    except Exception:
        return TempoReading()
    bpm = getattr(parsed, "bpm", None)
    if bpm is None or not BPM_MIN <= int(bpm) <= BPM_MAX:
        return TempoReading()
    return TempoReading(int(bpm), getattr(parsed, "bpm_confidence", "none"))


def _best_ratio(source_bpm: int, target_bpm: int, allow_half_double: bool):
    """倍率を決める。戻り値は (倍率, 2倍とみなしたか, 半分とみなしたか)。

    **素直な倍率で足りるなら、そのまま使う。** 荒れない範囲
    （`RATIO_WARN_LOW` 〜 `RATIO_WARN_HIGH`）に収まっているのに
    倍・半分へ読み替えると、**利用者の意図と逆向きに動く。**

        90 BPM のループを 128 のセッションへ（速くしたい）
          素直な倍率     90/128 = 0.703  ← 荒れない範囲の内側
          2 倍とみなす  180/128 = 1.406  ← 1 には近いが、遅くなる

    1 への近さだけで選んでいたときは後者を採り、速めたい素材が
    半分の速さで鳴っていた（2026-09-05 のレビューで判明）。

    範囲の外へ出て初めて、倍・半分の解釈を試す。170 の素材を 85 の
    セッションで使うようなときは、こちらが musically 正しい。
    """
    plain = source_bpm / target_bpm
    if not allow_half_double or RATIO_WARN_LOW <= plain <= RATIO_WARN_HIGH:
        return (plain, False, False)
    candidates = [
        (plain, False, False),
        # **倍テンポ・半テンポの解釈。** 170 の素材は 85 のセッションに
        # そのまま合う（引き伸ばす必要が無い）。
        (source_bpm / 2 / target_bpm, False, True),
        (source_bpm * 2 / target_bpm, True, False),
    ]
    # **対数で比べる。** 1.5 倍と 1/1.5 倍を同じ「遠さ」として扱うため。
    return min(candidates, key=lambda item: abs(math.log(item[0])))


def decide_tempo(
    filename: str,
    target_bpm: int | None,
    *,
    source_bpm: int | None = None,
    allow_half_double: bool = True,
) -> TempoDecision:
    """テンポをどう変えるか決める。**推測で伸縮しない。**

    Args:
        filename: 素材のファイル名（パスでもよい）。テンポを読むのに使う。
        target_bpm: セッションのテンポ。None なら変えない。
        source_bpm: 元のテンポ。渡せばファイル名より優先する。
        allow_half_double: 倍・半分のテンポの解釈も試すか。
    """
    if target_bpm is None:
        return TempoDecision(1.0, message_ja=tr(
            "テンポは変えません。",
            "The tempo stays as it is.",
        ))
    if not BPM_MIN <= target_bpm <= BPM_MAX:
        return TempoDecision(
            1.0,
            target_bpm=target_bpm,
            message_ja=tr("テンポは変えません。", "The tempo stays as it is."),
            warnings=(
                tr(
                    f"[警告] セッションのテンポが範囲外です: {target_bpm}。"
                    f"{BPM_MIN} から {BPM_MAX} で指定してください。",
                    f"[Warning] The session tempo is out of range: {target_bpm}. Use {BPM_MIN} to "
                    f"{BPM_MAX}.",
                ),
            ),
        )

    known = source_bpm
    if known is None:
        reading = read_bpm_from_filename(filename)
        known = reading.bpm
    if known is None:
        return TempoDecision(
            1.0,
            target_bpm=target_bpm,
            message_ja=tr("テンポは変えません。", "The tempo stays as it is."),
            warnings=(
                tr(
                    "元のテンポがファイル名から読めなかったので、"
                    "テンポは変えませんでした。",
                    "The tempo was not changed, because the original tempo could not be read from "
                    "the file name.",
                ),
            ),
        )
    if not BPM_MIN <= known <= BPM_MAX:
        return TempoDecision(
            1.0,
            source_bpm=known,
            target_bpm=target_bpm,
            message_ja=tr("テンポは変えません。", "The tempo stays as it is."),
            warnings=(tr(
                f"[警告] 元のテンポが範囲外です: {known}。",
                f"[Warning] The original tempo is out of range: {known}.",
            ),),
        )

    ratio, doubled, halved = _best_ratio(known, target_bpm, allow_half_double)

    if abs(ratio - 1.0) <= 1e-9:
        note = ""
        if halved:
            note = tr(
                f"（{known} は {target_bpm} の倍テンポとみなしました）",
                f"({known} was treated as double the tempo of {target_bpm})",
            )
        elif doubled:
            note = tr(
                f"（{known} は {target_bpm} の半分のテンポとみなしました）",
                f"({known} was treated as half the tempo of {target_bpm})",
            )
        return TempoDecision(
            1.0,
            source_bpm=known,
            target_bpm=target_bpm,
            doubled=doubled,
            halved=halved,
            message_ja=tr(
                f"テンポは {target_bpm} のままで合います。{note}",
                f"The tempo already matches at {target_bpm}.{' ' + note if note else ''}",
            ),
        )

    warnings: list[str] = []
    if ratio > RATIO_WARN_HIGH or ratio < RATIO_WARN_LOW:
        warnings.append(
            tr(
                f"[警告] {ratio:.2f}倍まで伸縮します。音が荒れることがあります。",
                f"[Warning] Stretching up to {ratio:.2f} times. The sound may become rough.",
            )
        )

    how = tr("遅く", "slower") if ratio > 1 else tr("速く", "faster")
    interpreted = ""
    if halved:
        interpreted = tr(
            f"（{known} を半分の {known / 2:g} とみなしました）",
            f"({known} was treated as half, {known / 2:g})",
        )
    elif doubled:
        interpreted = tr(
            f"（{known} を 2 倍の {known * 2} とみなしました）",
            f"({known} was treated as double, {known * 2})",
        )

    return TempoDecision(
        ratio,
        source_bpm=known,
        target_bpm=target_bpm,
        doubled=doubled,
        halved=halved,
        message_ja=(
            tr(
                f"テンポを {known} から {target_bpm} へ{how}します"
                f"（長さ {ratio:.3f} 倍）。{interpreted}",
                f"Changing the tempo from {known} to {target_bpm}, {how} (length times "
                f"{ratio:.3f}).{' ' + interpreted if interpreted else ''}",
            )
        ),
        warnings=tuple(warnings),
    )


def tempo_tag(decision: TempoDecision) -> str:
    """下ごしらえのファイル名に付ける印。**変えないときは空。**

    元と目標の両方を入れる。片方だけだと、元のテンポを指定し直したときに
    古いファイルを使い回してしまう。
    """
    if not decision.changes:
        return ""
    return f"b{decision.source_bpm}to{decision.target_bpm}"


# --------------------------------------------------------------------------
# 鍵盤に関係しない伸縮（クロマティック・ドラムキット用）
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StretchRender:
    """テンポを合わせるためだけの下ごしらえ 1 件。

    `core/phrase.PhraseRender` と同じ 3 つの属性
    （`source` / `dest` / `tempo_ratio`）を持つので、
    **`integration/render.py` はどちらも同じように扱える。**
    鍵盤の情報を持たないのは、ここでは要らないため。
    """

    source: str
    dest: str
    tempo_ratio: float

    @property
    def is_original(self) -> bool:
        return abs(self.tempo_ratio - 1.0) <= 1e-9

    def describe_ja(self) -> str:
        if self.is_original:
            return tr("元のまま", "unchanged")
        return tr(f"長さを{self.tempo_ratio:.3f}倍にする", f"length times {self.tempo_ratio:.3f}")


def stretch_for(
    source: str, decision: TempoDecision, out_dir: str
) -> StretchRender:
    """テンポ合わせ 1 件分の下ごしらえを決める。**純粋関数。**

    **変えないなら元のファイルをそのまま指す。** 同じ中身のコピーを作らない。

    ファイル名は `core/phrase.py` と同じ付け方（半音ずれ 0）にしてある。
    別々の付け方にすると、片付けの判断を二重に書くことになる。
    """
    if not decision.changes:
        return StretchRender(source=source, dest=source, tempo_ratio=1.0)
    base = out_dir.rstrip("/\\")
    name = phrase_filename(source, 0, tempo_tag(decision))
    return StretchRender(
        source=source, dest=f"{base}/{name}", tempo_ratio=decision.ratio
    )
