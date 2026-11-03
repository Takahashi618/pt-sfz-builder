"""kinds.py のテスト。

**作者の別のアプリと規則を合わせる**のが目的なので、
向こうの規則をそのまま検査に落としてある。ここが崩れると
「同じサンプルがアプリによって違う種別になる」ことになる。
"""

from _harness import Checker

from core.kinds import (
    DEFAULT_ONESHOT_MAX_SEC,
    KIND_FX,
    KIND_LOOP,
    KIND_ONESHOT,
    PACK_ORDER_ADDED,
    PACK_ORDER_COUNT,
    PACK_ORDER_MTIME,
    PACK_ORDER_NAME,
    PACK_ORDER_OPTIONS,
    kind_from_duration,
    next_pack_order,
    pack_stats,
    resolve_kind,
    sort_packs,
)

c = Checker("kinds")

# ==========================================================================
# 長さから種別
# ==========================================================================

c.equal("境目は 2.0 秒", DEFAULT_ONESHOT_MAX_SEC, 2.0)
c.equal("短ければワンショット", kind_from_duration(1.0), KIND_ONESHOT)
c.equal("境目ちょうどはワンショット", kind_from_duration(2.0), KIND_ONESHOT)
c.equal("超えたらループ", kind_from_duration(2.1), KIND_LOOP)
c.equal("分からなければ None", kind_from_duration(None), None)
c.equal("0 秒は判断しない", kind_from_duration(0.0), None)
c.equal("境目を変えられる", kind_from_duration(3.0, 5.0), KIND_ONESHOT)

# ==========================================================================
# 種別を決める — **長さを優先する**
# ==========================================================================

# 規則 1: 長い音はファイル名が何であれループ。
# **これが要点。** 実測（本ライブラリ 3127 件）で、ファイル名だけの判定で
# ワンショットとされた 685 件のうち 227 件（33%）が 2 秒を超えていた。
c.equal("長いワンショットはループ扱い", resolve_kind("one_shot", 5.0), KIND_LOOP)
c.equal("長い上に名前もループ", resolve_kind("loop", 5.0), KIND_LOOP)

# 規則 2: 短い音はファイル名の判定に従う（短いドラムループを拾う）
c.equal("短いループはループのまま", resolve_kind("loop", 1.0), KIND_LOOP)
c.equal("短いワンショット", resolve_kind("one_shot", 1.0), KIND_ONESHOT)

# 規則 3: 長さが分からなければファイル名に従う
c.equal("長さ不明ならファイル名", resolve_kind("one_shot", None), KIND_ONESHOT)
c.equal("長さ不明でループ", resolve_kind("loop", None), KIND_LOOP)

# ファイル名から分からないときは長さで決める（種別不明を減らす）
c.equal("名前が無くても長さで決まる", resolve_kind("", 1.0), KIND_ONESHOT)
c.equal("名前が無く長い", resolve_kind(None, 9.0), KIND_LOOP)
c.equal("どちらも無ければ空", resolve_kind("", None), "")

# **効果音は長さで覆さない。** ここだけ 作者の別のアプリと違う。
# あちらは 2 種類しか持たないが、splicename は効果音を別に判定する。
# 5 秒の効果音をループと言い換えると、かえって探しにくい。
c.equal("長い効果音は効果音のまま", resolve_kind("fx", 9.0), KIND_FX)
c.equal("短い効果音も効果音", resolve_kind("fx", 0.5), KIND_FX)
c.equal("長さ不明の効果音", resolve_kind("fx", None), KIND_FX)

# 前後の空白は無視する
c.equal("空白は落とす", resolve_kind("  loop  ", None), KIND_LOOP)

# 境目を渡せる
c.equal("境目を変えられる", resolve_kind("one_shot", 3.0, 5.0), KIND_ONESHOT)


# ==========================================================================
# パックの並び順
# ==========================================================================


class E:
    def __init__(self, pack, mtime=0.0):
        self.pack = pack
        self.mtime = mtime


entries = (
    [E("Big", 100.0)] * 50
    + [E("Same", 100.0)] * 50
    + [E("Mid", 900.0)] * 3
    + [E("Tiny", 500.0)]
)
counts = {name: stat.count for name, stat in pack_stats(entries).items()}
c.equal("数えられる", counts, {"Big": 50, "Same": 50, "Mid": 3, "Tiny": 1})

stats = pack_stats(entries)
c.equal("件数を持つ", stats["Big"].count, 50)
# **更新日時は最も新しい素材、追加日時は最も古い素材。** 意味が違う。
# Splice は素材を 1 つずつ落とすので、同じパックでも離れる。
c.equal("いちばん新しい日時を採る", stats["Mid"].mtime, 900.0)
mixed = pack_stats([E("P", 10.0), E("P", 90.0), E("P", 50.0)])["P"]
c.equal("新旧が混ざっても最新", mixed.mtime, 90.0)
c.equal("追加は最古", mixed.added, 10.0)

# **0 は「日時が無い」なので最古の候補にしない。**
# 1 件でも日時の無い素材があると、そのパックが常に先頭へ来てしまう。
holed = pack_stats([E("P", 0.0), E("P", 50.0), E("P", 80.0)])["P"]
c.equal("0 は最古にしない", holed.added, 50.0)
c.equal("最新は変わらない", holed.mtime, 80.0)
c.equal("全部 0 なら 0", pack_stats([E("P", 0.0)])["P"].added, 0.0)

# **既定は中身の多い順。** 実測で 553 パック中 389 個が 1 件だけだった
# （作者の別のアプリ）。名前順だと目当ての大きなパックが埋もれる。
c.equal("多い順", sort_packs(stats), ["Big", "Same", "Mid", "Tiny"])
c.equal("既定は多い順", sort_packs(stats), sort_packs(stats, PACK_ORDER_COUNT))
c.equal("名前順", sort_packs(stats, PACK_ORDER_NAME), ["Big", "Mid", "Same", "Tiny"])
# **更新は新しい順。** 最近さわったパックを探すため。
c.equal("更新の新しい順", sort_packs(stats, PACK_ORDER_MTIME), ["Mid", "Tiny", "Big", "Same"])

# **追加は古い順。** 入れた順に辿るため。**更新とは逆向き。**
added_stats = pack_stats(
    [E("First", 100.0), E("First", 900.0), E("Second", 300.0), E("Third", 500.0)]
)
c.equal(
    "追加した順は古いものから",
    sort_packs(added_stats, PACK_ORDER_ADDED),
    ["First", "Second", "Third"],
)
# 同じデータで更新順にすると逆になる（First は 900 まで買い足している）
c.equal(
    "更新順とは並びが違う",
    sort_packs(added_stats, PACK_ORDER_MTIME),
    ["First", "Third", "Second"],
)

# 日時が取れないものは**末尾**へ。先頭に来ると邪魔になる。
with_hole = pack_stats([E("Known", 500.0), E("Unknown", 0.0)])
c.equal("日時不明は末尾", sort_packs(with_hole, PACK_ORDER_ADDED), ["Known", "Unknown"])

# **同じ値なら名前順。** 並びが毎回同じでないと、覚えた位置が使えなくなる。
same_count = pack_stats([E("B", 1.0), E("A", 1.0)])
c.equal("同数は名前順", sort_packs(same_count), ["A", "B"])
c.equal("同じ日時も名前順", sort_packs(same_count, PACK_ORDER_MTIME), ["A", "B"])
c.equal("追加日時が同じでも名前順", sort_packs(same_count, PACK_ORDER_ADDED), ["A", "B"])
c.check(
    "名前順は大文字小文字を区別しない",
    sort_packs(pack_stats([E("b"), E("A")]), PACK_ORDER_NAME) == ["A", "b"],
)

# 日時が無くても落ちない
no_time = pack_stats([type("X", (), {"pack": "P"})()])
c.equal("日時が無ければ 0", no_time["P"].mtime, 0.0)
c.equal("それでも並べられる", sort_packs(no_time, PACK_ORDER_MTIME), ["P"])

# パック名の無いものは数えない
c.equal("空のパックは除く", sorted(pack_stats([E(""), E(None), E("  "), E("X")])), ["X"])
c.equal("空の入力", pack_stats([]), {})
c.equal("空の並べ替え", sort_packs({}), [])

# --- 順送り ---
# **中身の多い順から始まる。** 既定がいちばん使うものだから。
c.equal("並び順は 4 つ", len(PACK_ORDER_OPTIONS), 4)
c.equal("先頭は多い順", PACK_ORDER_OPTIONS[0][0], PACK_ORDER_COUNT)
c.equal("多い順の次は名前順", next_pack_order(PACK_ORDER_COUNT), PACK_ORDER_NAME)
c.equal("名前順の次は更新順", next_pack_order(PACK_ORDER_NAME), PACK_ORDER_MTIME)
c.equal("更新順の次は追加順", next_pack_order(PACK_ORDER_MTIME), PACK_ORDER_ADDED)
c.equal("追加順の次は多い順", next_pack_order(PACK_ORDER_ADDED), PACK_ORDER_COUNT)

# **名前に向きが入っていること。** 「日時順」だけでは新旧どちらが上か
# 分からず、読み上げで聞いても確かめようがない。
labels = dict(PACK_ORDER_OPTIONS)
c.check("更新は向きが分かる", "新しい" in labels[PACK_ORDER_MTIME], labels[PACK_ORDER_MTIME])
c.check("追加も向きが分かる", "古い" in labels[PACK_ORDER_ADDED], labels[PACK_ORDER_ADDED])
# **知らない値なら既定へ戻す。** 設定ファイルが古いときに詰まらないため。
c.equal("知らない値は既定へ", next_pack_order("なにか"), PACK_ORDER_COUNT)
c.check("どれも日本語の名前がある", all(label for _, label in PACK_ORDER_OPTIONS))

raise SystemExit(c.summary())
