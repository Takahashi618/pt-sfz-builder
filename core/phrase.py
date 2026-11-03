"""フレーズを**速さを変えずに**鍵盤へ広げる。

### 何が問題か

SFZ に**タイムストレッチは無い**。音程を変える手段は再生速度を変えること
だけなので、1 つのサンプルを鍵盤全体に広げると、**音程と一緒に速さも変わる。**
ワンショットなら気にならないが、**フレーズやループでは実用にならない。**

    C3 で弾く → 元の速さ
    C4 で弾く → 2 倍の速さ（1 オクターブ上）

### どう解く

**鍵盤ごとに、あらかじめ伸ばしたファイルを用意する。**
SFZ が再生時に縮めるので、差し引きで元の長さに戻る。

    鍵盤 k、ルート r のとき、SFZ の再生速度比は  ratio = 2^((k-r)/12)
    あらかじめ長さを ratio 倍にしておけば、
    再生時に 1/ratio になって **元の長さに戻る**

    （上へ移すときは長くしておき、下へ移すときは短くしておく）

伸ばすのは**音程を変えない伸縮**（ffmpeg の `atempo`）。
これで「音程だけ変わって速さは同じ」が作れる。

    <region> lokey=k hikey=k pitch_keycenter=r sample=<k 用に伸ばしたファイル>

### テンポ合わせと組み合わせる

`core/tempo.py` が出したテンポの倍率を**掛け合わせる**だけでよい。

    最終の倍率 = 2^((k-r)/12) × （元のテンポ ÷ 目標のテンポ）

これで**どの鍵盤でもセッションのテンポで鳴る。**

倍率がちょうど 1 になる鍵盤（ふつうはルート）は加工が要らないので、
**元のファイルをそのまま指す。** 同じ中身のコピーを作らない。

### 代償

- **鍵盤の数だけファイルができる。** 上下 12 半音なら 25 個。
  13 秒のステレオ素材で 1 回あたり 90 MB ほどになるので、
  **使わなくなったものを片付ける手段が要る**（`unused_renders`）
- 伸ばすほど音は荒れる。1 オクターブを超えると分かる程度になる
- 用意した範囲の外は**鳴らない**。速さが変わる音を鳴らすより、
  鳴らないほうが分かりやすいと考えた（黙って速さが変わると気づけない）

ここは**計画だけ**を持つ。実際に伸ばすのは `integration/render.py`。
分けてあるのは、どのファイルをどの倍率で作るかを**実機なしで検証する**ため。
"""

from __future__ import annotations

from .i18n import plural, tr

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from .notes import MIDI_MAX, MIDI_MIN, note_name

__all__ = [
    "PHRASE_SPAN_DEFAULT",
    "PHRASE_SPAN_MAX",
    "RENDER_DIR_NAME",
    "PhraseError",
    "PhraseRender",
    "PhrasePlan",
    "phrase_filename",
    "plan_phrase",
    "unused_renders",
]

# 下ごしらえの置き場所（スロットの置き場所からの相対）。
RENDER_DIR_NAME = "rendered"

# ルートから上下に何半音まで用意するか。
# 12（上下 1 オクターブ、25 ファイル）を既定にする。これを超えると
# 伸縮の粗さが目立ち、作るのにも時間がかかる。
PHRASE_SPAN_DEFAULT = 12

# 上限。48 も 96 も作れはするが、**待ち時間と音質が見合わない。**
PHRASE_SPAN_MAX = 24


class PhraseError(ValueError):
    """フレーズの計画を立てられないことを表す。"""


@dataclass(frozen=True)
class PhraseRender:
    """1 鍵盤分の下ごしらえ。"""

    key: int  # この鍵盤に割り当てる
    root_key: int  # SFZ の pitch_keycenter。**ずらさない**
    tempo_ratio: float  # あらかじめ伸ばす倍率（出力の長さ ÷ 入力の長さ）
    source: str
    dest: str

    @property
    def offset(self) -> int:
        """ルートから何半音か。正で上。"""
        return self.key - self.root_key

    @property
    def is_original(self) -> bool:
        """加工が要らないか。**倍率が 1 かどうかで判断する。**

        半音のずれが 0 でも、テンポを変えるなら加工が要る。
        「ルートかどうか」で判断すると、テンポだけ変える場合を取りこぼす。
        """
        return abs(self.tempo_ratio - 1.0) <= 1e-9

    def describe_ja(self) -> str:
        if self.is_original:
            return tr(f"{note_name(self.key)}、元のまま", f"{note_name(self.key)}, unchanged")
        if self.offset == 0:
            return tr(
                f"{note_name(self.key)}、長さを{self.tempo_ratio:.3f}倍にする",
                f"{note_name(self.key)}, length times {self.tempo_ratio:.3f}",
            )
        direction = tr("上", "up") if self.offset > 0 else tr("下", "down")
        # **「伸ばす」と言わない。** 下へ移すときは縮むので、嘘になる。
        return tr(
            f"{note_name(self.key)}、{abs(self.offset)}半音{direction}、"
            f"長さを{self.tempo_ratio:.3f}倍にする",
            f"{note_name(self.key)}, {plural(abs(self.offset), 'semitone')} {direction}, "
            f"length times {self.tempo_ratio:.3f}",
        )


@dataclass(frozen=True)
class PhrasePlan:
    """鍵盤ぶんの下ごしらえひとそろい。"""

    renders: tuple[PhraseRender, ...]
    root_key: int
    span: int

    @property
    def lokey(self) -> int:
        return self.renders[0].key

    @property
    def hikey(self) -> int:
        return self.renders[-1].key

    @property
    def work_count(self) -> int:
        """実際に作るファイルの数。ルートは加工が要らないので除く。"""
        return sum(1 for r in self.renders if not r.is_original)

    def describe_ja(self) -> str:
        return tr(
            f"ルートキー{note_name(self.root_key)}、"
            f"{note_name(self.lokey)}から{note_name(self.hikey)}まで、"
            f"速さを変えずに{len(self.renders)}鍵盤へ広げます。"
            f"下ごしらえに{self.work_count}個のファイルを作ります。",
            f"Root key {note_name(self.root_key)}, {note_name(self.lokey)} to "
            f"{note_name(self.hikey)}, spreading over {plural(len(self.renders), 'key')} "
            f"without changing the speed. Creating {plural(self.work_count, 'prepared file')}.",
        )


def _stem(path: str) -> str:
    """パスからファイル名の本体を取り出す。**OS を問わない。**"""
    name = PurePosixPath(path).name
    if "\\" in name:
        name = PureWindowsPath(path).name
    return name.rsplit(".", 1)[0] if "." in name else name


def _tag(source: str) -> str:
    """元のパスから短い識別子を作る。

    **名前だけだと衝突する。** 別のパックに同じファイル名があると、
    片方の下ごしらえをもう片方が使ってしまう。
    """
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]


def phrase_filename(source: str, offset: int, tempo_tag: str = "") -> str:
    """下ごしらえの出力ファイル名。

    **同じ素材・同じ半音数・同じテンポなら必ず同じ名前になる。**
    作り直しを避けられる。

    `tempo_tag` はテンポを変えるときだけ付ける（`core/tempo.tempo_tag`）。
    付け忘れると、テンポを変えた版と変えていない版が同じ名前になり、
    **古いほうを使い回してしまう。**
    """
    suffix = f"__{tempo_tag}" if tempo_tag else ""
    return f"{_stem(source)}__{_tag(source)}__p{offset:+03d}{suffix}.wav"


def plan_phrase(
    source: str,
    root_key: int,
    *,
    span: int = PHRASE_SPAN_DEFAULT,
    out_dir: str,
    tempo_ratio: float = 1.0,
    tempo_tag: str = "",
) -> PhrasePlan:
    """鍵盤ごとの下ごしらえを計画する。**純粋関数。**

    Args:
        source: 元のサンプル。
        root_key: 元の音程が鳴る鍵盤。
        span: ルートから上下に何半音まで用意するか。
        out_dir: 下ごしらえの置き場所。
        tempo_ratio: テンポ合わせの倍率（`core/tempo.py` が決める）。
            鍵盤ごとの倍率に**掛け合わせる**ので、どの鍵盤でも
            セッションのテンポで鳴る。
        tempo_tag: 出力ファイル名に付ける印。テンポを変えるときだけ。

    範囲が MIDI の外へ出る分は切り詰める。**黙って外の鍵盤を作らない。**
    """
    if not source.strip():
        raise PhraseError(tr("元のサンプルが指定されていません", "No source sample was given"))
    if not MIDI_MIN <= root_key <= MIDI_MAX:
        raise PhraseError(tr(
            f"ルートキーが MIDI ノートの範囲外です: {root_key}",
            f"The root key is out of the MIDI note range: {root_key}",
        ))
    if not 1 <= span <= PHRASE_SPAN_MAX:
        raise PhraseError(
            tr(
                f"用意する範囲は 1〜{PHRASE_SPAN_MAX} 半音です: {span}",
                f"The range to prepare is 1 to {PHRASE_SPAN_MAX} semitones: {span}",
            )
        )
    if not out_dir.strip():
        raise PhraseError(tr(
            "下ごしらえの置き場所が指定されていません",
            "No folder was given for the prepared files",
        ))
    if tempo_ratio <= 0:
        raise PhraseError(tr(
            f"テンポの倍率は正の数です: {tempo_ratio}",
            f"The tempo ratio must be positive: {tempo_ratio}",
        ))

    base = out_dir.rstrip("/\\")
    lokey = max(MIDI_MIN, root_key - span)
    hikey = min(MIDI_MAX, root_key + span)

    renders = []
    for key in range(lokey, hikey + 1):
        offset = key - root_key
        # SFZ が再生する速度比。これと同じ倍率だけ**あらかじめ伸ばす**。
        # テンポ合わせの倍率も**掛け合わせる**。
        ratio = (2.0 ** (offset / 12.0)) * tempo_ratio
        dest = (
            source
            if abs(ratio - 1.0) <= 1e-9
            else f"{base}/{phrase_filename(source, offset, tempo_tag)}"
        )
        renders.append(
            PhraseRender(
                key=key,
                root_key=root_key,
                tempo_ratio=ratio,
                source=source,
                dest=dest,
            )
        )
    return PhrasePlan(renders=tuple(renders), root_key=root_key, span=span)


def _norm_path(path: object) -> str:
    """比較用にパスをそろえる。**OS を問わない。**

    `.sfz` に書くのは常に `/` 区切り（`plan_phrase` が組み立てる）だが、
    置き場所を走査した側は OS の区切りで返ってくる。**そろえずに比べると、
    Windows では参照中のファイルまで「使われていない」に入る。**
    """
    text = str(path).strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.rstrip("/")


def _base_name(path: object) -> str:
    return _norm_path(path).rsplit("/", 1)[-1]


def unused_renders(referenced: object, present: object) -> list[str]:
    """使われていない下ごしらえを挙げる。**消しはしない。**

    Args:
        referenced: いまのスロットが参照しているパスの集まり。
        present: 下ごしらえの置き場所にあるパスの集まり。

    判断と実行を分けてあるのは、**消す前に一覧を読み上げられるように**
    するため。消してしまってから「あれが要った」と気づいても遅い。

    **迷ったら残す。** パスの綴りが揃わないことがあるので、
    区切りをそろえた全体と、ファイル名だけの両方で照合する。
    ファイル名には元のパスの短い識別子が入っている（`phrase_filename`）
    ので、別の素材のものと取り違えることはない。
    """
    keep_paths = {_norm_path(path) for path in referenced}  # type: ignore[union-attr]
    keep_names = {_base_name(path) for path in referenced}  # type: ignore[union-attr]
    return sorted(
        str(path)
        for path in present  # type: ignore[union-attr]
        if _norm_path(path) not in keep_paths and _base_name(path) not in keep_names
    )
