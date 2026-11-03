"""置き場所を決める。**手元の版と配布版で分ける。**

| もの | 手元の版（ソース・ランチャの .app） | 配布版（PyInstaller で固めた .app） |
| --- | --- | --- |
| スロット・下ごしらえ・設定 | プロジェクトの隣の `sfz_slots/` | `~/Music/SFZBuilder/` |
| Splice の索引 | 借りている部品の索引を共有 | スロットの置き場所の `splice_index.json` |
| Splice の素材 | 設定の値。空なら決まった場所を探す | 同じ |

**手元の版の置き場所は変えない。** Pro Tools のセッションは sforzando を通して
`.sfz` の**絶対パス**を覚えている（sforzando はパスしか保存しない）。
変えると、前に作ったセッションを開いたときに音が出なくなる。
以前は `core/slots.py` に作者の手元のパスがそのまま書いてあった
（配布物に入れてはいけない手元のパスで、ほかの Mac では書けない場所だった）。

**配布版は `~/Music/SFZBuilder/` に置く。**

- 書類フォルダは iCloud に同期されることがある。同期中のファイルを sforzando が
  読むと事故になる（iCloud 配下は避ける）
- `~/Music` は macOS の確認の対象外で、Finder からも見える
- **名前は ASCII にする。** sforzando に読ませるとき、この場所のパスを
  「開く」ダイアログへ貼り付ける。日本語でも通るが、濁点の分かれ方（NFC と NFD）で
  食い違う余地を残さない

アプリが作るものを 1 か所に集めるので、マニュアルで「消すならこのフォルダ」と言える。

OS 非依存（パスの組み立てと、あるかどうかの確認だけ）。
"""

from __future__ import annotations

from pathlib import Path

from .sibling import FROZEN, PROJECT_ROOT

__all__ = [
    "APP_FOLDER_NAME",
    "SPLICE_CANDIDATES",
    "default_slots_dir",
    "splice_index_path",
    "resolve_splice_root",
]

# 配布版の置き場所の名前（`~/Music/` の下）
APP_FOLDER_NAME = "SFZBuilder"

# Splice のパックが並ぶフォルダの候補（上から順に、あるものを使う）。Splice の版で名前が違う
SPLICE_CANDIDATES = (Path("~/Splice/sounds/packs"), Path("~/Splice/Samples/packs"))
# 選んだフォルダの中にこれがあれば、そちらをパックの並ぶフォルダとして使う
_PACK_SUBFOLDERS = ("sounds/packs", "Samples/packs", "packs")


def default_slots_dir() -> str:
    """スロット・下ごしらえ・設定の置き場所（絶対パス。末尾に区切りを付けない）。"""
    if FROZEN:
        return str(Path.home() / "Music" / APP_FOLDER_NAME)
    return str(PROJECT_ROOT.parent / "sfz_slots")


def splice_index_path(slots_dir: str) -> str | None:
    """Splice の索引の置き場所。**None は 借りている部品の索引を共有する**（手元の版）。

    **配布版は .app の中に書かない。** 借りた部品は既定で自分の
    `data/index.json` に書くが、配布版ではそこが .app の中になり、署名が壊れる
    （Finder から開いても無反応になる）。
    """
    if FROZEN:
        return str(Path(slots_dir) / "splice_index.json")
    return None


def resolve_splice_root(chosen: str = "") -> Path:
    """Splice のパックが並ぶフォルダ。`chosen` は設定の値（空なら決まった場所を探す）。

    - 選んだフォルダの中に `sounds/packs` などがあれば、そちらを使う
      （`~/Splice` そのものを選んでも、パックを数え間違えない。パックの名前は
      このフォルダの 1 段下のフォルダ名から取るため）
    - 空なら `SPLICE_CANDIDATES` のうち、あるもの。どれも無ければ最初の候補
      （索引を作るときに「見つかりません」と言う）
    """
    if chosen.strip():
        base = Path(chosen.strip()).expanduser()
        for sub in _PACK_SUBFOLDERS:
            if (base / sub).is_dir():
                return base / sub
        return base
    for candidate in SPLICE_CANDIDATES:
        if candidate.expanduser().is_dir():
            return candidate.expanduser()
    return SPLICE_CANDIDATES[0].expanduser()
