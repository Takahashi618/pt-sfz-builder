"""割り当ての計画を立てる。

「何をどの順で行うか」と「そもそも実行してよいか」だけを決める純粋関数。
実際のファイル書き込みと再読込は integration 層が行う。

こうしておくと、Pro Tools も macOS も無い Windows で判断の全分岐を試せる。
`.sfz` の中身まで計画に含めてあるので、**書き出す前に内容を検証できる**。

中断する条件は絞ってある。むやみに止めると使い勝手が落ちるので、
判断がつかないものは注意として添えたうえで実行する。
"""

from __future__ import annotations

from .i18n import COMMA, plural, tr
from .sibling import part_message

from collections.abc import Sequence
from dataclasses import dataclass, field

from .mapping import (
    DEFAULT_DRUM_START,
    MODE_CHROMATIC,
    MODE_DRUMKIT,
    MODE_PHRASE,
    DrumEntry,
    Instrument,
    build_chromatic,
    build_phrase,
    build_drumkit,
    to_sfz,
)
from .kinds import KIND_FX, KIND_ONESHOT
from .notes import note_name
from .phrase import PHRASE_SPAN_DEFAULT, PhraseError, plan_phrase
from .rootkey import DEFAULT_OCTAVE, KeyAnalyzer, decide_root_key
from .sfz import SfzError, render
from .slots import SlotAssignment, SlotError, SlotLedger
from .target import PluginTarget
from .tempo import decide_tempo, stretch_for, tempo_tag
from .tone import ToneSettings

__all__ = [
    "SUPPORTED_FORMATS",
    "SampleRef",
    "AssignRequest",
    "AssignPlan",
    "plan_assignment",
    "commit_assignment",
    "describe_slot_ja",
    "describe_success_ja",
]

# sforzando（ARIA エンジン）と Decent Sampler が読める音声形式。
# 拡張子は小文字・ドット無しで比べる。
SUPPORTED_FORMATS: frozenset[str] = frozenset({"wav", "aif", "aiff", "flac", "ogg"})


@dataclass(frozen=True)
class SampleRef:
    """割り当てる 1 サンプル。

    `kind` は `splicename.parse()` の種別（`loop` / `one_shot` / `fx`）を
    そのまま入れる想定。**任意**で、無くても動く。あればループ素材に
    注意を添えられる。
    """

    path: str
    name: str = ""
    kind: str | None = None

    @property
    def display_name(self) -> str:
        """表示・読み上げ用の名前。省略されていればパスの末尾を使う。"""
        if self.name:
            return self.name
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        """拡張子（小文字・ドット無し）。無ければ空文字。"""
        tail = self.path.rsplit("/", 1)[-1]
        if "." not in tail:
            return ""
        return tail.rsplit(".", 1)[-1].lower()


@dataclass
class AssignRequest:
    """割り当ての入力。UI 層から渡される情報をまとめたもの。"""

    target: PluginTarget
    samples: Sequence[SampleRef]
    mode: str = MODE_CHROMATIC
    tone: ToneSettings | None = None
    root_key: int | None = None  # None なら決定手順に任せる
    octave: int = DEFAULT_OCTAVE
    start_note: int = DEFAULT_DRUM_START
    known_slot_number: int | None = None
    analyzer: KeyAnalyzer | None = None
    instrument_name: str = ""
    # 速さを保つ配置で、ルートから上下に何半音まで用意するか。
    # 大きくすると待ち時間が延び、音も荒れる（`core/phrase.py`）。
    phrase_span: int = PHRASE_SPAN_DEFAULT
    # セッションのテンポ。None なら素材のテンポのまま（`core/tempo.py`）。
    # **合わないループは使えないことが多い**ので、合わせられるようにしてある。
    target_bpm: int | None = None
    # 倍・半分のテンポの解釈を許すか。**素材の BPM 表記が実感と半分
    # ずれていることがある**ので、既定では許す。意図と違う向きに
    # 動いたときのために切れるようにしてある（設定ダイアログ）。
    allow_half_double: bool = True


@dataclass
class AssignPlan:
    """割り当ての実行計画。

    `ok` が False なら integration 層は**何も実行してはならない**。
    `notes` には注意事項が入る。**`[警告]` が要るものだけ接頭辞を付けてある**
    ので、そのまま読み上げてよい。
    """

    ok: bool
    message_ja: str
    slot: SlotAssignment | None = None
    sfz_path: str | None = None
    sfz_text: str | None = None
    setting_name: str | None = None
    root_key: int | None = None
    notes: tuple[str, ...] = field(default=())
    # 速さを保つ配置のときだけ入る。**実行層はこれを先に作ってから
    # `.sfz` を書く。** 先に書くと、まだ無いファイルを指す SFZ ができる。
    renders: tuple = field(default=())
    # 台帳へ載せる中身と結び付け先。**まだ載せていない。**
    # 書き込みまで済んでから `commit_assignment` で載せる。
    instrument: object | None = None
    track_name: str = ""
    # ルートキーをどう決めたか（自動で決めたときだけ）。**割り当てたあとに言う。**
    # 「推定できなかったので既定値です。鳴らして確かめてください」のような
    # 大事な一言が、以前は計画の文にしか入らず、割り当ての結果では消えていた。
    root_note: str = ""

    def describe_ja(self) -> str:
        """注意まで含めた読み上げ文言。"""
        if not self.notes:
            return self.message_ja
        return self.message_ja + " " + " ".join(self.notes)


def _check_formats(samples: Sequence[SampleRef]) -> str | None:
    """扱えない形式があれば、その説明を返す。無ければ None。"""
    supported = COMMA.join(sorted(SUPPORTED_FORMATS))
    for sample in samples:
        extension = sample.extension
        if extension not in SUPPORTED_FORMATS:
            label = extension or tr("拡張子なし", "no extension")
            return tr(
                f"[警告] {sample.display_name} は {label} です。"
                f"割り当てられるのは {supported} だけです。中止しました。",
                f"[Warning] {sample.display_name} is {label}. Only {supported} can be "
                "assigned. Stopped.",
            )
    return None


def _note_tempo(notes: list[str], decision) -> None:
    """テンポの判断を読み上げ用の注意へ移す。

    **変えなかったときも、理由があるなら伝える。** 黙っていると
    「合わせたつもり」で使い続けることになる。
    """
    if decision.changes:
        notes.append(decision.message_ja)
    notes.extend(decision.warnings)


def _build_instrument(
    request: AssignRequest,
    root_key: int,
    notes: list[str],
    render_dir: str,
) -> tuple[Instrument, tuple]:
    """要求から配置を組み立てる。組めなければ `SfzError` を投げる。

    戻り値は (配置, 下ごしらえの一覧)。下ごしらえは
    **速さを保つ配置のときだけ**中身が入る。
    """
    if request.mode == MODE_PHRASE:
        # クロマティックと同じく 1 サンプルだけ使う
        if len(request.samples) > 1:
            notes.append(
                tr(
                    f"{len(request.samples)}個選ばれていますが、"
                    "速さを保つ配置では先頭の1個だけを使います。",
                    f"{plural(len(request.samples), 'sample')} selected, but the keep-speed "
                    "mapping uses only the first one.",
                )
            )
        head = request.samples[0]
        # **テンポ合わせは鍵盤ごとの倍率に掛け合わせる。**
        # これでどの鍵盤でもセッションのテンポで鳴る。
        tempo = decide_tempo(
            head.display_name,
            request.target_bpm,
            allow_half_double=request.allow_half_double,
        )
        _note_tempo(notes, tempo)
        try:
            plan = plan_phrase(
                head.path,
                root_key,
                span=request.phrase_span,
                out_dir=render_dir,
                tempo_ratio=tempo.ratio,
                tempo_tag=tempo_tag(tempo),
            )
        except PhraseError as exc:
            raise SfzError(str(exc)) from exc
        instrument = build_phrase(
            plan,
            name=request.instrument_name or head.display_name,
            tone=request.tone,
            notes=[
                tr(
                    "速さを変えずに鍵盤へ広げている。",
                    "Spreads the sample across the keyboard without changing its speed.",
                ),
                tr(
                    "鍵盤ごとに長さを変えたファイル（下ごしらえ）を使う。",
                    "Uses a file with a different length for each key (prepared files).",
                ),
            ],
        )
        return instrument, plan.renders

    if request.mode == MODE_DRUMKIT:
        # **1 件ずつテンポを見る。** ドラムキットは素材ごとにテンポが違う。
        entries = []
        renders = []
        unreadable = 0
        oneshots = 0
        warnings: list[str] = []
        for sample in request.samples:
            # **ワンショットは伸縮しない。** 名前に BPM が入っていても、
            # 1 発ものの長さを変えると音そのものが変わる。種別は
            # 呼び出し側が長さから決めて入れてくる（`core/kinds.py`）。
            if sample.kind in (KIND_ONESHOT, KIND_FX):
                oneshots += 1
                entries.append(DrumEntry(sample.path, sample.display_name))
                continue
            tempo = decide_tempo(
                sample.display_name,
                request.target_bpm,
                allow_half_double=request.allow_half_double,
            )
            stretch = stretch_for(sample.path, tempo, render_dir)
            entries.append(DrumEntry(stretch.dest, sample.display_name))
            if not stretch.is_original:
                renders.append(stretch)
            elif request.target_bpm is not None and tempo.source_bpm is None:
                unreadable += 1
            # **警告は捨てない。** 同じ文言は畳んで 1 回だけ言う。
            for warning in tempo.warnings:
                if warning.startswith(tr("[警告]", "[Warning]")) and warning not in warnings:
                    warnings.append(warning)
        # **数だけでなく、合わせなかったものの理由も伝える。**
        # 黙っていると「合わせたつもり」で使い続けることになる。
        if renders:
            notes.append(tr(
                f"{len(renders)}個をセッションのテンポに合わせます。",
                f"Matching {plural(len(renders), 'sample')} to the session tempo.",
            ))
        if oneshots and request.target_bpm is not None:
            notes.append(
                tr(
                    f"{oneshots}個はワンショットなので、テンポは変えません。",
                    f"{plural(oneshots, 'sample')} left at the original tempo, because they are "
                    "one-shots.",
                )
            )
        if unreadable:
            notes.append(
                tr(
                    f"{unreadable}個は元のテンポがファイル名から読めなかったので、"
                    "そのままにします。",
                    f"{plural(unreadable, 'sample')} left as they are, because the original tempo "
                    "could not be read from the file name.",
                )
            )
        notes.extend(warnings)
        return (
            build_drumkit(
                entries,
                start_note=request.start_note,
                name=request.instrument_name,
                tone=request.tone,
            ),
            tuple(renders),
        )

    # クロマティックは 1 サンプルだけ使う。黙って捨てると気づけないので伝える。
    if len(request.samples) > 1:
        notes.append(
            tr(
                f"{len(request.samples)}個選ばれていますが、"
                "クロマティックでは先頭の1個だけを使います。",
                f"{plural(len(request.samples), 'sample')} selected, but the chromatic mapping "
                "uses only the first one.",
            )
        )
    head = request.samples[0]
    tempo = decide_tempo(
        head.display_name,
        request.target_bpm,
        allow_half_double=request.allow_half_double,
    )
    _note_tempo(notes, tempo)
    stretch = stretch_for(head.path, tempo, render_dir)
    if not stretch.is_original:
        # **合うのはルートキーだけ。** ほかの鍵盤では速さが変わる。
        # 黙って「テンポを合わせました」と言うと誤解を招く。
        notes.append(
            tr(
                "テンポが合うのはルートキーだけです。"
                "どの鍵盤でも合わせたいときは配置を「速さを保つ」にしてください。",
                "Only the root key matches the tempo. To match on every key, choose “Spread "
                "across the keyboard, keeping speed” as the mapping.",
            )
        )
    return (
        build_chromatic(
            stretch.dest,
            root_key,
            name=request.instrument_name or head.display_name,
            tone=request.tone,
        ),
        () if stretch.is_original else (stretch,),
    )


def plan_assignment(
    request: AssignRequest,
    ledger: SlotLedger,
    *,
    generated_at: str | None = None,
) -> AssignPlan:
    """割り当て計画を立てる。**台帳は書き換えない**（副作用なし）。

    スロットは選ぶだけで、結び付けと記録は `.sfz` を書けてから
    `commit_assignment` が行う。先に台帳を書き換えてしまうと、
    後の失敗で中途半端な状態が残る。
    """
    if not request.samples:
        return AssignPlan(ok=False, message_ja=tr(
            "[警告] 割り当てるサンプルがありません。",
            "[Warning] There are no samples to assign.",
        ))

    problem = _check_formats(request.samples)
    if problem is not None:
        return AssignPlan(ok=False, message_ja=problem)

    notes: list[str] = []
    if request.target.ambiguous:
        notes.append(
            tr(
                f"[警告] トラック名を「{request.target.track_name}」と読みました。"
                "区切りが曖昧なので確かめてください。",
                f"[Warning] The track name was read as “{request.target.track_name}”. The "
                "separator is ambiguous, so please check it.",
            )
        )

    # --- ルートキー ---
    head = request.samples[0]
    if request.root_key is not None:
        root_key = request.root_key
        if not 0 <= root_key <= 127:
            return AssignPlan(
                ok=False,
                message_ja=tr(
                    f"[エラー] ルートキーが範囲外です: {root_key}。0 から 127 で指定してください。",
                    f"[Error] The root key is out of range: {root_key}. Use 0 to 127.",
                ),
            )
        root_message = tr(
            f"ルートキー {note_name(root_key)}（指定値）。",
            f"Root key {note_name(root_key)} (as you set it).",
        )
        root_note = ""  # 自分で決めた値なので、割り当てたあとに言い直さない
    else:
        decided = decide_root_key(
            head.display_name,
            octave=request.octave,
            audio_path=head.path,
            analyzer=request.analyzer,
        )
        root_key = decided.note
        root_message = decided.message_ja
        root_note = root_message
        notes.extend(decided.warnings)

    # ドラムキットではルートキーを使わない（各鍵盤が自分の音になる）
    if request.mode == MODE_DRUMKIT:
        root_message = tr(
            f"{note_name(request.start_note)}から順に並べます。",
            f"Arranged in order from {note_name(request.start_note)}.",
        )
        root_note = ""

    # --- 配置の組み立て ---
    # **下ごしらえはセッションによらず共有**（`SlotLayout.render_dir`）。
    render_dir = ledger.layout.render_dir
    try:
        instrument, renders = _build_instrument(
            request, root_key, notes, render_dir
        )
    except SfzError as exc:
        return AssignPlan(ok=False, message_ja=tr(
            f"[警告] {exc}",
            f"[Warning] {part_message(str(exc))}",
        ))

    # --- ループ素材の注意 ---
    # **逃げ道まで言う。** 「速さも変わります」だけでは、どうすればよいかが
    # 分からない。速さを保つ配置があることをその場で伝える。
    if request.mode == MODE_CHROMATIC and head.kind == "loop":
        notes.append(
            tr(
                "ループ素材です。音程を変えると速さも変わります。"
                "速さを保ちたいときは配置を「速さを保つ」にしてください。",
                "This is a loop. Changing its pitch also changes its speed. To keep its speed, "
                "choose “Spread across the keyboard, keeping speed” as the mapping.",
            )
        )

    # --- スロットを選ぶ。**まだ台帳は書き換えない** ---
    try:
        slot = ledger.choose_slot(
            plugin=request.target.plugin,
            track_name=request.target.track_name,
            known_number=request.known_slot_number,
        )
    except SlotError as exc:
        return AssignPlan(ok=False, message_ja=tr(
            f"[警告] {exc}",
            f"[Warning] {part_message(str(exc))}",
        ))

    # **書き出しの失敗も計画の失敗として返す。** `SfzDocument` は名前や
    # パスに改行があると `SfzError` を投げる。ここだけ try の外に
    # あったので、そのまま画面まで素通りし、読み上げ無しで止まっていた。
    try:
        text = render(to_sfz(instrument, generated_at=generated_at))
    except SfzError as exc:
        return AssignPlan(ok=False, message_ja=tr(
            f"[警告] {exc}",
            f"[Warning] {part_message(str(exc))}",
        ))

    message = tr(
        f"{request.target.plugin.label_ja} スロット{slot.number}に "
        f"{instrument.describe_ja()} を割り当てます。{root_message}",
        f"Assigning {instrument.describe_ja()} to {request.target.plugin.label_ja} slot "
        f"{slot.number}. {root_message}",
    )

    return AssignPlan(
        ok=True,
        message_ja=message,
        slot=slot,
        sfz_path=ledger.path_for(slot),
        sfz_text=text,
        setting_name=ledger.setting_name_for(slot),
        root_key=root_key,
        notes=tuple(notes),
        renders=renders,
        instrument=instrument,
        track_name=request.target.track_name,
        root_note=root_note,
    )


def commit_assignment(plan: AssignPlan, ledger: SlotLedger) -> SlotAssignment | None:
    """計画の内容を台帳へ載せる。**書き込みが済んでから呼ぶ。**

    `plan_assignment` はスロットを**選ぶ**だけで台帳に触らない。
    先に載せてしまうと、下ごしらえや `.sfz` の書き込みで失敗したときに、
    実体の無い音色が台帳に残る。スロットも埋まったままになり、
    次の割り当てが別のスロットへ逃げる。

    載せるものが無ければ何もしない（None を返す）。
    """
    if not plan.ok or plan.slot is None or plan.instrument is None:
        return None
    ledger.bind(plan.slot, plan.track_name)
    ledger.assign(plan.slot, plan.instrument)  # type: ignore[arg-type]
    return plan.slot


def describe_slot_ja(slot: SlotAssignment) -> str:
    """割り当て済みスロットの状態を、完了報告の言い回しで言う。

    注意事項は含めない。実行層は注意を自前で組み立てるので、
    ここで混ぜると二重に読み上げてしまう。
    """
    return tr(
        f"{slot.plugin.label_ja} スロット{slot.number}に "
        f"{slot.summary_ja} を割り当てました。トラック「{slot.track_name}」。",
        f"Assigned {slot.summary_ja} to {slot.plugin.label_ja} slot {slot.number}. Track "
        f"“{slot.track_name}”.",
    )


def describe_success_ja(plan: AssignPlan) -> str:
    """割り当てが済んだあとの読み上げ文言。

    計画時の「割り当てます」を「割り当てました」に言い換える。
    """
    if not plan.ok or plan.slot is None:
        return plan.describe_ja()
    base = describe_slot_ja(plan.slot)
    if plan.notes:
        return base + " " + " ".join(plan.notes)
    return base
