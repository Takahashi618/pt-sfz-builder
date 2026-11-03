"""作者の別のプロジェクトから借りる部品を探す。**探し方をここ 1 か所に集める。**

読み上げや素材の索引などの部品は、作者の別のプロジェクトから借りている。
部品には中立の名前を付けて呼ぶ。

    speech_and_preview   読み上げ・試聴・効果音
    sample_index         Splice の索引・ファイル名の解析・長さの変換

探す順番:

1. このプロジェクトの `siblings/<名前>/`（公開しているソースと配布版。部品の写しが入っている）
2. 作者の手元では、同じ親フォルダに並んだ別のプロジェクト
   （本当のフォルダ名は `sibling_dirs.json`。公開しない）

### なぜまとめたか

以前は同じ探索が何か所にも写してあり、**すでに食い違っていた**（キャッシュの有無、深さの扱い）。
置き場所が変わったときに 1 か所直し忘れると、
「ルートキーは分かるのにテンポだけ読めない」のような、
原因の分かりにくい壊れ方をする。

**見つからなくても落ちない。** 借り物が無ければ、その機能だけが
使えなくなる（読み上げ名が付かない、検索が使えない）。
アプリ自体は起動する。

### 配布版（PyInstaller で固めた .app。2026-10-25 から）

借りる部品を `.app` の中の `siblings/` に同梱する（`BUNDLE_PARTS`。
`tools/build_release.py` が詰める）。読み込み方は同じ。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .i18n import is_english

__all__ = [
    "FROZEN",
    "PROJECT_ROOT",
    "BUNDLE_SIBLINGS",
    "DEV_DIRS_FILE",
    "BUNDLE_PARTS",
    "find_sibling",
    "load_ptcore",
    "part_key_label",
    "part_message",
]

# PyInstaller で固めた配布版として動いているか
FROZEN = bool(getattr(sys, "frozen", False))

# このプロジェクトの根。`core/` の 1 つ上（配布版では、.app の中の部品の置き場所）。
PROJECT_ROOT = (
    Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parents[1]
)

# 配布版と公開しているソースで、借りる部品を置く場所
BUNDLE_SIBLINGS = PROJECT_ROOT / "siblings"

# 手元の隣のフォルダの本当の名前（中立の名前 → フォルダ名）。**公開しない。**
# 配布物には関係の無い名前を載せないので、コードには中立の名前だけを書く
DEV_DIRS_FILE = PROJECT_ROOT / "sibling_dirs.json"

# 配布版に同梱する借り物（中立の名前 → その中のファイル）。
# **`ui/borrowed.py` と `load_ptcore` が読むもの全部。** 足したら
# `tests/test_release.py` が気づく（借りているのに同梱していない部品、それらが読む部品があれば落ちる）。
# **ptcore は使うものと、それらが読むものだけ。`__init__.py` は入れない**（中で関係の無いモジュールまで
# 読む。無ければ名前空間パッケージとして読めて、相対 import も通る）
BUNDLE_PARTS: dict[str, tuple[str, ...]] = {
    "speech_and_preview": (
        "ui/ax_label.py",
        "ui/announce.py",
        "ui/sounds.py",
        "ui/wx_keys.py",
        "audio/player.py",
    ),
    "sample_index": (
        "ptcore/audiofile.py",
        "ptcore/dsp.py",
        "ptcore/keydetect.py",
        "ptcore/library.py",
        "ptcore/prep.py",
        "ptcore/splicename.py",
    ),
}

# プロジェクトの根から上へ何段目を見るか（`parents` の添字）。**0 段目が本命。**
_DEPTHS = (0, 1)

_MISSING = object()
_cache: dict[str, Any] = {}


def _sibling_roots() -> list[Path]:
    """手元で隣のプロジェクトを探す場所。"""
    return [
        PROJECT_ROOT.parents[depth]
        for depth in _DEPTHS
        if depth < len(PROJECT_ROOT.parents)
    ]


def _dev_dirs() -> dict[str, str]:
    """手元の隣のフォルダの本当の名前。無い・読めなければ空（名前のまま探す）。"""
    try:
        data = json.loads(DEV_DIRS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def find_sibling(name: str, marker: str = "") -> Path | None:
    """借りる部品のフォルダを探す。見つからなければ None。

    Args:
        name: 部品の中立の名前（`sample_index` など）。
        marker: 中にあるはずのファイルの相対パス。
            **本物かどうかを確かめるため**に使う。同名の空フォルダを
            掴んで、あとで分かりにくい ImportError になるのを防ぐ。
    """
    candidates = [BUNDLE_SIBLINGS / name]
    if not FROZEN:
        folder = _dev_dirs().get(name, name)
        candidates += [root / folder for root in _sibling_roots()]
    for base in candidates:
        if not base.is_dir():
            continue
        if marker and not (base / marker).exists():
            continue
        return base
    return None


def load_ptcore(name: str) -> Any | None:
    """`sample_index` の `ptcore/<name>.py` を読み込む。**一度だけ試す。**

    失敗したら None を覚えて、以後は再試行しない。
    `decide_tempo` は素材 1 件ごとに呼ばれるので、
    毎回ディスクを見に行くと無駄が積み上がる。
    """
    cached = _cache.get(name, _MISSING)
    if cached is not _MISSING:
        return cached

    module: Any | None = None
    root = find_sibling("sample_index", "ptcore/splicename.py")
    if root is not None:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            module = __import__(f"ptcore.{name}", fromlist=[name])
        except ImportError:
            module = None
    _cache[name] = module
    return module


# 部品が返す言葉（日本語だけ）→ 英語。部品はほかのアプリも借りているので部品の側は
# 変えず、ここで言い換える。部品の文言が変わると英語に日本語が混ざるので、
# tests/test_i18n.py が部品のソースと突き合わせる。長い文を先に置く
_PART_WORDS = (
    ("移調やタイムストレッチに使える道具がありません。ffmpeg か rubberband を入れてください"
     "（brew install ffmpeg rubberband）",
     "No tool for transposing and time stretching was found. Install ffmpeg "
     "or rubberband (brew install ffmpeg rubberband)"),
    ("チャンネル数を合わせるには ffmpeg が要ります（brew install ffmpeg）",
     "Changing the channel count needs ffmpeg (brew install ffmpeg)"),
    ("チャンネル数を合わせるには ffmpeg が要ります", "Changing the channel count needs ffmpeg"),
    ("チャンネル数を変えられませんでした: ", "Could not change the channel count: "),
    ("チャンネル数・サンプルレート・ビット深度が不正です", "The channel count, sample rate or bit depth is invalid"),
    ("元のファイルがありません: ", "The source file does not exist: "),
    ("出力先を作れません: ", "Cannot create the output folder: "),
    ("コピーできません: ", "Cannot copy: "),
    ("出力ファイルができていません", "The output file was not created"),
    ("使えるバックエンドがありません", "No audio tool is available"),
    (" 秒で終わりませんでした", " seconds passed without finishing"),
    (" を起動できません: ", " could not be started: "),
    (" が失敗しました: ", " failed: "),
    ("終了コード ", "exit code "),
    ("チャンネル数は 1 以上です", "The channel count must be 1 or more"),
    ("キーとして解釈できません: ", "Cannot read this as a key: "),
    ("音名として解釈できません: ", "Cannot read this as a note: "),
    ("MIDI ノート番号が範囲外です: ", "The MIDI note number is out of range: "),
    ("BPM は正の値である必要があります", "BPM must be positive"),
    ("長さの比は正の値である必要があります", "The length ratio must be positive"),
    ("atempo に 0 以下は指定できません", "atempo must be greater than 0"),
    ("長さは 2 の冪である必要があります", "The length must be a power of 2"),
    ("間引き数は 1 以上である必要があります", "The decimation factor must be 1 or more"),
    ("拍子は正の値である必要があります", "The meter must be positive"),
    ("ループの小節数は正の値である必要があります", "The loop length in bars must be positive"),
    ("目標の小節数は正の値である必要があります", "The target length in bars must be positive"),
    ("多チャンネルのまま間引くと左右が混ざります。mono=True にするか、decimate を 1 にしてください",
     "Decimating several channels mixes left and right. Use mono=True or set decimate to 1"),
)


def part_message(text: str) -> str:
    """部品が返す文言を、いまの言語にする（表に無いファイル名などはそのまま残す）。"""
    if is_english():
        for ja, en in _PART_WORDS:
            text = text.replace(ja, en)
    return text


def part_key_label(label: str) -> str:
    """部品が返すキーの名前（`Cマイナー`・`不明`）を、いまの言語にする。

    **`part_message` の表には入れない。** 文の中の言葉を置き換える表に入れると、
    文に含まれるファイル名（`/x/Cマイナー.wav`）まで書き換えてしまう。
    """
    if not is_english():
        return label
    if label == "不明":
        return "unknown"
    for ja, en in (("マイナー", " minor"), ("メジャー", " major")):
        if label.endswith(ja):
            return label[: -len(ja)] + en
    return label
