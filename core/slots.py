"""スロット台帳。どのプラグインインスタンスに何を割り当てたかを記録する。

**プラグイン側から「今どのサンプルが載っているか」を問い合わせる手段が無い。**
そのため、この台帳がただ一つの正になる。Pro Tools 側で手動で別の設定を
選ばれると台帳とずれるので、そのときは選び直してもらう。

台帳は索引であって実体ではない。実体は `.sfz` ファイルそのもので、
詳細が要るときは `sfz.parse()` で読み戻せる（往復できる形で書いている）。
台帳には**読み上げに要る分だけ**を持たせ、軽く保つ。

OS 非依存。macOS の絶対パスを文字列として組み立てるだけなので、
Windows で全経路をテストできる。
"""

from __future__ import annotations

from .i18n import COMMA, plural, tr

import enum
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath

from .mapping import MODE_DRUMKIT, Instrument
from .notes import MIDI_MAX, MIDI_MIN
from .phrase import RENDER_DIR_NAME
from .places import default_slots_dir

__all__ = [
    "SlotError",
    "PluginKind",
    "SlotLayout",
    "SlotAssignment",
    "SlotLedger",
    "sanitize_session",
    "slot_number_from_setting_name",
]

# Pro Tools の Librarian から選ぶことを考えると、現実的な上限はこのあたり。
# パス長の制約ではない（SFZ はテキストなので長さは自由）。
MAX_SLOT_COUNT = 999


class SlotError(RuntimeError):
    """スロットの操作に失敗したことを表す。"""


def _is_absolute(text: str) -> bool:
    """macOS でも Windows でも、絶対パスなら True。

    本番は macOS だが、テストは Windows でも走らせる。両方の書式を
    通しておかないと、実ファイルを使ったテストが Windows で書けなくなる。
    """
    return PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute()


class PluginKind(enum.Enum):
    """割り当て先のプラグイン。

    値は台帳（JSON）に保存するので、安定した文字列にしておく。
    """

    SFORZANDO = "sforzando"
    DECENT_SAMPLER = "decent_sampler"

    @property
    def display_name(self) -> str:
        """Pro Tools のウィンドウ名に現れる表記。"""
        return {
            PluginKind.SFORZANDO: "sforzando",
            PluginKind.DECENT_SAMPLER: "Decent Sampler",
        }[self]

    @property
    def label_ja(self) -> str:
        """読み上げ用のラベル。日本語の画面では、英語のまま読ませると聞き取りにくいのでカタカナにする。"""
        return {
            PluginKind.SFORZANDO: tr("スフォルツァンド", "sforzando"),
            PluginKind.DECENT_SAMPLER: tr("ディセントサンプラー", "Decent Sampler"),
        }[self]

    @property
    def settings_folder(self) -> str:
        """Pro Tools の Plug-In Settings 配下のフォルダ名。

        **実機で確認すること（S4）。** 違っていればここだけ直せばよい。
        """
        return {
            PluginKind.SFORZANDO: "sforzando",
            PluginKind.DECENT_SAMPLER: "Decent Sampler",
        }[self]

    @property
    def file_extension(self) -> str:
        """定義ファイルの拡張子。プラグインごとに違う。"""
        return {
            PluginKind.SFORZANDO: "sfz",
            PluginKind.DECENT_SAMPLER: "dspreset",
        }[self]


def sanitize_session(name: str) -> str:
    """セッション名をフォルダ名に使える形にする。使えなければ空文字。

    **推測で別名を作らない。** 使えない文字が混ざったら、その 1 文字を
    下線に置き換えるだけにする。まるごと諦めると、根に直接置く動作
    （＝全セッションで共有）に落ちてしまう。
    """
    text = (name or "").strip()
    if not text:
        return ""
    out = []
    for ch in text:
        if ch in "/\\:" or ord(ch) < 32:
            out.append("_")
        else:
            out.append(ch)
    cleaned = "".join(out).strip(" .")
    # `.` や `..` はフォルダ名として使えない
    return "" if cleaned in ("", ".", "..") else cleaned


@dataclass(frozen=True)
class SlotLayout:
    """スロットの物理配置。

    `.sfz` の置き場所は `chroma_slots`（旧方式のスロット WAV 用）と分けてある。
    **iCloud 配下は避けること**（同期の影響を受ける。過去に実害があった）。

    ### セッションごとに分ける（2026-09-05）

    `session` を渡すと `.sfz` と台帳を `<slots_dir>/<session>/` へ置く。

        sfz_slots/
          rendered/            下ごしらえ。**共有**（同じ素材・同じ倍率なら 1 つ）
          260904_1/slot01.sfz, ledger.json
          260825_1/slot01.sfz, ledger.json

    **分けないと、別のセッションで割り当てたときに前のセッションの音を
    上書きする。** Pro Tools の既定のトラック名（`Inst1`…）はどのセッションでも
    同じで、台帳はトラック名でスロットを決めるため、同じスロットを掴む。
    sforzando はセッションにパスしか覚えていない（チャンクは音色の中身が
    増えても 1211 バイトのまま）ので、**開き直すと後から書いた音が鳴る**
    （2026-09-05 に実機のログで確認）。

    下ごしらえを共有のままにしてあるのは、**同じ素材を同じ倍率に伸ばした
    ファイルはセッションが違っても同じ**だから。1 回 90 メガバイトになるので
    セッションごとに複製すると容量が持たない。

    `session` が空なら根に直接置く（今までどおり）。セッション名が
    読めなかったときにここへ落ちる。

    `slots_dir` の既定は `core/places.py` が決める（手元の版はプロジェクトの隣の
    `sfz_slots/`、配布版は `~/Music/SFZBuilder/`）。
    """

    slots_dir: str = field(default_factory=default_slots_dir)
    slot_count: int = 16
    setting_prefix: str = "SLOT"
    session: str = ""

    def __post_init__(self) -> None:
        if not _is_absolute(self.slots_dir):
            raise SlotError(tr(
                f"slots_dir は絶対パスにしてください: {self.slots_dir!r}",
                f"slots_dir must be an absolute path: {self.slots_dir!r}",
            ))
        if self.slots_dir.endswith(("/", "\\")):
            raise SlotError(tr(
                "slots_dir の末尾に区切り記号は付けないでください",
                "slots_dir must not end with a separator",
            ))
        if not 1 <= self.slot_count <= MAX_SLOT_COUNT:
            raise SlotError(
                tr(
                    f"slot_count は 1〜{MAX_SLOT_COUNT} の範囲です: {self.slot_count}",
                    f"slot_count must be 1 to {MAX_SLOT_COUNT}: {self.slot_count}",
                )
            )
        if not self.setting_prefix.strip():
            raise SlotError(tr("setting_prefix が空です", "setting_prefix is empty"))

    def filename(self, number: int, plugin: PluginKind) -> str:
        """スロットの定義ファイル名。プラグインで拡張子が変わる。"""
        self._check(number)
        return f"slot{number:02d}.{plugin.file_extension}"

    @property
    def session_dir(self) -> str:
        """このセッションの `.sfz` と台帳を置く場所。"""
        safe = sanitize_session(self.session)
        return f"{self.slots_dir}/{safe}" if safe else self.slots_dir

    @property
    def render_dir(self) -> str:
        """下ごしらえの置き場所。**セッションによらず共有。**

        同じ素材を同じ倍率に伸ばしたファイルはセッションが違っても同じ。
        1 回 90 メガバイトになるので、複製すると容量が持たない。
        """
        return f"{self.slots_dir}/{RENDER_DIR_NAME}"

    @property
    def ledger_path(self) -> str:
        """台帳の場所。**セッションごと。**"""
        return f"{self.session_dir}/ledger.json"

    def path(self, number: int, plugin: PluginKind) -> str:
        """定義ファイルの絶対パス。"""
        return f"{self.session_dir}/{self.filename(number, plugin)}"

    def setting_name(self, number: int) -> str:
        """Pro Tools の Librarian に表示される設定名（拡張子なし）。"""
        self._check(number)
        return f"{self.setting_prefix}_{number:02d}"

    def numbers(self) -> list[int]:
        return list(range(1, self.slot_count + 1))

    def _check(self, number: int) -> None:
        if not 1 <= number <= self.slot_count:
            raise SlotError(
                tr(
                    f"スロット番号が範囲外です: {number}（1〜{self.slot_count}）",
                    f"The slot number is out of range: {number} (1 to {self.slot_count})",
                )
            )


@dataclass
class SlotAssignment:
    """1 スロットの現在の状態。

    `track_name` は Pro Tools のトラック名で、プラグインインスタンスの識別子に使う。
    None なら、まだどのインスタンスにも結び付いていない。
    """

    number: int
    plugin: PluginKind
    track_name: str | None = None
    mode: str | None = None
    summary_ja: str = ""
    sample_count: int = 0
    root_key: int | None = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def is_free(self) -> bool:
        """どのインスタンスにも結び付いていないか。"""
        return self.track_name is None

    @property
    def has_content(self) -> bool:
        """サンプルが載っているか。"""
        return self.sample_count > 0

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "plugin": self.plugin.value,
            "track_name": self.track_name,
            "mode": self.mode,
            "summary_ja": self.summary_ja,
            "sample_count": self.sample_count,
            "root_key": self.root_key,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SlotAssignment":
        return cls(
            number=int(data["number"]),
            plugin=PluginKind(data["plugin"]),
            track_name=data.get("track_name"),
            mode=data.get("mode"),
            summary_ja=data.get("summary_ja", ""),
            sample_count=int(data.get("sample_count", 0)),
            root_key=data.get("root_key"),
            updated_at=data.get("updated_at", ""),
        )

    def describe_ja(self) -> str:
        """状態を読み上げ用に 1 行で言う。視覚情報に頼らず現状を伝える。"""
        head = tr(
            f"{self.plugin.label_ja} スロット{self.number}",
            f"{self.plugin.label_ja} slot {self.number}",
        )
        if self.track_name:
            head += tr(f"、トラック「{self.track_name}」", f", track “{self.track_name}”")
        if not self.has_content:
            return tr(f"{head}、未割り当て", f"{head}, not assigned")
        parts = [head]
        if self.summary_ja:
            parts.append(self.summary_ja)
        if self.mode == MODE_DRUMKIT:
            parts.append(tr(
                f"{self.sample_count}個のワンショット",
                plural(self.sample_count, "one-shot"),
            ))
        return COMMA.join(parts)


@dataclass
class SlotLedger:
    """スロットの割り当て台帳。

    キーは (プラグイン種別, スロット番号)。sforzando のスロット 3 と
    Decent Sampler のスロット 3 は別物として扱う。
    """

    layout: SlotLayout = field(default_factory=SlotLayout)
    assignments: dict[tuple[PluginKind, int], SlotAssignment] = field(
        default_factory=dict
    )

    VERSION = 1

    # ---------------- 生成と参照 ----------------

    @classmethod
    def create(
        cls, layout: SlotLayout | None = None, plugins: list[PluginKind] | None = None
    ) -> "SlotLedger":
        """全スロットを未使用で初期化した台帳を作る。"""
        layout = layout or SlotLayout()
        ledger = cls(layout=layout)
        for plugin in plugins or list(PluginKind):
            for number in layout.numbers():
                ledger.assignments[(plugin, number)] = SlotAssignment(
                    number=number, plugin=plugin
                )
        return ledger

    def get(self, plugin: PluginKind, number: int) -> SlotAssignment:
        try:
            return self.assignments[(plugin, number)]
        except KeyError:
            raise SlotError(
                tr(
                    f"{plugin.label_ja} のスロット{number}は台帳にありません。"
                    "初期設定をやり直してください",
                    f"Slot {number} of {plugin.label_ja} is not in the ledger. Please set it up "
                    "again",
                )
            ) from None

    def slots_of(self, plugin: PluginKind) -> list[SlotAssignment]:
        return [
            self.assignments[(plugin, n)]
            for n in self.layout.numbers()
            if (plugin, n) in self.assignments
        ]

    def find_by_track(
        self, plugin: PluginKind, track_name: str
    ) -> SlotAssignment | None:
        """トラック名からスロットを引く。大文字小文字と前後空白は無視する。"""
        key = track_name.strip().casefold()
        for slot in self.slots_of(plugin):
            if slot.track_name and slot.track_name.strip().casefold() == key:
                return slot
        return None

    # ---------------- 割り当て ----------------

    def choose_slot(
        self,
        plugin: PluginKind,
        track_name: str,
        known_number: int | None = None,
    ) -> SlotAssignment:
        """割り当て先スロットを選ぶ。**台帳は書き換えない。** 上ほど確実。

        1. `known_number` — プラグインが表示している設定名から逆算できた番号。
           **台帳より確実なので最優先する**（台帳はずれることがある）
        2. トラック名での既存の結び付き
        3. 未使用スロットのうち最小番号

        **選ぶことと結び付けることを分けてある。** 選んだあとに
        `.sfz` の書き込みや下ごしらえで失敗することがあるので、
        書けてから結び付ける（`bind`）。先に結び付けると、失敗した割り当てで
        スロットが埋まったままになる。
        """
        if not track_name.strip():
            raise SlotError(tr(
                "トラック名が空です。割り当て先を特定できません",
                "The track name is empty, so the assignment target cannot be identified",
            ))

        if known_number is not None:
            return self.get(plugin, known_number)

        existing = self.find_by_track(plugin, track_name)
        if existing is not None:
            return existing

        for slot in self.slots_of(plugin):
            if slot.is_free:
                return slot

        raise SlotError(
            tr(
                f"{plugin.label_ja} の空きスロットがありません"
                f"（最大{self.layout.slot_count}個）。"
                "不要な割り当てを解除してください",
                f"There are no free {plugin.label_ja} slots (up to {self.layout.slot_count}). "
                "Please release an assignment you do not need",
            )
        )

    def bind(self, slot: SlotAssignment, track_name: str) -> SlotAssignment:
        """スロットをトラックへ結び付ける。**書けてから呼ぶ。**"""
        slot.track_name = track_name
        return slot

    def resolve(
        self,
        plugin: PluginKind,
        track_name: str,
        known_number: int | None = None,
    ) -> SlotAssignment:
        """選んで、そのまま結び付ける。`choose_slot` + `bind`。"""
        return self.bind(
            self.choose_slot(plugin, track_name, known_number), track_name
        )

    def assign(self, slot: SlotAssignment, instrument: Instrument) -> SlotAssignment:
        """スロットに配置内容を記録する。

        `.sfz` を実際に書くのは呼び出し側（integration 層）の仕事。
        ここは台帳の更新だけを行う。
        """
        root = instrument.zones[0].root_key
        if not MIDI_MIN <= root <= MIDI_MAX:
            raise SlotError(tr(
                f"ルートキーが範囲外です: {root}",
                f"The root key is out of range: {root}",
            ))

        slot.mode = instrument.mode
        slot.summary_ja = instrument.describe_ja()
        slot.sample_count = len(instrument.zones)
        # クロマティックならルートキー、ドラムキットなら並びの開始ノート。
        # どちらも「どの鍵盤を基準に置いたか」を表す。
        slot.root_key = root
        slot.updated_at = datetime.now(timezone.utc).isoformat()
        return slot

    def release(self, plugin: PluginKind, number: int) -> SlotAssignment:
        """割り当てを解除して未使用へ戻す。"""
        slot = self.get(plugin, number)
        slot.track_name = None
        slot.mode = None
        slot.summary_ja = ""
        slot.sample_count = 0
        slot.root_key = None
        slot.updated_at = datetime.now(timezone.utc).isoformat()
        return slot

    # ---------------- 経路 ----------------

    def path_for(self, slot: SlotAssignment) -> str:
        return self.layout.path(slot.number, slot.plugin)

    def setting_name_for(self, slot: SlotAssignment) -> str:
        return self.layout.setting_name(slot.number)

    # ---------------- 永続化 ----------------

    def to_json(self) -> str:
        data = {
            "version": self.VERSION,
            "layout": {
                "slots_dir": self.layout.slots_dir,
                "slot_count": self.layout.slot_count,
                "setting_prefix": self.layout.setting_prefix,
                # **セッション名も残す。** 残さないと、読み戻した台帳の
                # 置き場所が根に戻り、2 回目以降の割り当てが
                # 全セッション共有の場所へ書かれる（2026-09-05 に踏んだ）。
                "session": self.layout.session,
            },
            "assignments": [
                slot.to_dict()
                for _, slot in sorted(
                    self.assignments.items(),
                    key=lambda kv: (kv[0][0].value, kv[0][1]),
                )
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "SlotLedger":
        data = json.loads(text)
        version = data.get("version")
        if version != cls.VERSION:
            raise SlotError(
                tr(
                    f"台帳のバージョンが未対応です: {version}（対応: {cls.VERSION}）",
                    f"This ledger version is not supported: {version} (supported: {cls.VERSION})",
                )
            )
        raw = data.get("layout", {})
        layout = SlotLayout(
            slots_dir=raw.get("slots_dir") or default_slots_dir(),
            slot_count=int(raw.get("slot_count", 16)),
            setting_prefix=raw.get("setting_prefix", "SLOT"),
            session=raw.get("session", ""),
        )
        ledger = cls(layout=layout)
        for item in data.get("assignments", []):
            slot = SlotAssignment.from_dict(item)
            ledger.assignments[(slot.plugin, slot.number)] = slot
        return ledger

    # ---------------- 読み上げ ----------------

    def summary_ja(self) -> str:
        """台帳全体の状態を 1 文で。"""
        parts: list[str] = []
        for plugin in PluginKind:
            slots = self.slots_of(plugin)
            if not slots:
                continue
            used = sum(1 for s in slots if not s.is_free)
            # 「2分の8」は分数に読めてしまう。個数として言い切る。
            parts.append(tr(
                f"{plugin.label_ja} {len(slots)}個中{used}個使用中",
                f"{plugin.label_ja}: {used} of {plural(len(slots), 'slot')} in use",
            ))
        return COMMA.join(parts) if parts else tr(
            "スロットは未初期化です",
            "The slots are not set up",
        )


def slot_number_from_setting_name(name: str, layout: SlotLayout) -> int | None:
    """プラグインが表示している設定名からスロット番号を逆算する。

    Pro Tools の Librarian に出ている名前（例 `SLOT_03`）から番号を取る。
    **台帳より確実な情報源**なので、`resolve()` の `known_number` に渡す。
    合致しなければ None（そのインスタンスはスロット未設定）。
    """
    text = name.strip()
    for suffix in (".tfx", ".sfz", ".dspreset"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
            break
    for number in layout.numbers():
        if text.casefold() == layout.setting_name(number).casefold():
            return number
    return None
