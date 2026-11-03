"""core/places.py のテスト。**手元の版と配布版の置き場所。**"""

import tempfile
from pathlib import Path

from _harness import Checker

from core import places
from core.sibling import PROJECT_ROOT
from core.slots import SlotLayout, SlotLedger

c = Checker("places")

# ==========================================================================
# 手元の版
# ==========================================================================
#
# **置き場所を変えない。** Pro Tools のセッションは `.sfz` の絶対パスを
# 覚えているので、変えると前に作ったセッションで音が出なくなる。
# 以前は作者の手元のパスがそのまま書いてあった（配布物に入れてはいけない）。

c.equal(
    "手元の版はプロジェクトの隣の sfz_slots",
    places.default_slots_dir(),
    str(PROJECT_ROOT.parent / "sfz_slots"),
)
c.equal("台帳の既定も同じ", SlotLayout().slots_dir, places.default_slots_dir())
c.equal("手元の版の索引は 借りている部品と共有", places.splice_index_path("/x"), None)

# 置き場所を書いていない古い台帳も、既定の置き場所で読める
ledger = SlotLedger.from_json('{"version": 1, "layout": {}, "assignments": []}')
c.equal("古い台帳は既定の置き場所", ledger.layout.slots_dir, places.default_slots_dir())

# ==========================================================================
# 配布版
# ==========================================================================
#
# **.app の中に書かない。** 借りた部品は既定で自分の data/ に
# 索引を書くが、配布版ではそこが .app の中になり、署名が壊れる。

saved = places.FROZEN
places.FROZEN = True
try:
    c.equal(
        "配布版はミュージックの SFZBuilder",
        places.default_slots_dir(),
        str(Path.home() / "Music" / "SFZBuilder"),
    )
    c.check("名前は ASCII", places.APP_FOLDER_NAME.isascii())
    c.equal(
        "配布版の索引はスロットの置き場所",
        places.splice_index_path("/Volumes/Audio/Music/SFZBuilder"),
        "/Volumes/Audio/Music/SFZBuilder/splice_index.json",
    )
finally:
    places.FROZEN = saved

# ==========================================================================
# Splice のフォルダ
# ==========================================================================

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "Splice"
    (root / "sounds" / "packs").mkdir(parents=True)
    c.equal(
        "Splice のフォルダを選んでも、パックの並ぶフォルダを使う",
        places.resolve_splice_root(str(root)),
        root / "sounds" / "packs",
    )
    packs = root / "sounds" / "packs"
    c.equal("パックの並ぶフォルダを選べばそのまま", places.resolve_splice_root(str(packs)), packs)
    other = Path(tmp) / "自分の素材"
    other.mkdir()
    c.equal("中に packs が無ければ選んだフォルダ", places.resolve_splice_root(str(other)), other)
    c.equal(
        "前後の空白は落とす",
        places.resolve_splice_root(f"  {packs}  "),
        packs,
    )

c.check(
    "空なら決まった場所（ホームの Splice）",
    str(places.resolve_splice_root("")).startswith(str(Path.home())),
    str(places.resolve_splice_root("")),
)

raise SystemExit(c.summary())
