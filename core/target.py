"""前面のプラグインウィンドウが「どのトラックの何か」を解釈する。

**Pro Tools のプラグインウィンドウのタイトルは `Plug-in: <プラグイン名>` で、
トラック名を含まない**（2026-08-07 実測）。
トラック名は AX の `Track Selector` の値から取る。

    AXWindow title='Plug-in: sforzando'
      AXPopUpButton 'Track Selector'   -> 'Inst1'      ← どのインスタンスか
      AXPopUpButton 'Plugin Selector'  -> 'sforzando'  ← プラグインの種類

`ExportSessionInfoAsText` のプラグイン一覧では「何個あるか」しか分からず
トラックとの対応が付かないので、**開いているウィンドウを見るのが唯一の手段**になる。

AX からの取得そのものは Mac 側（integration 層）の仕事で、ここは受け取った
文字列を解釈するだけ。OS 非依存なので Windows で全経路をテストできる。

sforzando / Decent Sampler でも同じ構造かは未確認（S4）。書式が違っていても
拾えるよう、**タイトルだけからの解釈も残してある**。実機で確定したら
使わない経路を削ればよい。
"""

from __future__ import annotations

from .i18n import tr

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .slots import PluginKind

__all__ = [
    "WindowInfo",
    "PluginTarget",
    "detect_plugin",
    "split_insert_marker",
    "parse_window_title",
    "build_target",
    "choose_front_target",
]

# "Plug-in: sforzando" / "Plugin: sforzando" のいずれも受ける。
# これに合致したら、**タイトルにトラック名は入っていない**。
_PLUGIN_PREFIX = re.compile(r"^\s*plug\s*-?\s*in\s*:\s*", re.IGNORECASE)

# タイトルにトラック名が入る書式だった場合の区切り。長いものから試す。
_SEPARATORS: tuple[str, ...] = (" - ", " – ", " — ", ": ", " / ", " | ", "-", ":", "|")

# インサートスロットの表記。上ほど確実で、下へ行くほど誤認しやすい。
_EXPLICIT_INSERT = re.compile(r"[\(\[]?\s*insert\s+([a-j])\s*[\)\]]?\s*$", re.IGNORECASE)
_BRACKET_INSERT = re.compile(r"[\(\[]\s*([a-j])\s*[\)\]]\s*$", re.IGNORECASE)
_BARE_INSERT = re.compile(r"\s+([a-j])\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class WindowInfo:
    """AX から採れたプラグインウィンドウ 1 枚分の情報。

    どれも欠けうる。`track_name` と `plugin_name` が採れていれば確実で、
    タイトルしか無ければ解釈に頼ることになる。
    """

    title: str = ""
    track_name: str | None = None  # Track Selector の値
    plugin_name: str | None = None  # Plugin Selector の値


@dataclass(frozen=True)
class PluginTarget:
    """前面のプラグインウィンドウが指している対象。"""

    plugin: PluginKind
    track_name: str
    insert_slot: str | None = None
    raw_title: str = ""
    ambiguous: bool = False

    def describe_ja(self) -> str:
        """読み上げ用。**曖昧なときは黙って進めず、その旨を言う。**"""
        head = tr(
            f"トラック「{self.track_name}」の{self.plugin.label_ja}",
            f"{self.plugin.label_ja} on track “{self.track_name}”",
        )
        if self.insert_slot:
            head += tr(
                f"、インサート{self.insert_slot.upper()}",
                f", insert {self.insert_slot.upper()}",
            )
        if self.ambiguous:
            head += tr(
                "。トラック名の区切りが曖昧なので確かめてください",
                ". The track name separator is ambiguous, so please check it",
            )
        return head


def _detect_one(text: str) -> PluginKind | None:
    """1 つの文字列からプラグイン種別を判定する。

    複数該当したときは**より後ろに現れた方**を採る。
    「Kontakt を挿したトラック」のような名前より、末尾のプラグイン名が本命。
    """
    lowered = text.casefold()
    matches: list[tuple[int, PluginKind]] = []
    for plugin in PluginKind:
        position = lowered.rfind(plugin.display_name.casefold())
        if position >= 0:
            matches.append((position, plugin))
    if not matches:
        return None
    # enum 同士は比較できないので、位置だけをキーにする
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def detect_plugin(*texts: str | None) -> PluginKind | None:
    """渡された順に見て、最初に判定できたプラグイン種別を返す。

    呼び出し側は確実な情報から順に渡す（Plugin Selector → タイトル）。
    """
    for text in texts:
        if not text:
            continue
        found = _detect_one(text)
        if found is not None:
            return found
    return None


def split_insert_marker(text: str) -> tuple[str, str | None, bool]:
    """末尾のインサート表記を切り離す。

    戻り値は (本体, スロット記号, 曖昧か)。

    **「Kick a」のようなトラック名は、末尾の "a" をインサート表記と
    取り違えうる。** 明示的な書式（`Insert a` / `(a)`）なら確実だが、
    単独の 1 文字は判断がつかないので `曖昧` を立てて呼び出し側に伝える。
    黙って切り落とすとトラック名が変わってしまう。
    """
    stripped = text.strip()
    for pattern, ambiguous in (
        (_EXPLICIT_INSERT, False),
        (_BRACKET_INSERT, False),
        (_BARE_INSERT, True),
    ):
        matched = pattern.search(stripped)
        if matched is None:
            continue
        head = stripped[: matched.start()].strip()
        if not head:
            # 全体がインサート表記だった。トラック名を失うので分離しない
            continue
        return head, matched.group(1).lower(), ambiguous
    return stripped, None, False


def parse_window_title(title: str) -> tuple[PluginKind | None, str | None]:
    """タイトルからプラグイン種別とトラック名を取り出す。

    戻り値は (プラグイン種別, トラック名)。どちらも取れないことがある。

    `Plug-in: <名前>` 形式のときは**トラック名を含まない**ので、
    種別だけを返して None を添える。Track Selector を見るしかない。
    """
    if not title or not title.strip():
        return None, None

    plugin = _detect_one(title)

    if _PLUGIN_PREFIX.match(title):
        return plugin, None

    if plugin is None:
        return None, None

    lowered = title.casefold()
    position = lowered.rfind(plugin.display_name.casefold())
    head = title[:position].rstrip()

    for separator in _SEPARATORS:
        marker = separator.rstrip()
        if marker and head.endswith(marker):
            head = head[: len(head) - len(marker)]
            break

    track = head.strip(" -–—:/|[]()").strip()
    return plugin, (track or None)


def build_target(window: WindowInfo) -> PluginTarget | None:
    """`WindowInfo` から対象を組み立てる。解釈できなければ None。

    トラック名は **Track Selector の値をそのまま使う**。Pro Tools が返す
    正式な名前なので加工しない（`'Inst1'` のように表示名と詰め方が
    違うことがあるが、台帳の中で一貫していれば実害はない）。
    """
    plugin = detect_plugin(window.plugin_name, window.title)
    title_plugin, title_track = parse_window_title(window.title)
    if plugin is None:
        plugin = title_plugin
    if plugin is None:
        return None

    if window.track_name and window.track_name.strip():
        return PluginTarget(
            plugin=plugin,
            track_name=window.track_name.strip(),
            raw_title=window.title,
        )

    if not title_track:
        return None

    track, insert, ambiguous = split_insert_marker(title_track)
    return PluginTarget(
        plugin=plugin,
        track_name=track,
        insert_slot=insert,
        raw_title=window.title,
        ambiguous=ambiguous,
    )


def choose_front_target(windows: Sequence[WindowInfo]) -> PluginTarget | None:
    """前面から順に見て、最初に解釈できたものを対象とする。

    integration 層は「前面から並べたウィンドウ一覧」を渡す。
    どれも解釈できなければ None を返し、呼び出し側は
    「割り当て対象のプラグインではありません」と読み上げて安全に止まる。
    """
    for window in windows:
        target = build_target(window)
        if target is not None:
            return target
    return None
