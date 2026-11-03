"""SFZ 形式の生成と読み戻し。

このモジュールは純粋で、ファイル I/O も OS 依存も持たない。
Windows 上で全経路をテストできる。

生成物の規約（DESIGN_SFZ.md「9. SFZ 生成の落とし穴」より）:

- **1 行 1 オプコード。** `sample=` は値にスペースを含みうるため必ず行の最後に置く
- 数値の書式は fmt_number に一本化する（指数表記を出さない）
- コメントは `//` のみ。`/* */` はサポートが不安定なので使わない
- ノート指定は必ず数値。音名表記（`c4`）は実装により C4=60 か 72 かが割れる
"""

from __future__ import annotations

from .i18n import tr

import re
from dataclasses import dataclass, field

__all__ = [
    "SfzError",
    "fmt_number",
    "Opcode",
    "Region",
    "SfzDocument",
    "render",
    "parse",
]

# オプコード名として許す文字。SFZ 仕様は英小文字・数字・アンダースコア
_OPCODE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# ノート番号を値に取るオプコード。範囲検査の対象
NOTE_OPCODES = frozenset(
    {"lokey", "hikey", "key", "pitch_keycenter", "sw_lokey", "sw_hikey", "sw_last"}
)

# 本モジュールが解釈するヘッダ
_HEADER_GLOBAL = "<global>"
_HEADER_REGION = "<region>"
_HEADER_CONTROL = "<control>"
_KNOWN_HEADERS = frozenset({_HEADER_GLOBAL, _HEADER_REGION, _HEADER_CONTROL})


class SfzError(RuntimeError):
    """SFZ の生成・解析に失敗したことを表す。"""


def fmt_number(value: float | int) -> str:
    """数値を SFZ に書ける文字列にする。

    指数表記を出さないことが要点。``f"{0.00001:g}"`` は ``1e-05`` になり、
    SFZ のパーサが解釈できない。小数点以下 6 桁で丸め、末尾の 0 を落とす。

    >>> fmt_number(0.001)
    '0.001'
    >>> fmt_number(18000)
    '18000'
    >>> fmt_number(0.02)
    '0.02'
    """
    if isinstance(value, bool):  # bool は int の派生。事故を防ぐため先に弾く
        raise SfzError(tr(
            f"真偽値は数値として書けません: {value!r}",
            f"A boolean cannot be written as a number: {value!r}",
        ))
    if isinstance(value, int):
        return str(value)
    if value != value:  # NaN
        raise SfzError(tr("NaN は書けません", "NaN cannot be written"))
    if value in (float("inf"), float("-inf")):
        raise SfzError(tr("無限大は書けません", "Infinity cannot be written"))
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


@dataclass(frozen=True)
class Opcode:
    """1 個のオプコード。

    値を常に文字列で持つのは、**浮動小数の書式をここより外に漏らさないため。**
    ``0.1`` が ``0.1`` になるか ``0.10000000000000001`` になるかを
    呼び出し側で心配しなくて済む。
    """

    name: str
    value: str

    def __post_init__(self) -> None:
        if not _OPCODE_NAME_RE.match(self.name):
            raise SfzError(tr(
                f"オプコード名が不正です: {self.name!r}",
                f"Invalid opcode name: {self.name!r}",
            ))
        if "\n" in self.value or "\r" in self.value:
            raise SfzError(tr(
                f"オプコードの値に改行を含められません: {self.name}",
                f"An opcode value cannot contain a line break: {self.name}",
            ))
        if self.name in NOTE_OPCODES:
            _check_note_value(self.name, self.value)

    @classmethod
    def number(cls, name: str, value: float | int) -> "Opcode":
        """数値からオプコードを作る。書式は fmt_number に委ねる。"""
        return cls(name, fmt_number(value))

    def render(self) -> str:
        return f"{self.name}={self.value}"


def _check_note_value(name: str, value: str) -> None:
    """ノート番号が 0〜127 の整数であることを確かめる。

    音名表記を弾くのも役目のうち。``pitch_keycenter=c4`` は実装により
    60 とも 72 とも解釈されるため、本ツールでは常に数値で書く。
    """
    try:
        note = int(value)
    except ValueError:
        raise SfzError(
            tr(
                f"{name} は数値で指定してください（音名表記はオクターブがずれます）: {value!r}",
                f"{name} must be a number (note names shift the octave): {value!r}",
            )
        ) from None
    if not 0 <= note <= 127:
        raise SfzError(tr(
            f"{name} が MIDI ノートの範囲外です: {note}",
            f"{name} is out of the MIDI note range: {note}",
        ))


@dataclass
class Region:
    """1 つのサンプルと、それが鳴る条件。

    ``sample`` を独立したフィールドに切り出しているのは、レンダリング時に
    **必ず行の最後へ回すため。** 値にスペースを含みうるので、後ろに他の
    オプコードが続くとパーサによっては値の一部として食われる。
    """

    sample: str
    opcodes: list[Opcode] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sample or not self.sample.strip():
            raise SfzError(tr("sample のパスが空です", "The sample path is empty"))
        if "\n" in self.sample or "\r" in self.sample:
            raise SfzError(tr(
                "sample のパスに改行を含められません",
                "The sample path cannot contain a line break",
            ))

    def get(self, name: str) -> str | None:
        """オプコードの値を取り出す。無ければ None。"""
        for opcode in self.opcodes:
            if opcode.name == name:
                return opcode.value
        return None


@dataclass
class SfzDocument:
    """SFZ ファイル 1 つ分。

    本ツールが使う階層は ``<control>`` / ``<global>`` / ``<region>`` の 3 種だけ。
    ``<group>`` と ``<master>`` は使わない（継承の段数を減らして事故を防ぐ）。
    """

    regions: list[Region] = field(default_factory=list)
    global_opcodes: list[Opcode] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    default_path: str | None = None

    def __post_init__(self) -> None:
        for comment in self.comments:
            if "\n" in comment or "\r" in comment:
                raise SfzError(tr(
                    "コメントに改行を含められません",
                    "A comment cannot contain a line break",
                ))
        if self.default_path is not None and not self.default_path.endswith("/"):
            raise SfzError(
                tr(
                    f"default_path は末尾に / が要ります: {self.default_path!r}",
                    f"default_path must end with /: {self.default_path!r}",
                )
            )


def render(doc: SfzDocument) -> str:
    """SfzDocument を SFZ のテキストにする。純粋関数。

    出力は「コメント → <control> → <global> → <region> の並び」で固定する。
    順序を固定しておくと、往復テストで文字列比較ができる。
    """
    lines: list[str] = []

    for comment in doc.comments:
        lines.append(f"// {comment}" if comment else "//")
    if doc.comments:
        lines.append("")

    if doc.default_path is not None:
        lines.append(_HEADER_CONTROL)
        lines.append(f"default_path={doc.default_path}")
        lines.append("")

    if doc.global_opcodes:
        lines.append(_HEADER_GLOBAL)
        lines.extend(opcode.render() for opcode in doc.global_opcodes)
        lines.append("")

    for region in doc.regions:
        lines.append(_HEADER_REGION)
        lines.extend(opcode.render() for opcode in region.opcodes)
        # sample= は必ず最後。ここが本モジュールで最も壊してはいけない一行
        lines.append(f"sample={region.sample}")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def parse(text: str) -> SfzDocument:
    """SFZ のテキストを読み戻す。往復テスト用の最小実装。

    自分の生成物を読み返せることを保証するのが目的なので、
    知らないヘッダは黙って無視せずエラーにする。
    """
    comments: list[str] = []
    global_opcodes: list[Opcode] = []
    regions: list[Region] = []
    default_path: str | None = None

    section: str | None = None
    pending: list[Opcode] = []
    pending_sample: str | None = None
    in_leading_comments = True

    def close_region() -> None:
        nonlocal pending, pending_sample
        if section != _HEADER_REGION:
            return
        if pending_sample is None:
            raise SfzError(tr(
                "sample= の無い <region> があります",
                "There is a <region> with no sample=",
            ))
        regions.append(Region(sample=pending_sample, opcodes=pending))
        pending = []
        pending_sample = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("//"):
            if in_leading_comments:
                comments.append(line[2:].strip())
            continue
        in_leading_comments = False

        if line.startswith("<"):
            close_region()
            if line not in _KNOWN_HEADERS:
                raise SfzError(tr(
                    f"{lineno} 行目: 未対応のヘッダです: {line}",
                    f"Line {lineno}: unsupported header: {line}",
                ))
            section = line
            continue

        name, sep, value = line.partition("=")
        if not sep:
            raise SfzError(tr(
                f"{lineno} 行目: オプコードとして読めません: {line!r}",
                f"Line {lineno}: cannot be read as an opcode: {line!r}",
            ))
        name = name.strip()
        value = value.strip()

        if section is None:
            raise SfzError(tr(
                f"{lineno} 行目: ヘッダより前にオプコードがあります: {line!r}",
                f"Line {lineno}: an opcode comes before any header: {line!r}",
            ))

        if section == _HEADER_CONTROL:
            if name != "default_path":
                raise SfzError(tr(
                    f"{lineno} 行目: <control> に未対応のオプコード: {name}",
                    f"Line {lineno}: unsupported opcode in <control>: {name}",
                ))
            default_path = value
        elif section == _HEADER_GLOBAL:
            global_opcodes.append(Opcode(name, value))
        else:  # <region>
            if name == "sample":
                pending_sample = value
            else:
                pending.append(Opcode(name, value))

    close_region()
    return SfzDocument(
        regions=regions,
        global_opcodes=global_opcodes,
        comments=comments,
        default_path=default_path,
    )
