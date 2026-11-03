"""素材の種別とパックの並び順。**作者の別のアプリと規則を合わせる。**

同じサンプルを作者の別のアプリと**同じ言葉で絞り込めること**が目的なので、
判断の規則を勝手に変えない。

### 種別はファイル名だけでは当てにならない

作者の別のアプリが実測している。**Splice 3119 件のうち、ファイル名だけで
ワンショットと判定した 2241 件の中に、3 秒以上のものが 1270 件あった。**

そこで**長さを優先する。**

    1. 長さが境目を超える  → ループ（ファイル名が何であれ長い音）
    2. 長さが境目以下      → ファイル名の判定に従う（短いループを拾う）
    3. 長さが分からない    → ファイル名の判定に従う

境目は 2.0 秒（`DEFAULT_ONESHOT_MAX_SEC`）。ドラムの単発音はおおむね
ここに収まる。

**効果音（fx）は長さで覆さない。** ここだけ向こうと違う。あちらは
ワンショットとループの 2 種類しか持たないが、`splicename` は効果音を
別に判定する。5 秒の効果音をループと言い換えると、かえって探しにくい。

### パックの並び順は 4 つ

| 並び | 向き | 使いどころ |
| --- | --- | --- |
| 中身の多い順（既定） | 多い順 | 目当てが決まっていないとき |
| 名前順 | あいうえお順 | 名前を覚えているとき。頭文字で飛べる |
| 更新の新しい順 | 新しい順 | **最近さわったパックを探すとき** |
| 追加した順 | **古い順** | **入れた順に辿るとき** |

作者の別のアプリの実測では **553 パック中 389 個が 1 件だけ**だった。
名前順だと目当ての大きなパックが埋もれる。だから既定は中身の多い順。

日時は 2 種類あり、**意味が違う。**

| | 何の日時か | 例 |
| --- | --- | --- |
| 更新 | そのパックで**最も新しい**素材 | 買い足し続けているパックが上 |
| 追加 | そのパックで**最も古い**素材 | 最初に入れたパックが上 |

Splice は素材を 1 つずつ落とすので、**同じパックでも追加日と更新日が
離れる**。実測でも `Southside - King of Trap Vol. 1` は
追加 2026-08-11 / 更新 2026-08-31 だった。

**フォルダ自体の日時は見ない。** 索引だけで出せるほうが速く、
外部の状態にも左右されない。実測ではフォルダの作成日時と
最古の素材の日時が一致したので、これで足りる。

OS 非依存。数えて並べるだけなので Windows でもテストできる。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "KIND_ONESHOT",
    "KIND_LOOP",
    "KIND_FX",
    "KIND_LABELS",
    "DEFAULT_ONESHOT_MAX_SEC",
    "PACK_ORDER_NAME",
    "PACK_ORDER_COUNT",
    "PACK_ORDER_MTIME",
    "PACK_ORDER_ADDED",
    "PACK_ORDER_OPTIONS",
    "PackStat",
    "kind_from_duration",
    "resolve_kind",
    "pack_stats",
    "sort_packs",
    "next_pack_order",
]

# `splicename` が返す値に合わせる。**勝手に増やさない。**
KIND_ONESHOT = "one_shot"
KIND_LOOP = "loop"
KIND_FX = "fx"

KIND_LABELS: dict[str, str] = {
    KIND_ONESHOT: "ワンショット",
    KIND_LOOP: "ループ",
    KIND_FX: "効果音",
    "": "不明",
}

# 長さから種別を判断する境目（秒）。これ以下ならワンショット。
# 作者の別のアプリの `DEFAULT_ONESHOT_MAX_SEC` と同じ値。**揃えておく。**
DEFAULT_ONESHOT_MAX_SEC: float = 2.0

PACK_ORDER_NAME = "name"
PACK_ORDER_COUNT = "count"
PACK_ORDER_MTIME = "mtime"
PACK_ORDER_ADDED = "added"

# **順送りの順番でもある。** 既定（中身の多い順）から始まる。
# 名前に**向きを入れてある。** 「日時順」だけでは新旧どちらが上か分からず、
# 読み上げで聞いても確かめようがない。
PACK_ORDER_OPTIONS: list[tuple[str, str]] = [
    (PACK_ORDER_COUNT, "中身の多い順"),
    (PACK_ORDER_NAME, "名前順"),
    (PACK_ORDER_MTIME, "更新の新しい順"),
    (PACK_ORDER_ADDED, "追加した順。古いものから"),
]


def kind_from_duration(
    duration: float | None, oneshot_max_sec: float = DEFAULT_ONESHOT_MAX_SEC
) -> str | None:
    """長さから種別を判断する。判断できなければ None。**純粋関数。**"""
    if duration is None or duration <= 0:
        return None
    return KIND_ONESHOT if duration <= oneshot_max_sec else KIND_LOOP


def resolve_kind(
    name_kind: str | None,
    duration: float | None,
    oneshot_max_sec: float = DEFAULT_ONESHOT_MAX_SEC,
) -> str:
    """種別を決める。**長さが分かればそれを優先する。**

    Args:
        name_kind: ファイル名からの判定（`splicename` の `kind`）。
        duration: 長さ（秒）。分からなければ None。
        oneshot_max_sec: ワンショットと見なす上限。

    **効果音はそのまま返す。** 長さで言い換えると探しにくくなる。
    """
    named = (name_kind or "").strip()
    if named == KIND_FX:
        return KIND_FX

    by_duration = kind_from_duration(duration, oneshot_max_sec)
    if by_duration == KIND_LOOP:
        # 長い音は、ファイル名が何であってもループとして扱う
        return KIND_LOOP
    if named:
        # 短い音はファイル名の判定に従う（短いドラムループを拾う）
        return named
    if by_duration is not None:
        return by_duration
    return ""


@dataclass(frozen=True)
class PackStat:
    """パック 1 つ分の並べ替えに要る値。

    `mtime` と `added` は**意味が違う**。前者は最も新しい素材、
    後者は最も古い素材の日時。Splice は素材を 1 つずつ落とすので、
    同じパックでも離れる。
    """

    count: int = 0
    mtime: float = 0.0
    added: float = 0.0


def pack_stats(entries: Sequence[Any]) -> dict[str, PackStat]:
    """パック名ごとの件数と更新日時を集める。**パック名の無いものは除く。**

    更新日時は**そのパックで最も新しい素材の日時**、追加日時は**最も古い
    素材の日時**。フォルダ自体の日時は見ない（索引だけで出せるほうが速く、
    外部の状態にも左右されない。実測で一致することも確かめてある）。
    """
    counts: dict[str, int] = {}
    newest: dict[str, float] = {}
    oldest: dict[str, float] = {}
    for entry in entries:
        name = (getattr(entry, "pack", "") or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        try:
            stamp = float(getattr(entry, "mtime", 0.0) or 0.0)
        except (TypeError, ValueError):
            stamp = 0.0
        if stamp > newest.get(name, 0.0):
            newest[name] = stamp
        # **0 は「日時が無い」なので最古の候補にしない。**
        # 1 件でも日時の無い素材があると、そのパックが常に先頭へ来てしまう。
        if stamp > 0 and (name not in oldest or stamp < oldest[name]):
            oldest[name] = stamp
    return {
        name: PackStat(
            count=count,
            mtime=newest.get(name, 0.0),
            added=oldest.get(name, 0.0),
        )
        for name, count in counts.items()
    }


def sort_packs(
    stats: dict[str, PackStat], order: str = PACK_ORDER_COUNT
) -> list[str]:
    """パック名を並べる。

    | 並び | 主キー | 同じときの落とし所 |
    | --- | --- | --- |
    | `PACK_ORDER_COUNT` | 件数の多い順 | 名前順 |
    | `PACK_ORDER_NAME` | 名前順 | — |
    | `PACK_ORDER_MTIME` | 更新日時の**新しい順** | 名前順 |
    | `PACK_ORDER_ADDED` | 追加日時の**古い順** | 名前順 |

    **同じ値のときに名前順へ落とすのは、並びを毎回同じにするため。**
    順番が揺れると、覚えた位置が使えなくなる。
    """
    if order == PACK_ORDER_NAME:
        return sorted(stats, key=str.lower)
    if order == PACK_ORDER_MTIME:
        return sorted(stats, key=lambda n: (-stats[n].mtime, n.lower()))
    if order == PACK_ORDER_ADDED:
        # **古い順。** 入れた順に辿るための並び。
        # 日時が取れないものは末尾へ（先頭に来ると邪魔になる）。
        return sorted(
            stats,
            key=lambda n: (
                stats[n].added <= 0,
                stats[n].added,
                n.lower(),
            ),
        )
    return sorted(stats, key=lambda n: (-stats[n].count, n.lower()))


def next_pack_order(order: str) -> str:
    """順送りで次の並び順。**知らない値なら既定へ戻す。**"""
    values = [value for value, _ in PACK_ORDER_OPTIONS]
    if order not in values:
        return values[0]
    return values[(values.index(order) + 1) % len(values)]
