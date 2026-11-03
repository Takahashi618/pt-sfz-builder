"""再読込のトリガー。**実機の結果、既定では何もしなくてよくなった。**

### 結論（2026-09-04 実機確認）

**sforzando は `.sfz` の置き場所を監視していて、書き換えると自動で読み直す。**
プラグインのログにそのまま出る。

    FolderWatcher start for *<スロットの置き場所>*

`core/atomicio.py` の差し替え方式（一時ファイル → rename）でも拾われることを
確認済み。リージョン 1 個の SFZ を 3 個に書き換えたら、**操作を一切せずに**
プラグインの表示が 1 → 3 に変わった。

そのため既定は `FolderWatchReload`（何もせず「反映されます」と伝える）。
**一度 `import` でスロットを読ませたあとは、書くだけでよい。**

### 元の設計との差

当初は「書き換えても自動では読み直さない」前提で、3 つの案を用意していた。

| 案 | 手順 | 実機の結果 |
| --- | --- | --- |
| A | Pro Tools の Librarian から同じ設定を選び直す | 未検証。要らなくなった |
| B | Decent Sampler の Cmd+O | **不可。**Pro Tools がキーを横取りする |
| C | プラグインのファイル名欄を座標クリック → reload | **可能。**保険として残す |

**案 B は Pro Tools の中では成立しない。** プラグインウィンドウを最前面に
してもキーストロークは届かず、Pro Tools 本体の「セッションを開く」が出る。

案 C は `tools/sforzando_load.py` に実装がある。監視が効かない場面
（別のフォルダに置いた・監視が止まった）の逃げ道として残す。

**Protocol は残す。** Decent Sampler や TX16Wx に広げるとき、
同じ仕組みとは限らないため。
"""

from __future__ import annotations

from core.i18n import APP_NAME, tr

import enum
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from core.sibling import FROZEN
from core.slots import SlotAssignment

__all__ = [
    "ReloadOutcome",
    "ReloadRequest",
    "ReloadResult",
    "ScriptResult",
    "ScriptRunner",
    "OsascriptRunner",
    "permission_hint",
    "explain_error",
    "ReloadTrigger",
    "NullReload",
    "FolderWatchReload",
    "LibrarianReload",
    "KeyboardOpenReload",
]


class ReloadOutcome(enum.Enum):
    DONE = "done"  # 再読込させた
    SKIPPED = "skipped"  # 何もしていない。人が操作する必要がある
    FAILED = "failed"  # 試みたが失敗した


@dataclass(frozen=True)
class ReloadRequest:
    """再読込に要る情報ひとそろい。

    案によって使う項目が違うので、まとめて渡して各実装に選ばせる。
    """

    slot: SlotAssignment
    setting_name: str
    file_path: str


@dataclass(frozen=True)
class ReloadResult:
    outcome: ReloadOutcome
    message_ja: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        """失敗していないか。**何もしなかった場合も ok とみなす。**

        自動化できなくても、人が選び直せば使える。書き込み自体は
        済んでいるので、そこまでを成功として扱う。
        """
        return self.outcome is not ReloadOutcome.FAILED


# --------------------------------------------------------------------------
# AppleScript の実行
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptResult:
    ok: bool
    output: str = ""
    error: str = ""


class ScriptRunner(Protocol):
    """AppleScript を実行するもの。テストではスタブを注入する。"""

    def run(self, script: str, args: Sequence[str]) -> ScriptResult: ...


class OsascriptRunner:
    """`osascript` で AppleScript を実行する。**macOS 専用。**

    Windows では実行時に分かるようエラーを返す。import では落とさない
    （型として扱えないと、Windows 側でテストが書けなくなる）。
    """

    def __init__(self, scripts_dir: str | Path, timeout: float = 15.0) -> None:
        self._dir = Path(scripts_dir)
        self._timeout = timeout

    def run(self, script: str, args: Sequence[str]) -> ScriptResult:
        """`tools/` に置いたスクリプトファイルを実行する。"""
        path = self._dir / script
        if sys.platform == "darwin" and not path.is_file():
            return ScriptResult(False, error=tr(
                f"スクリプトが見つかりません: {path}",
                f"Script not found: {path}",
            ))
        return self._invoke([str(path)], args)

    def run_text(self, script: str, args: Sequence[str] = ()) -> ScriptResult:
        """その場で書いた AppleScript を実行する（標準入力から渡す）。

        **時間の上限と macOS の判定を 1 か所に集めるためにここに置く。**
        道具ごとに `subprocess.run` を書いていたときは、上限の無いものが
        混ざっていて、モーダルで止まると戻ってこなかった。
        """
        return self._invoke(["-"], args, stdin=script)

    def _invoke(
        self, head: Sequence[str], args: Sequence[str], *, stdin: str | None = None
    ) -> ScriptResult:
        if sys.platform != "darwin":
            return ScriptResult(
                False, error=tr(
                    "AppleScript は macOS でしか実行できません",
                    "AppleScript runs only on macOS",
                )
            )
        try:
            completed = subprocess.run(
                ["osascript", *head, *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ScriptResult(
                False, error=tr(
                    f"{self._timeout} 秒待っても応答がありませんでした",
                    f"No response after {self._timeout} seconds",
                )
            )
        except OSError as exc:
            return ScriptResult(False, error=str(exc))

        if completed.returncode != 0:
            return ScriptResult(
                False,
                output=(completed.stdout or "").strip(),
                error=(completed.stderr or "").strip(),
            )
        return ScriptResult(True, output=(completed.stdout or "").strip())


# AppleScript の失敗のうち、**利用者が自分で直せるもの**（許可）。番号で見分ける。
# 文はシステムの言語で変わるが、番号は変わらない。
_AUTOMATION_CODES = ("-1743",)
_ACCESSIBILITY_CODES = ("-1719", "-25211")


def _permission_holder() -> str:
    """許可を入れる先のアプリの名前。**ソースから起動したときはターミナル。**

    macOS は、許可を「起動したアプリ」に付ける。ソースから起動していると
    python ではなくターミナルに許可が要る（作者の別のアプリの知見）。
    手元の .app はランチャが `SFZBUILDER_APP` を渡すので見分けられる。
    """
    if FROZEN or os.environ.get("SFZBUILDER_APP", "").strip():
        return APP_NAME
    return tr("このアプリを起動したターミナル", "the Terminal app that started this app")


def permission_hint(error: str) -> str:
    """AppleScript の失敗が許可の不足なら、**どこで何を入れればよいか**の文。違えば空文字。

    許可が無いときの osascript のエラーは英語交じりの長い文で、
    読み上げで聞いても直し方が分からない。配布版を初めて開いた人が
    必ず通る道なので、どこで何を入れればよいかまで言う。
    """
    text = error or ""
    holder = _permission_holder()
    if any(code in text for code in _AUTOMATION_CODES):
        return tr(
            "System Events を操作する許可がありません。"
            "システム設定の「プライバシーとセキュリティ」→「オートメーション」で、"
            f"{holder}の「System Events」をオンにしてください。",
            "Permission to control System Events is missing. In System Settings, go to "
            f"Privacy & Security, Automation, and under {holder} turn on System Events.",
        )
    if any(code in text for code in _ACCESSIBILITY_CODES) or "assistive access" in text:
        return tr(
            "アクセシビリティの許可がありません。"
            "システム設定の「プライバシーとセキュリティ」→「アクセシビリティ」で、"
            f"{holder}をオンにしてください。"
            "操作メニューの「アクセシビリティの設定を開く」で、その画面を開けます。",
            "Accessibility permission is missing. In System Settings, go to Privacy & "
            f"Security, Accessibility, and turn on {holder}. The Open Accessibility Settings "
            "item in the Actions menu takes you there.",
        )
    return ""


def explain_error(error: str) -> str:
    """AppleScript の失敗を読み上げる文にする。許可の不足なら直し方を言う。

    分からないものは元の文のまま返す（黙って捨てない）。
    """
    return permission_hint(error) or (error or "").strip()


# --------------------------------------------------------------------------
# 再読込のトリガー
# --------------------------------------------------------------------------


class ReloadTrigger(Protocol):
    def reload(self, request: ReloadRequest) -> ReloadResult: ...


class NullReload:
    """本当に何もしない。**テスト用。**

    「書いたが、反映は人がやる」という状態を表す。実機では
    `FolderWatchReload` が既定になったので、こちらはテストと、
    監視が期待できない場面のために残す。
    """

    def reload(self, request: ReloadRequest) -> ReloadResult:
        return ReloadResult(
            ReloadOutcome.SKIPPED,
            tr(
                f"書き込みました。{request.setting_name} を選び直すと反映されます。",
                f"Written. Select {request.setting_name} again to apply it.",
            ),
        )


class FolderWatchReload:
    """**既定。** プラグイン側の監視に任せる。

    sforzando（ARIA エンジン）は読み込んだ `.sfz` の置き場所を監視していて、
    書き換えると自動で読み直す（2026-09-04 実機確認）。こちらから何かを
    する必要が無い。

    **何もしないが `SKIPPED` ではなく `DONE` を返す。** 実際に反映されるので、
    「人が操作しないと反映されない」と読み上げるのは誤りになる。

    ただし**そのスロットを一度も読ませていなければ監視は始まっていない。**
    最初の 1 回だけは `tools/sforzando_load.py import` が要る。
    それを伝えるため `first_time` を渡せるようにしてある。
    """

    def reload(self, request: ReloadRequest) -> ReloadResult:
        return ReloadResult(
            ReloadOutcome.DONE,
            tr("書き込みました。自動で反映されます。", "Written. It applies automatically."),
            detail=request.file_path,
        )


class LibrarianReload:
    """案 A: Pro Tools の Librarian から同じ設定を選び直す。

    設定を選び直せばプラグインが状態を読み直すので、そこから `.sfz` も
    読み直される **はず**。S3-a で確かめる。
    """

    SCRIPT = "ax_select_setting.applescript"

    def __init__(self, runner: ScriptRunner) -> None:
        self._runner = runner

    def reload(self, request: ReloadRequest) -> ReloadResult:
        result = self._runner.run(self.SCRIPT, [request.setting_name])
        if not result.ok:
            return ReloadResult(
                ReloadOutcome.FAILED,
                tr(
                    f"[警告] {request.setting_name} を選び直せませんでした。"
                    "手で選び直してください。",
                    f"[Warning] Could not select {request.setting_name} again. Please select it "
                    "by hand.",
                ),
                detail=result.error,
            )
        return ReloadResult(
            ReloadOutcome.DONE,
            tr(
                f"{request.setting_name} を選び直して反映しました。",
                f"Selected {request.setting_name} again to apply it.",
            ),
            detail=result.output,
        )


class KeyboardOpenReload:
    """案 B: Cmd+O でプリセットを開き直す（Decent Sampler v1.12.2 以降）。

    開くのは macOS 標準のダイアログなので、**VoiceOver だけで完結する**
    （Cmd+Shift+G でパスを直接入力できる）。これが通れば AppleScript も
    座標クリックも要らなくなる。S3-b で確かめる。
    """

    # **2 本に分けてある。** 後半（パスを入れて確定する）は
    # `tools/sforzando_load.py` と共有する。同じ手順を 2 か所に
    # 書いていたときは、実機で詰めた待ち時間がすでに食い違っていた。
    OPEN_SCRIPT = "press_cmd_o.applescript"
    FILL_SCRIPT = "fill_open_dialog.applescript"

    def __init__(self, runner: ScriptRunner) -> None:
        self._runner = runner

    def reload(self, request: ReloadRequest) -> ReloadResult:
        result = self._runner.run(self.OPEN_SCRIPT, [])
        if result.ok:
            result = self._runner.run(self.FILL_SCRIPT, [request.file_path])
        if not result.ok:
            return ReloadResult(
                ReloadOutcome.FAILED,
                tr(
                    "[警告] プリセットを開き直せませんでした。"
                    f"プラグインの画面で Cmd+O を押し、{request.file_path} を開いてください。",
                    "[Warning] Could not reopen the preset. In the plugin window, press "
                    f"Command-O and open {request.file_path}.",
                ),
                detail=result.error,
            )
        return ReloadResult(
            ReloadOutcome.DONE,
            tr("プリセットを開き直して反映しました。", "Reopened the preset to apply it."),
            detail=result.output,
        )
