"""テストの共通部品。

pytest を使わず直接実行できるようにしてある。Mac へ持っていくときに
依存を増やしたくないため（プロジェクト方針）。

失敗しても止めずに最後までやり、まとめて報告する。1 件目で止まると
「あと何が壊れているか」が見えず、往復の回数が増えるだけになる。

各テストはこう書く。

    from _harness import Checker
    c = Checker("sfz")
    c.equal("C3 は 60", note_name(60), "C3")
    raise SystemExit(c.summary())
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

# プロジェクトルートを import パスに載せる。tests/ から直接実行できるように。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# **テストの最中は音も読み上げも出さない。** 借りている部品（作者の別のアプリの
# sounds・announce）はこの環境変数で黙る。止めていなかったときは、ビルドの
# たびに効果音が鳴り、VoiceOver がテストの文を読み上げていた
# （2026-10-25 のレビュー。読み上げは 10-24 に借り先が直るまで届いていなかった）。
os.environ["SM_SILENT"] = "1"
os.environ["SM_NO_ANNOUNCE"] = "1"
# テストは日本語の文言で書いてある（英語は tests/test_i18n.py が別のプロセスで見る）
os.environ["SFZBUILDER_LANG"] = "ja"

__all__ = ["Checker"]


class Checker:
    """合否を数えるだけの最小限のテスト器。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = 0
        self.failures: list[str] = []

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        """条件が真なら合格。偽なら detail を添えて記録する。"""
        if condition:
            self.passed += 1
            return True
        self.failures.append(label + (f" — {detail}" if detail else ""))
        return False

    def equal(self, label: str, actual: Any, expected: Any) -> bool:
        """等値の検査。失敗時に期待値と実際値の両方を出す。"""
        return self.check(
            label, actual == expected, f"期待 {expected!r} / 実際 {actual!r}"
        )

    def raises(
        self,
        label: str,
        exc_type: type[BaseException],
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """例外が出ることの検査。

        **別の例外が出た場合も失敗にする。** 「何かしら落ちればよい」に
        するとタイプミスを検出できなくなる。
        """
        try:
            func(*args, **kwargs)
        except exc_type:
            self.passed += 1
            return True
        except Exception as exc:  # noqa: BLE001 — 種類の違いを報告したい
            return self.check(
                label,
                False,
                f"{exc_type.__name__} を期待したが {type(exc).__name__}: {exc}",
            )
        return self.check(label, False, f"{exc_type.__name__} が発生しなかった")

    def summary(self) -> int:
        """結果を出力し、終了コードを返す（0 = 全合格）。"""
        total = self.passed + len(self.failures)
        print(f"{self.name}: {self.passed}/{total} 件合格")
        for line in self.failures:
            print(f"  失敗: {line}")
        return 1 if self.failures else 0
