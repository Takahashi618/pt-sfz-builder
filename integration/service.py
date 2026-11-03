"""割り当ての実行。計画を受けて、書いて、読み直させる。

**ここでは判断をしない。** 何をするかは `core/assign.py` が決めている。
この層は決まったことを順に行い、結果を読み上げ文言にして返すだけ。

失敗の重さを分けてある。

| 失敗した場所 | 扱い | 理由 |
| --- | --- | --- |
| 下ごしらえ（伸縮が要るとき） | **中止**（ok=False） | 無いファイルを指す SFZ を書いても鳴らない |
| `.sfz` の書き込み | **中止**（ok=False） | これが本体。書けなければ何も起きていない |
| 台帳の保存 | 続行＋`[警告]` | 今回の割り当ては効いている。次回の記憶が飛ぶだけ |
| 再読込 | 続行＋`[警告]` | 書けてはいる。人が選び直せば反映される |

**下ごしらえは `.sfz` を書く前に済ませる。** 順序を逆にすると、
まだ存在しないファイルを指す SFZ ができ、プラグインが
「サンプルが見つからない」のモーダルを出す。

### 台帳に載せるのは最後

`plan_assignment` はスロットを**選ぶ**だけで台帳に触らない。
**中止したときに台帳が動いていないこと**が要る。動いていると、
実体の無い音色が台帳に残り、スロットも埋まったままになる
（次の割り当てが別のスロットへ逃げ、Cmd+Shift+L は嘘を読み上げる）。

「書けていれば作業は前に進んでいる」ので、そこから先の失敗で
全部を無かったことにはしない。
"""

from __future__ import annotations

from core.i18n import tr

from dataclasses import dataclass, field, replace
from pathlib import Path

from core.assign import (
    AssignPlan,
    AssignRequest,
    commit_assignment,
    describe_slot_ja,
    plan_assignment,
)
from core.atomicio import write_atomic
from core.slots import PluginKind, SlotLayout, SlotLedger

from .reloader import FolderWatchReload, ReloadRequest, ReloadResult, ReloadTrigger
from .render import render_phrase

__all__ = [
    "AssignOutcome",
    "AssignService",
    "load_ledger",
    "save_ledger",
]


@dataclass
class AssignOutcome:
    """実行の結果。"""

    ok: bool
    message_ja: str
    plan: AssignPlan
    reload: ReloadResult | None = None
    written_path: str | None = None
    notes: tuple[str, ...] = field(default=())

    def describe_ja(self) -> str:
        """注意まで含めた読み上げ文言。"""
        if not self.notes:
            return self.message_ja
        return self.message_ja + " " + " ".join(self.notes)


def load_ledger(
    path: str | Path,
    *,
    layout: SlotLayout | None = None,
    plugins: list[PluginKind] | None = None,
) -> SlotLedger:
    """台帳を読む。ファイルが無ければ新しく作る。

    **壊れていた場合は例外を投げる。** 黙って作り直すと、それまでの
    割り当てが消えたことに気づけない。呼び出し側で受けて、
    作り直すか直すかを人に選ばせる。
    """
    target = Path(path)
    if not target.is_file():
        return SlotLedger.create(layout, plugins)
    ledger = SlotLedger.from_json(target.read_text(encoding="utf-8"))
    # **読み込んだ場所のセッションを優先する。** 台帳の中身と、それが
    # 置かれているフォルダが食い違うことがある（セッション名を
    # 残す前に書かれた台帳、フォルダごと写した台帳）。
    # 食い違ったまま使うと、別のセッションのスロットを書き換える。
    if layout is not None and layout.session and ledger.layout.session != layout.session:
        ledger.layout = replace(ledger.layout, session=layout.session)
    # **置き場所も、いま使っている場所を優先する。** 台帳には書いた時の
    # 置き場所（絶対パス）が入っている。フォルダごと動かしたり写したりした
    # 台帳をそのまま使うと、`.sfz` を元の場所へ書きに行く（いま sforzando が
    # 見ている場所には何も届かない）。
    if layout is not None and ledger.layout.slots_dir != layout.slots_dir:
        ledger.layout = replace(ledger.layout, slots_dir=layout.slots_dir)
    return ledger


def save_ledger(ledger: SlotLedger, path: str | Path) -> Path:
    """台帳を書く。書きかけを読まれないよう差し替え方式で。"""
    return write_atomic(path, ledger.to_json() + "\n")


class AssignService:
    """割り当てを実行する。

    `reload_trigger` を省略すると `FolderWatchReload` になる。
    **sforzando は置き場所を監視していて、書き換えれば自動で読み直す**
    （2026-09-04 実機確認）。こちらからトリガーを撃つ必要が無い。

    テストで「何もしない」経路を通したいときは `NullReload` を明示的に渡す。
    """

    def __init__(
        self,
        ledger: SlotLedger,
        reload_trigger: ReloadTrigger | None = None,
        *,
        ledger_path: str | Path | None = None,
        renderer=None,
    ) -> None:
        self._ledger = ledger
        self._trigger = reload_trigger or FolderWatchReload()
        self._ledger_path = Path(ledger_path) if ledger_path else None
        # 下ごしらえの実体。テストではスタブを注入して、ffmpeg を呼ばずに
        # 全経路を通す。
        self._render = renderer or render_phrase

    @property
    def ledger(self) -> SlotLedger:
        return self._ledger

    def assign(self, request: AssignRequest) -> AssignOutcome:
        """計画を立てて、そのまま実行する。"""
        return self.execute(plan_assignment(request, self._ledger))

    def execute(self, plan: AssignPlan) -> AssignOutcome:
        """計画を実行する。"""
        if not plan.ok:
            # 計画の段階で止まっている。**何も書かない。**
            return AssignOutcome(
                ok=False, message_ja=plan.describe_ja(), plan=plan
            )

        if plan.sfz_path is None or plan.sfz_text is None or plan.slot is None:
            return AssignOutcome(
                ok=False,
                message_ja=tr(
                    "[エラー] 計画に書き込み先がありません。内部の不整合です。",
                    "[Error] The plan has no file to write. This is an internal inconsistency.",
                ),
                plan=plan,
            )

        # **下ごしらえを先に済ませる。** 順序を逆にすると、まだ無い
        # ファイルを指す SFZ ができ、プラグインがモーダルのエラーを出す。
        if plan.renders:
            rendered = self._render(plan.renders)
            if not rendered.ok:
                return AssignOutcome(
                    ok=False,
                    message_ja=rendered.message_ja,
                    plan=plan,
                )

        try:
            written = write_atomic(plan.sfz_path, plan.sfz_text)
        except OSError as exc:
            return AssignOutcome(
                ok=False,
                message_ja=tr(
                    f"[エラー] {plan.sfz_path} に書けませんでした。{exc}",
                    f"[Error] Could not write {plan.sfz_path}. {exc}",
                ),
                plan=plan,
            )

        # **ここで初めて台帳に載せる。** 下ごしらえも書き込みも通った。
        # 先に載せると、実体の無い音色が台帳に残り、スロットも埋まる。
        commit_assignment(plan, self._ledger)

        # **ルートキーをどう決めたかを先に言う**（自動で決めたときだけ）。
        # 既定値に落ちたときの「鳴らして確かめてください」を消さない。
        notes = ([plan.root_note] if plan.root_note else []) + list(plan.notes)
        if plan.renders:
            notes.append(rendered.describe_ja())

        problem = self._save_ledger()
        if problem is not None:
            notes.append(problem)

        reload_result = self._trigger.reload(
            ReloadRequest(
                slot=plan.slot,
                setting_name=plan.setting_name or "",
                file_path=str(written),
            )
        )
        # 完了報告は台帳の状態から組み立てる。注意事項は notes に集めて
        # 最後にまとめて読み上げるので、ここでは混ぜない。
        success_line = describe_slot_ja(plan.slot)
        if reload_result.ok:
            message = f"{success_line} {reload_result.message_ja}"
        else:
            notes.append(reload_result.message_ja)
            message = success_line

        return AssignOutcome(
            ok=True,
            message_ja=message,
            plan=plan,
            reload=reload_result,
            written_path=str(written),
            notes=tuple(notes),
        )

    def release(self, plugin: PluginKind, number: int) -> AssignOutcome:
        """割り当てを解除する。`.sfz` は消さず、台帳から外すだけ。

        ファイルを残すのは、消しても Pro Tools 側の設定は残るため。
        消すと「設定はあるのにファイルが無い」状態になり、
        プラグインがエラーを出す。
        """
        slot = self._ledger.release(plugin, number)
        notes: list[str] = []
        problem = self._save_ledger()
        if problem is not None:
            notes.append(problem)
        return AssignOutcome(
            ok=True,
            message_ja=tr(
                f"{plugin.label_ja} スロット{number}の割り当てを解除しました。",
                f"Released the assignment of {plugin.label_ja} slot {number}.",
            ),
            plan=AssignPlan(ok=True, message_ja="", slot=slot),
            notes=tuple(notes),
        )

    def _save_ledger(self) -> str | None:
        """台帳を保存する。失敗したら注意文を返す（例外にはしない）。"""
        if self._ledger_path is None:
            return None
        try:
            save_ledger(self._ledger, self._ledger_path)
        except (OSError, TypeError, ValueError) as exc:
            return tr(
                f"[警告] 割り当ては効いていますが、台帳を保存できませんでした。{exc}",
                f"[Warning] The assignment works, but the ledger could not be saved. {exc}",
            )
        return None
