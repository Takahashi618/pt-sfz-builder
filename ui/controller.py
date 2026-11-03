"""UI と中身の橋渡し。**wx に依存しない。**

画面の部品を組み立てるのは `main_frame.py` の仕事で、ここは
「押されたら何をするか」だけを持つ。分けてあるのは、**判断の部分を
画面なしでテストできるようにするため**（`tests/test_controller.py`）。

判断そのものも持たない。何をどう割り当てるかは `core/assign.py` が決める。
ここがするのは、UI の入力を `AssignRequest` に直し、結果を読み上げ用の
文言にして返すことだけ。

依存は差し替えられるようにしてある。

| 依存 | 既定 | テストでは |
| --- | --- | --- |
| Splice ライブラリ | 借りている部品の `ptcore/library.py` | スタブ |
| 前面プラグインの特定 | `integration/axread.py` | スタブ |
| 読み込ませる操作 | `integration/sforzando_load.py`（別のプロセス） | スタブ |

**素材が 1 件も無い、前面がプラグインでない、といった状態でも落ちない。**
理由を日本語で返して、利用者が次に何をすればよいか分かるようにする。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, Sequence

from core.assign import AssignRequest, SampleRef
from core.atomicio import write_atomic
from core.mapping import MODE_CHROMATIC, MODE_DRUMKIT, MODE_PHRASE
from core.kinds import (
    DEFAULT_ONESHOT_MAX_SEC,
    KIND_LABELS,
    PACK_ORDER_ADDED,
    PACK_ORDER_COUNT,
    PACK_ORDER_MTIME,
    PACK_ORDER_NAME,
    PACK_ORDER_OPTIONS,
    next_pack_order,
    pack_stats,
    resolve_kind,
    sort_packs,
)
from core.i18n import COMMA, ENV_NAME, LANG, is_english, plural, sentences, tr
from core.notes import parse_note_name
from core.phrase import PHRASE_SPAN_DEFAULT, PHRASE_SPAN_MAX
from core.places import resolve_splice_root, splice_index_path
from core.tempo import BPM_MAX, BPM_MIN
from core.rootkey import DEFAULT_OCTAVE
from core.sibling import FROZEN, PROJECT_ROOT, load_ptcore, part_message
from core.slots import PluginKind, SlotLayout, sanitize_session
from core.target import PluginTarget
from core.tone import DEFAULT_PRESET, get_preset
from integration.axread import make_reader, read_plugin_windows
from integration.service import AssignService, load_ledger
from integration.render import backend_name, clean_rendered, find_unused
from integration.sforzando_log import read_states
from ui.borrowed import make_player

__all__ = [
    "MODE_AUTO",
    "MODE_LABELS",
    "MODE_ORDER",
    "KIND_FILTER_LABELS",
    "AUTO",
    "SearchForm",
    "AssignForm",
    "Outcome",
    "AppController",
]

# **素材に合わせて自動で決める。** 画面だけの値で、`core` には渡さない。
#
# 以前は「一覧で選び直したらループのときだけ配置を寄せる」という作りで、
# 穴が 3 つあった（2026-09-05 のレビュー）。
#
#   * 片道だった。一度ループで寄せたあとワンショットを選んでも戻らず、
#     1 発ものが 25 個も引き伸ばされた
#   * `SetSelection(0)` は `EVT_LISTBOX` を出さないので、**検索直後の
#     先頭の項目には効かなかった**（いちばん押される経路）
#   * Cmd+S でテンポを入れて決定しただけで「自分で選んだ」とみなされ、
#     以後まったく働かなかった
#
# 選び直しの副作用ではなく、**割り当てるその場で決める**ようにした。
MODE_AUTO = "auto"

# 読み上げに出す言葉。**内部の名前（auto など）をそのまま読ませない。**
MODE_LABELS: dict[str, str] = {
    MODE_AUTO: tr("素材に合わせる", "Match the sample"),
    MODE_CHROMATIC: tr("鍵盤全体に広げる", "Spread across the keyboard"),
    MODE_PHRASE: tr("鍵盤全体に広げる。速さを保つ", "Spread across the keyboard, keeping speed"),
    MODE_DRUMKIT: tr("1鍵盤に1サンプル", "One sample per key"),
}

# 画面に並べる順。**主用途から先に置く。**
MODE_ORDER: tuple[str, ...] = (
    MODE_AUTO,
    MODE_CHROMATIC,
    MODE_PHRASE,
    MODE_DRUMKIT,
)

# 検索条件としての種別。**空は「指定しない」。**
# 個々の素材の言い方は `core/kinds.py` の `KIND_LABELS` を使う
# （作者の別のアプリと同じ言葉にするため）。
#
# **`KIND_LABELS` を先に置く。** あちらにも空文字の項目（「不明」）が
# あるので、あとに置くと上書きされ、種別の選択肢の先頭が
# 「不明」と読み上げられていた（2026-09-05 のレビューで判明）。
#
# 英語の画面では、借りられている kinds.py の日本語を使わず、ここの言葉にする
# （kinds.py は別のアプリも読むので、言語の設定を読まない）。
_KIND_LABELS: dict[str, str] = tr(
    KIND_LABELS, {"one_shot": "One-shot", "loop": "Loop", "fx": "FX", "": "Unknown"}
)
_PACK_ORDER_LABELS: dict[str, str] = tr(
    dict(PACK_ORDER_OPTIONS),
    {
        PACK_ORDER_COUNT: "most samples first",
        PACK_ORDER_NAME: "by name",
        PACK_ORDER_MTIME: "recently updated first",
        PACK_ORDER_ADDED: "order added, oldest first",
    },
)
KIND_FILTER_LABELS: dict[str, str] = {**_KIND_LABELS, "": tr("すべての種別", "All types")}

AUTO = tr("自動", "Auto")

# 割り当てられるプラグイン。**読み込ませる操作（座標）は sforzando の分しか無い。**
# Decent Sampler の窓を前に出したまま割り当てると、以前は台帳に枠が無いために
# 「空きスロットがありません」と、本当の理由と違うことを言っていた。
SUPPORTED_PLUGINS = (PluginKind.SFORZANDO,)

# 読み込ませる操作を待つ上限（秒）。実測で 11 秒ほどかかるので、
# **余裕を見て 40 秒。** 切らないと、AppleScript が止まったときに
# 待つしかない状態になる。
PLUGIN_LOAD_TIMEOUT_SEC = 40.0


@dataclass
class SearchForm:
    """検索の条件。空文字は「指定しない」。"""

    text: str = ""
    key: str = ""
    relative: bool = False
    bpm: str = ""
    tolerance: int = 4
    kind: str = ""
    pack: str = ""

    def describe_ja(self) -> str:
        """何で絞ったかを読み上げる。**指定していない条件は言わない。**"""
        parts: list[str] = []
        if self.text:
            parts.append(tr(f"語「{self.text}」", f"word “{self.text}”"))
        if self.key:
            parts.append(tr(f"キー{self.key}", f"key {self.key}") + (tr(
                "、平行調も含む",
                ", including the relative key",
            ) if self.relative else ""))
        if self.bpm:
            parts.append(tr(
                f"{self.bpm} BPM、前後{self.tolerance}",
                f"{self.bpm} BPM, plus or minus {self.tolerance}",
            ))
        if self.kind:
            parts.append(KIND_FILTER_LABELS.get(self.kind, self.kind))
        if self.pack:
            parts.append(tr(f"パック「{self.pack}」", f"pack “{self.pack}”"))
        return COMMA.join(parts) if parts else tr("条件なし", "no filters")


@dataclass
class AssignForm:
    """割り当ての設定。"""

    # **既定は「素材に合わせる」。** ループをふつうのクロマティックで
    # 広げると鍵盤ごとに速さが変わり、セッションのテンポを指定しても
    # 合うのはルートキーだけになる（2026-09-04 に利用者が実際に踏んだ）。
    mode: str = MODE_AUTO
    root_key: str = AUTO
    octave: int = DEFAULT_OCTAVE
    tone_preset: str = DEFAULT_PRESET
    slot_number: int | None = None  # None なら自動
    # 速さを保つ配置で、ルートから上下に何半音まで用意するか。
    # 大きくすると待ち時間が延び、音も荒れる。
    phrase_span: int = PHRASE_SPAN_DEFAULT
    # セッションのテンポ。空文字なら素材のまま。**画面から来た文字列のまま持つ**
    # （数字かどうかの判断は 1 か所にまとめる）。
    target_bpm: str = ""
    # 倍・半分のテンポの解釈を許すか（`core/tempo.py`）。
    # **素材の BPM 表記が実感と半分ずれていることがある**ので既定は許す。
    # 意図と逆向きに動いたときのために切れるようにしてある。
    allow_half_double: bool = True

    def bpm_value(self) -> tuple[int | None, str]:
        """テンポを数値にする。戻り値は (値, 駄目な理由)。

        **空欄は「指定しない」であって間違いではない。**
        """
        text = self.target_bpm.strip()
        if not text:
            return None, ""
        try:
            value = int(text)
        except ValueError:
            return None, tr(
                f"セッションのテンポは数字で入れてください: {text}",
                f"Enter the session tempo as a number: {text}",
            )
        if not BPM_MIN <= value <= BPM_MAX:
            return None, (
                tr(
                    f"セッションのテンポが範囲外です: {value}。"
                    f"{BPM_MIN} から {BPM_MAX} で指定してください。",
                    f"The session tempo is out of range: {value}. Use {BPM_MIN} to {BPM_MAX}.",
                )
            )
        return value, ""


@dataclass
class Outcome:
    """UI へ返す結果。**成否と読み上げ文言だけ。**

    以前は `detail` に道具の出力などを入れていたが、**どこからも
    読んでいなかった。** 診断に要る文字列は標準エラーへ出す
    （`.app` のランチャが `~/Library/Logs/SfzBuilder.log` へ落とす）。
    """

    ok: bool
    message_ja: str

    def __bool__(self) -> bool:
        return self.ok


class TargetReader(Protocol):
    def __call__(self) -> tuple[PluginTarget | None, str, str]: ...


class PluginLoader(Protocol):
    def __call__(self, sfz_path: str, track_name: str) -> Outcome: ...


def _default_target_reader() -> tuple[PluginTarget | None, str, str]:
    """前面のプラグインウィンドウを読む。(対象, 読み上げ文言, セッション名)。

    **セッション名も一緒に返す。** AppleScript の往復を 2 回にしないため。
    """
    result = read_plugin_windows(make_reader())
    return (
        (result.front_target() if result.ok else None),
        result.describe_ja(),
        result.session_name,
    )


def loader_base_command() -> list[str]:
    """読み込ませる道具を別のプロセスで起こすコマンドの頭。

    **どちらの版も `app.py` の `--sforzando-load` を通す**（中身は
    `integration/sforzando_load.py`）。配布版の `sys.executable` は python ではなく
    .app の実行ファイルなので、`.py` の道具をそのまま渡しても動かない。
    手元の版も同じ入口にして、配布版でだけ壊れる道を作らない。
    """
    if FROZEN:
        return [sys.executable, "--sforzando-load"]
    return [sys.executable, str(PROJECT_ROOT / "app.py"), "--sforzando-load"]


def loader_command(sfz_path: str, track_name: str) -> list[str]:
    """`.sfz` を読み込ませるコマンド。

    **割り当てたトラックの名前を渡す。** 道具はそのトラックの sforzando の画面を
    探して前に出し、ほかの画面が前にあっても、そちらを押さない。
    """
    args = ["import", sfz_path]
    if track_name:
        args += ["--track", track_name]
    return loader_base_command() + args


def tool_message(output: str) -> str:
    """道具の出力の最後の `MESSAGE` 行（読み上げる一文）。無ければ空文字。

    **何が起きたかは道具がいちばんよく知っている**（違うトラックの画面だった、
    許可が無い、sforzando の版が違う）。ここで一律の文言に置き換えると、
    利用者は次に何をすればよいか分からない。
    """
    for line in reversed((output or "").splitlines()):
        if line.startswith("MESSAGE\t"):
            return line.split("\t", 1)[1].strip()
    return ""


def _default_plugin_loader(sfz_path: str, track_name: str) -> Outcome:
    """sforzando に `.sfz` を読ませる（`app.py --sforzando-load import`）。

    **座標クリックが絡むので、ここは別プロセスに任せる。**
    UI の中で直接動かすと、失敗したときに画面ごと巻き込む。
    """
    command = loader_command(sfz_path, track_name)
    try:
        # **必ず時間で切る。** AppleScript がモーダルなどで止まると
        # 戻ってこない。切らないと、待つしかない状態になる。
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PLUGIN_LOAD_TIMEOUT_SEC,
            # **画面と同じ言語で答えさせる。** 道具の読み上げる文をそのまま使うので、
            # 道具が自分で言語を決めると、英語の画面で日本語を読むことがある
            env=dict(os.environ, **{ENV_NAME: LANG}),
        )
    except subprocess.TimeoutExpired:
        return Outcome(
            False,
            tr(
                f"{PLUGIN_LOAD_TIMEOUT_SEC:.0f}秒待っても終わりませんでした。"
                "プラグインの画面が前に出ているか確かめて、もう一度試してください。",
                f"Not finished after {PLUGIN_LOAD_TIMEOUT_SEC:.0f} seconds. Check that the plugin "
                "window is in front and try again.",
            ),
        )
    except OSError as exc:
        print(tr(
            f"読み込ませる道具を起動できません: {exc}",
            f"Cannot start the loading tool: {exc}",
        ), file=sys.stderr)
        return Outcome(False, tr(
            f"読み込ませる道具を起動できませんでした。{exc}",
            f"Could not start the loading tool. {exc}",
        ))
    said = tool_message(done.stdout or "")
    if done.returncode != 0:
        # **診断は標準エラーへ。** 読み上げに混ぜると長すぎて聞けない。
        print(
            (done.stdout or "") + (done.stderr or ""), file=sys.stderr
        )
        return Outcome(
            False,
            said
            or tr(
                "プラグインに読み込ませられませんでした。"
                "プラグインの画面が開いているか確かめてください。",
                "Could not load into the plugin. Check that the plugin window is open.",
            ),
        )
    return Outcome(True, said or tr("プラグインに読み込ませました。", "Loaded into the plugin."))


def summary_en(entry: Any) -> str:
    """一覧の 1 行の英語（索引の `summary()` は日本語なので組み立て直す。並びは同じ）。"""
    parts = [getattr(entry, "description", "") or getattr(entry, "filename", "") or str(entry)]
    if getattr(entry, "bpm", None):
        parts.append(f"{entry.bpm} BPM")
    if getattr(entry, "key", None):
        quality = getattr(entry, "key_quality", "") or ""
        parts.append(f"{entry.key} {quality}" if quality in ("minor", "major") else entry.key)
    parts.append(_KIND_LABELS.get(getattr(entry, "kind", "") or "", _KIND_LABELS[""]))
    duration = getattr(entry, "duration", None)
    if isinstance(duration, (int, float)):
        parts.append(f"{duration:.1f} seconds")
    return ", ".join(parts)


def _fold(text: str) -> str:
    """比べるための形にそろえる。**全角と半角、濁点の分かれ方、大文字小文字。**

    日本語入力のまま打った全角の「ｋｉｃｋ」も、Finder が作った NFD の
    日本語のファイル名も見つかるようにする（作者の別のアプリと同じ考え方）。
    借り先のライブラリは小文字にそろえるだけなので、語の照合はこちらで行う。
    """
    return unicodedata.normalize("NFKC", text or "").casefold()


def _text_hits(entry: Any, words: Sequence[str]) -> bool:
    """語が全部、ファイル名・パック名・説明のどこかに含まれるか（かつ）。

    照合する範囲は借り先（`ptcore` の `Library.search`）と同じ。
    """
    haystack = _fold(
        " ".join(
            str(getattr(entry, name, "") or "")
            for name in ("filename", "pack", "description")
        )
        or str(getattr(entry, "path", ""))
    )
    return all(word in haystack for word in words)


def _same_path(path: str) -> str:
    """パスを比べられる形にする。**濁点の分かれ方（NFC と NFD）もそろえる。**

    macOS の「開く」ダイアログなど Cocoa を通ったパスは、日本語が NFD に
    なることがある。sforzando のログに残るのは
    そのパスなので、こちらが書いた NFC のパスとは文字列として一致しない。
    """
    return unicodedata.normalize("NFC", str(Path(path)))


class AppController:
    """画面から呼ばれる操作をまとめたもの。"""

    def __init__(
        self,
        *,
        layout: SlotLayout | None = None,
        library: Any | None = None,
        target_reader: TargetReader | None = None,
        plugin_loader: PluginLoader | None = None,
        service: AssignService | None = None,
        player: Any | None = None,
    ) -> None:
        self.layout = layout or SlotLayout()
        self._library = library
        self._library_tried = library is not None
        self._read_target = target_reader or _default_target_reader
        self._load_plugin = plugin_loader or _default_plugin_loader

        # **台帳とスロットはセッションごと。** 差し替えられた `service` を
        # 渡されたときは触らない（テストが自分で組み立てている）。
        self._owns_service = service is None
        self.ledger_path = Path(self.layout.ledger_path)
        if service is not None:
            self._service = service
        else:
            self._service = self._make_service()

        # 試聴。**借りられなければ None。** 音が出せなくても割り当てはできる。
        # **最初に使うときまで作らない。** 起動時に作ると実測 104 ミリ秒
        # 余分にかかり、そのぶん最初の読み上げが遅れる。
        self._player = player
        self._player_tried = player is not None
        # **設定は 2 つに分かれる。**
        #   根       … アプリ全体の好み（パックの並び順）
        #   セッション … その曲のもの（セッションのテンポ）
        # セッション名が読めないうちは両方が同じファイルを指す。
        self.settings_path = Path(self.layout.slots_dir) / "session.json"
        self.session_path = Path(self.layout.session_dir) / "session.json"
        # パックの並び順。**既定は中身の多い順。**
        # 実測（作者の別のアプリ）で 553 パック中 389 個が 1 件だけだった。
        # 名前順だと目当ての大きなパックが埋もれる。
        # パックの並び順は**アプリ全体の好み**。曲によらない。
        settings = self._read_json(self.settings_path)
        self.pack_order = settings.get("pack_order", PACK_ORDER_COUNT)
        # Splice のフォルダ。**空なら決まった場所を探す**（`core/places.py`）。
        # Splice のアプリの設定で動かせるので、操作メニューから選び直せる。
        self._splice_choice = str(settings.get("splice_root", "") or "")
        # 索引が使えない理由（検索で伝える）。"" / "no_parts" / "no_index"
        self._library_problem = ""
        self.results: list[Any] = []
        self.target: PluginTarget | None = None
        self.last_written: str | None = None
        # 書いたスロットのトラック。**読み込ませるとき、そのトラックの画面だけを押す。**
        self.last_track = ""
        # 直前に「使っていない」と読み上げた下ごしらえ。**消すのはこれだけ。**
        self.unused_paths: list[str] = []

    # -- セッション -------------------------------------------------------

    def _make_service(self) -> AssignService:
        """いまのセッションの台帳でサービスを組み立てる。"""
        ledger = load_ledger(
            self.ledger_path,
            layout=self.layout,
            plugins=[PluginKind.SFORZANDO],
        )
        return AssignService(ledger, ledger_path=self.ledger_path)

    @property
    def session(self) -> str:
        """いま開いている Pro Tools セッションの名前。分からなければ空文字。"""
        return self.layout.session

    def use_session(self, name: str) -> bool:
        """セッションが変わったら台帳を差し替える。変わったら True。

        **セッションごとにスロットを分けるのが要**（`core/slots.py`）。
        分けないと、別のセッションで割り当てたときに前のセッションの
        音を上書きする。

        **名前が読めなかったときは切り替えない。** 空文字で切り替えると
        全セッション共有の置き場所へ落ちてしまい、上書きが復活する。
        """
        wanted = sanitize_session(name)
        if not wanted or wanted == sanitize_session(self.layout.session):
            return False
        if not self._owns_service:
            # 差し替えられたサービスは尊重する（テスト）
            return False
        self.layout = replace(self.layout, session=wanted)
        self.ledger_path = Path(self.layout.ledger_path)
        self.session_path = Path(self.layout.session_dir) / "session.json"
        self._service = self._make_service()
        # 覚えている書き込み先も、別のセッションのものは持ち越さない
        self.last_written = None
        self.last_track = ""
        return True

    # -- セッションの条件 -------------------------------------------------

    def _read_json(self, path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_json(self, path: Path, **changes) -> None:
        """設定を覚える。**書けなくても黙って進む。**

        覚えられないのは不便なだけで、割り当て自体には影響しない。
        **既にある項目は消さない**（片方だけ保存して他方を失わないため）。

        **差し替え方式で書く**（`core/atomicio.py`）。じかに書くと、
        途中で落ちたときに壊れた JSON が残り、次の起動で
        テンポもパックの並び順も黙って既定へ戻る。
        """
        data = self._read_json(path)
        data.update(changes)
        try:
            write_atomic(path, json.dumps(data, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def load_session_bpm(self) -> str:
        """このセッションのテンポを読む。無ければ空文字。

        **曲ごとに覚える。** テンポは曲の性質なので、セッションを開き直したら
        そのときの値が戻るのが正しい。毎回入れ直させない。

        このセッションの分がまだ無ければ、根に置いてある古い設定を見る
        （セッションごとに分ける前の値。1 回だけ引き継ぐ）。
        """
        value = self._read_json(self.session_path).get("target_bpm")
        if not value and self.session_path != self.settings_path:
            value = self._read_json(self.settings_path).get("target_bpm")
        return str(value) if value else ""

    def save_session_bpm(self, text: str) -> None:
        self._write_json(self.session_path, target_bpm=text.strip())

    def cycle_pack_order(self) -> Outcome:
        """パックの並び順を順送りする（作者の別のアプリの Cmd+Shift+G と同じ）。

        中身の多い順 → 名前順 → 更新の新しい順 → 追加した順 → 中身の多い順
        （`core/kinds.PACK_ORDER_OPTIONS` の並び）。
        """
        self.pack_order = next_pack_order(self.pack_order)
        self._write_json(self.settings_path, pack_order=self.pack_order)
        label = _PACK_ORDER_LABELS.get(self.pack_order, self.pack_order)
        return Outcome(True, tr(f"パックの並び順を{label}にしました。", f"Pack order: {label}."))

    # -- ライブラリ -------------------------------------------------------

    @property
    def library(self) -> Any | None:
        """Splice ライブラリ。**一度だけ読み込む。**

        見つからなくても None を返すだけで落ちない。
        検索は使えなくなるが、ファイルを直接指定する経路は残る。
        使えない理由は `_library_problem` に控える（検索で伝える）。
        """
        if not self._library_tried:
            self._library_tried = True
            lib = self._open_library()
            # **索引が読めなければ検索には使わない。** ただし実体は
            # `rescan_library` が作り直せるように別途開き直す。
            if lib is None:
                self._library_problem = "no_parts"
                self._library = None
            elif lib.load(quiet=True):
                self._library_problem = ""
                self._library = lib
            else:
                self._library_problem = "no_index"
                self._library = None
        return self._library

    @property
    def splice_root(self) -> Path:
        """Splice のパックが並ぶフォルダ（設定の値。空なら決まった場所を探す）。"""
        return resolve_splice_root(self._splice_choice)

    def _open_library(self) -> Any | None:
        """Splice ライブラリを開く。**索引は読まない。** 無ければ None。

        索引の置き場所は `core/places.splice_index_path`（配布版は .app の外）。
        """
        module = load_ptcore("library")
        if module is None:
            return None
        return module.Library(
            str(self.splice_root),
            index_path=splice_index_path(self.layout.slots_dir),
        )

    def set_splice_root(self, chosen: str) -> Outcome:
        """Splice のフォルダを選び直す（操作メニューの「Splice のフォルダを選ぶ」）。

        **索引は呼び出し側が作り直す。** 前のフォルダの索引は使わない。
        `~/Splice` そのものを選んでも、中の `sounds/packs` を使う。
        """
        root = resolve_splice_root(chosen)
        if not root.is_dir():
            return Outcome(False, tr(
                f"フォルダが見つかりません: {root}",
                f"Folder not found: {root}",
            ))
        self._splice_choice = str(root)
        self._write_json(self.settings_path, splice_root=str(root))
        self._library, self._library_tried = None, False
        self.results = []
        return Outcome(True, tr(
            f"Splice のフォルダを {root} にしました。",
            f"The Splice folder is now {root}.",
        ))

    def rescan_library(self) -> Outcome:
        """Splice ライブラリの索引を作り直す。

        **素材を買い足しても索引が古いままだと見つからない。**
        走査は 3000 件ほどで 1 秒程度なので、待たせても差し支えない
        （初めて作るときは、全部の素材の頭を読むので数秒かかる）。

        索引が読めていない状態からでも作れるよう、**ここでは
        `self.library` を通さず新しく開く。**
        """
        root = self.splice_root
        if not root.is_dir():
            # 無いフォルダを数えると「0 件」と言うだけで、何が悪いのか分からない
            return Outcome(
                False,
                tr(
                    f"Splice のフォルダが見つかりません（{root}）。"
                    "操作メニューの「Splice のフォルダを選ぶ」で、"
                    "素材の入っているフォルダを選んでください。",
                    f"The Splice folder was not found ({root}). Use Choose Splice Folder in the "
                    "Actions menu to choose the folder that holds your samples.",
                ),
            )
        lib = self._library
        if lib is None:
            lib = self._open_library()
        if lib is None:
            return Outcome(
                False, tr(
                    "Splice の索引を作る部品が見つかりません。",
                    "The part that builds the Splice index was not found.",
                )
            )
        try:
            # **保存は scan が行う。** ここで続けて save すると、同じ索引を
            # 二度書いていた（借り先と共有している索引）。
            stats = lib.scan()
        except Exception as exc:
            return Outcome(False, tr(
                f"索引を更新できませんでした: {exc}",
                f"Could not update the index: {part_message(str(exc))}",
            ))

        self._library = lib
        self._library_tried = True
        self._library_problem = ""
        total = stats.get("total", 0)
        parsed = stats.get("parsed", 0)
        unreadable = stats.get("unreadable", 0)
        message = tr(
            f"索引を更新しました。{total} 件。"
            f"うち {parsed} 件を読み直しました。",
            f"Index updated. {plural(total, 'sample')}, {parsed} read again.",
        )
        if unreadable:
            message += tr(
                f"{unreadable} 件は読めませんでした。",
                f" {unreadable} could not be read.",
            )
        return Outcome(True, message)

    def packs(self) -> list[str]:
        """絞り込み候補にするパック名。**並び順は `pack_order` に従う。**

        借りている部品の `packs()` は名前順で固定なので、こちらで数え直す。
        """
        lib = self.library
        if lib is None:
            return []
        try:
            return sort_packs(pack_stats(lib.entries), self.pack_order)
        except Exception:
            return []

    def keys(self) -> list[str]:
        lib = self.library
        if lib is None:
            return []
        try:
            return list(lib.keys())
        except Exception:
            return []

    def search(self, form: SearchForm) -> Outcome:
        """条件で絞り込む。結果は `self.results` に入る。"""
        lib = self.library
        if lib is None:
            self.results = []
            if self._library_problem == "no_parts":
                return Outcome(
                    False,
                    tr(
                        "Splice の索引を読む部品が見つかりません。"
                        "ファイルを選んで割り当ててください。",
                        "The part that reads the Splice index was not found. Please choose a file "
                        "to assign.",
                    ),
                )
            # **初めて使うときは、まだ索引が無い。** 「読めません」とだけ言うと
            # 壊れたように聞こえ、作れば済むことが伝わらない。
            return Outcome(
                False,
                tr(
                    "Splice の索引がまだ無いか、読めません。"
                    "操作メニューの「Splice の索引を更新」（コマンド+R）で作ってください。"
                    "ファイルを選んで割り当てることもできます。",
                    "The Splice index does not exist yet or cannot be read. Create it with Update "
                    "Splice Index in the Actions menu (Command-R). You can also choose a file to "
                    "assign.",
                ),
            )

        bpm: int | None = None
        if form.bpm.strip():
            try:
                bpm = int(form.bpm.strip())
            except ValueError:
                return Outcome(False, tr(
                    f"BPM は数字で入れてください: {form.bpm}",
                    f"Enter the BPM as a number: {form.bpm}",
                ))

        try:
            found = list(
                lib.search(
                    # **語はライブラリに任せない**（下の `_text_hits`）。
                    text=None,
                    bpm=bpm,
                    tolerance=form.tolerance,
                    key=form.key or None,
                    relative=form.relative,
                    # **種別はライブラリに任せない。** あちらはファイル名だけで
                    # 判定するので当てにならない。長さを見て自分で絞る。
                    kind=None,
                    pack=form.pack or None,
                )
            )
        except Exception as exc:  # ライブラリ側の想定外
            self.results = []
            return Outcome(False, tr(
                f"検索に失敗しました: {exc}",
                f"The search failed: {part_message(str(exc))}",
            ))

        if form.text:
            words = _fold(form.text).split()
            found = [e for e in found if _text_hits(e, words)]
        if form.pack:
            # **パックは名前が同じものだけ。** ライブラリは部分一致で絞るので、
            # 「Trap」を選ぶと「Trap Vol. 2」まで混ざっていた。選択肢は
            # 実在のパック名なので、同じ名前のものだけを残してよい。
            found = [e for e in found if getattr(e, "pack", "") == form.pack]
        if form.kind:
            found = [e for e in found if self.kind_of(e) == form.kind]
        self.results = found

        count = len(self.results)
        if count == 0:
            return Outcome(
                False, tr(
                    f"{form.describe_ja()} に合う素材はありませんでした。",
                    f"No samples found. Search: {form.describe_ja()}.",
                )
            )
        return Outcome(True, tr(
            f"{count} 件見つかりました。{form.describe_ja()}。",
            f"{plural(count, 'sample')} found. Search: {form.describe_ja()}.",
        ))

    def kind_of(self, entry: Any) -> str:
        """素材の種別。**長さを優先する**（`core/kinds.py`）。"""
        return resolve_kind(
            getattr(entry, "kind", ""),
            getattr(entry, "duration", None),
            DEFAULT_ONESHOT_MAX_SEC,
        )

    def will_render(self, paths: Sequence[str], form: AssignForm) -> bool:
        """下ごしらえで待たせるか。**待たせる前に伝えるために要る。**

        画面が `form.mode` から推し量っていたときは、「素材に合わせる」で
        ループを選んだ場合に**何も言わないまま数秒止まっていた。**
        """
        mode, _ = self.resolve_mode(paths, form)
        return mode == MODE_PHRASE

    def wait_note_ja(self, paths: Sequence[str], form: AssignForm) -> str:
        """待たせることを伝える文言。待たせないなら空文字。

        **何個作るかまで言う。** 画面を見ない利用者には進み具合の
        手掛かりが無いので、待つ長さの見当が付くだけでずいぶん違う。
        """
        if not self.will_render(paths, form):
            return ""
        span = max(1, min(form.phrase_span, PHRASE_SPAN_MAX))
        return tr(
            f"{span * 2 + 1}鍵盤ぶんの下ごしらえをしています。"
            "少しお待ちください。",
            f"Preparing {span * 2 + 1} keys. Please wait.",
        )

    def kind_for_path(self, path: str) -> str | None:
        """パスから種別を引く。**検索結果に無ければ None。**

        ファイルを直接選んだときは長さが分からないので None を返す。
        `core/assign.py` は None を「分からない」として扱う。
        """
        for entry in self.results:
            if getattr(entry, "path", None) == path:
                return self.kind_of(entry)
        return None

    def result_labels(self) -> list[str]:
        """一覧に並べる文字列。**1 行 1 件で、読み上げて分かる形にする。**

        種別は**長さで判定し直したもの**を出す。ライブラリの `summary()` を
        そのまま使うと、絞り込みの結果と一覧の表示が食い違う
        （「ループで絞ったのにワンショットと読まれる」）。

        **判定し直した種別を持たせてから `summary()` を呼ぶ。**
        出来上がった文字列の中の言葉を差し替えていたときは、
        あちらの `summary()` の区切り方と言葉づかいの両方に依存していて、
        どちらかが変わると**黙って何も置き換わらなかった**
        （差し替え損ねても分からない）。
        """
        labels = []
        for entry in self.results:
            resolved = self.kind_of(entry)
            named = (getattr(entry, "kind", "") or "").strip()
            if named != resolved:
                try:
                    entry = replace(entry, kind=resolved)
                except TypeError:
                    pass  # dataclass でなければそのまま出す
            if is_english():
                labels.append(summary_en(entry))
                continue
            summary = getattr(entry, "summary", None)
            labels.append(summary() if callable(summary) else str(entry))
        return labels

    def result_path(self, index: int) -> str | None:
        if not 0 <= index < len(self.results):
            return None
        return getattr(self.results[index], "path", None)

    def result_kind(self, index: int) -> str:
        """素材の種別（`loop` / `one_shot` / `fx`）。分からなければ空文字。

        **長さで判定し直したもの**を返す。ファイル名だけの判定は当てにならない。
        """
        if not 0 <= index < len(self.results):
            return ""
        return self.kind_of(self.results[index])

    def resolve_mode(
        self, paths: Sequence[str], form: AssignForm
    ) -> tuple[str, str]:
        """実際に使う配置を決める。戻り値は (配置, 読み上げに足す一言)。

        **自分で選んでいれば、そのまま使う。** 「素材に合わせる」の
        ときだけここで決める。

        | 素材 | 配置 | 理由 |
        | --- | --- | --- |
        | 2 個以上 | 1鍵盤に1サンプル | まとめて選ぶのはキットを組むとき |
        | ループ | 速さを保つ | ふつうに広げると鍵盤ごとに速さが変わる |
        | それ以外 | 鍵盤全体に広げる | ワンショットは速さが変わっても困らない |

        **決めたことは必ず言う。** 黙って変えると、思っていたのと違う
        音色ができても気づけない。
        """
        if form.mode != MODE_AUTO:
            return form.mode, ""
        if len(paths) > 1:
            return (
                MODE_DRUMKIT,
                tr(
                    f"{len(paths)}個選ばれているので、"
                    f"配置は「{MODE_LABELS[MODE_DRUMKIT]}」にしました。",
                    f"{plural(len(paths), 'sample')} selected, so the mapping is "
                    f"“{MODE_LABELS[MODE_DRUMKIT]}”.",
                ),
            )
        kind = self.kind_for_path(paths[0]) if paths else None
        if kind == "loop":
            return (
                MODE_PHRASE,
                tr(
                    "ループ素材なので、配置を「速さを保つ」にしました。",
                    f"This is a loop, so the mapping is “{MODE_LABELS[MODE_PHRASE]}”.",
                ),
            )
        return (
            MODE_CHROMATIC,
            tr(
                f"配置は「{MODE_LABELS[MODE_CHROMATIC]}」にしました。",
                f"The mapping is “{MODE_LABELS[MODE_CHROMATIC]}”.",
            ),
        )

    # -- 試聴 -------------------------------------------------------------

    def _get_player(self):
        """試聴プレイヤー。**最初に使うときに作る。**"""
        if not self._player_tried:
            self._player_tried = True
            self._player = make_player()
        return self._player

    @property
    def can_preview(self) -> bool:
        return self._get_player() is not None

    def toggle_preview(self, path: str | None) -> Outcome:
        """スペース 1 つで再生と停止を切り替える。

        **作者の別のアプリと同じ操作**にしてある。アプリを
        使い分けるので、キーが揃っていないと持ち替えるたびに迷う。
        """
        player = self._get_player()
        if player is None:
            return Outcome(False, tr(
                "試聴は使えません。just_playback が要ります。",
                "Preview is not available. It needs just_playback.",
            ))
        if not path:
            return Outcome(False, tr(
                "一覧から素材を選んでください。",
                "Please choose a sample from the list.",
            ))
        try:
            # **`current_path` はプロパティ。** 括弧を付けると
            # None を呼ぶことになる（2026-09-04 に踏んだ）。
            if player.current_path != str(path):
                player.load(path)
                player.play()
            else:
                player.toggle_play_stop()
        except Exception as exc:
            return Outcome(False, tr(f"試聴できませんでした: {exc}", f"Could not preview: {exc}"))
        return Outcome(True, player.describe_state_en() if is_english() else player.describe_state_ja())

    def stop_preview(self) -> None:
        """鳴らしっぱなしにしない。**割り当てのときや終了時に呼ぶ。**

        **まだ作っていなければ作らない。** 止めるだけのために
        プレイヤーを起こす意味は無い。
        """
        if self._player is None:
            return
        try:
            self._player.stop()
        except Exception:
            pass

    # -- 割り当て先 -------------------------------------------------------

    def detect_target(self) -> Outcome:
        """前面のプラグインウィンドウを調べる。

        **セッション名もここで拾う。** AppleScript の往復は 1 回で済み、
        割り当ての直前に必ず通る経路なので、ここが一番確実。
        """
        target, message, session = self._read_target()
        self.target = target
        if self.use_session(session):
            # 文の区切りを入れる（「…のスフォルツァンド セッションは」と続けて読まれていた）
            end = "" if message.endswith(tr("。", ".")) else tr("。", ".")
            message = tr(
                f"{message}{end}セッションは「{self.session}」です。",
                f"{message}{end} The session is “{self.session}”.",
            )
        return Outcome(target is not None, message)

    # -- 割り当て ---------------------------------------------------------

    def assign(self, paths: Sequence[str], form: AssignForm) -> Outcome:
        """選ばれた素材を割り当てる。

        **対象が分からなければ、まず調べる。** 利用者に 2 回押させない。
        """
        if not paths:
            return Outcome(False, tr("素材が選ばれていません。", "No sample is selected."))
        mode, mode_note = self.resolve_mode(paths, form)
        if self.target is None:
            found = self.detect_target()
            if not found.ok:
                return Outcome(False, found.message_ja)
        assert self.target is not None
        if self.target.plugin not in SUPPORTED_PLUGINS:
            return Outcome(
                False,
                tr(
                    f"{self.target.plugin.label_ja}にはまだ割り当てられません。"
                    "スフォルツァンドの画面を前に出してから、もう一度実行してください。",
                    f"{self.target.plugin.label_ja} cannot be assigned yet. Bring the sforzando "
                    "window to the front and try again.",
                ),
            )

        target_bpm, bpm_problem = form.bpm_value()
        if bpm_problem:
            return Outcome(False, bpm_problem)
        # **覚えるのはここ。** 画面側でやると、別の経路から割り当てたときに
        # 保存し忘れる。曲ごとに変わる値なので入れ直させない。
        self.save_session_bpm(form.target_bpm)

        root_key: int | None = None
        if form.root_key != AUTO:
            root_key = _note_number(form.root_key, form.octave)
            if root_key is None:
                return Outcome(False, tr(
                    f"ルートキーが分かりません: {form.root_key}",
                    f"The root key is not recognized: {form.root_key}",
                ))

        request = AssignRequest(
            target=self.target,
            # **種別を一緒に渡す。** ドラムキットでワンショットを
            # 伸縮させないために要る（長さで判定したもの）。
            samples=[SampleRef(p, kind=self.kind_for_path(p)) for p in paths],
            mode=mode,
            tone=get_preset(form.tone_preset),
            root_key=root_key,
            octave=form.octave,
            known_slot_number=form.slot_number,
            phrase_span=max(1, min(form.phrase_span, PHRASE_SPAN_MAX)),
            target_bpm=target_bpm,
            allow_half_double=form.allow_half_double,
        )
        outcome = self._service.assign(request)
        if outcome.written_path:
            self.last_written = outcome.written_path
            self.last_track = self.target.track_name
        message = outcome.describe_ja()
        if mode_note:
            message = f"{mode_note} {message}"
        # **台帳の保存は `AssignService` に任せる。**
        # ここで書き足していたときは、中止した割り当ての台帳まで
        # 保存していた（`.sfz` は書かれていないのに、スロットは
        # 使用中として残る）。保存できなかったときの `[警告]` は
        # サービスが notes に入れてくれる。
        return Outcome(outcome.ok, message)

    # -- プラグインへ読み込ませる ----------------------------------------

    def needs_loading(self) -> bool:
        """初回の読み込みが要るか。

        **プラグインがそのファイルを監視していれば要らない。**
        ログから判断する。分からないときは「要る」に倒す
        （余分に押しても実害が無く、押し忘れると音が出ないため）。
        """
        if not self.last_written:
            return True
        states = read_states()
        if not states:
            return True
        want = _same_path(self.last_written)
        for path, state in states.items():
            if _same_path(path) == want:
                return not state.watching
        return True

    def load_into_plugin(self) -> Outcome:
        """いま書いたスロットをプラグインに読み込ませる（初回だけ）。

        **書いたときのトラックを一緒に渡す。** 道具は、前に出ている sforzando の
        画面が別のトラックのものなら押さない。以前は前にある sforzando を
        そのまま押していたので、割り当てたあとに別のトラックの画面を開くと、
        そちらに読み込ませていた（2 つのトラックが同じ音を鳴らし、台帳とも
        食い違う）。
        """
        if not self.last_written:
            return Outcome(False, tr(
                "先に割り当てを実行してください。",
                "Please run the assignment first.",
            ))
        return self._load_plugin(self.last_written, self.last_track)

    # -- 状態 -------------------------------------------------------------

    def unused_renders_ja(self) -> Outcome:
        """使っていない下ごしらえを数える。**消さない。**

        挙げた一覧は `unused_paths` に控える。**読み上げた分だけを
        消すため。** 消すときに数え直すと、確認の前後で `.sfz` が
        書き換わったときに「言った数と消える数が違う」ことが起きる。
        """
        found = find_unused(self.layout.slots_dir)
        self.unused_paths = list(found.paths) if found.ok else []
        return Outcome(found.ok, found.describe_ja())

    def clean_renders(self) -> Outcome:
        """使っていない下ごしらえを消す。**読み上げた一覧だけを消す。**"""
        done = clean_rendered(
            self.layout.slots_dir, paths=self.unused_paths or None
        )
        self.unused_paths = []
        return Outcome(done.ok, done.describe_ja())

    def stretch_backend_ja(self) -> str:
        """伸縮の道具の状態。**無ければ「速さを保つ」が使えない。**"""
        name = backend_name()
        if not name:
            return tr(
                "伸縮の道具がありません。ffmpeg か rubberband を入れると"
                "「速さを保つ」配置が使えます。",
                "There is no stretching tool. Install ffmpeg or rubberband to use the "
                "keep-speed mapping.",
            )
        return tr(f"伸縮には {name} を使います。", f"Stretching uses {name}.")

    def slot_summary_ja(self) -> str:
        """台帳の要約。**使っているスロットだけ読み上げる。**"""
        # **`assignments` は辞書。** キーは (プラグイン, 番号) の組。
        # そのまま回すとキーの組が返ってきて、属性が無いと言われる。
        used = [
            a
            for a in self._service.ledger.slots_of(PluginKind.SFORZANDO)
            if a.track_name or a.sample_count
        ]
        where = tr(
            f"セッション「{self.session}」",
            f"Session “{self.session}”",
        ) if self.session else tr(
            "セッション名が読めていません",
            "The session name could not be read",
        )
        if not used:
            return tr(
                f"{where}。どのスロットもまだ使っていません。",
                f"{where}. No slots are in use yet.",
            )
        lines = [tr(
            f"{where}。{len(used)} スロットを使っています",
            f"{where}. {plural(len(used), 'slot')} in use",
        )]
        for a in used:
            track = a.track_name or tr("未接続", "not connected")
            lines.append(tr(
                f"スロット{a.number}、{track}、{a.summary_ja or '中身なし'}",
                f"Slot {a.number}, {track}, {a.summary_ja or 'empty'}",
            ))
        return sentences(lines)


def _note_number(name: str, octave: int) -> int | None:
    """音名とオクターブから MIDI ノート番号を出す。範囲外なら None。

    **変換の規則は `core/notes.py` にだけ置く。** ここで 128 個の音名を
    突き合わせて逆算していたときは、同じ対応表が 2 か所にあることになり、
    `parse_note_name` が受け付けるフラット表記（`Bb`）だけこちらが
    弾く、という食い違いが出ていた。
    """
    try:
        return parse_note_name(f"{name}{octave}")
    except ValueError:
        return None
