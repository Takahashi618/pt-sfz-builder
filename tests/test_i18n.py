"""表示の言語（core/i18n.py）の確認。

- 言語の決め方（Mac の「優先する言語」の上から、日本語か英語の先に出るほう。
  どちらも無ければ英語）
- **ソースの文言がすべて日本語と英語の組になっていること**（ast で見る）
- 読み上げの頭の印が両方の言語でそろっていること（通知音はこの印で選ぶ）
- 借りている部品の文言が、言い換えの表で全部英語になること（部品の文言が
  変わると、英語の読み上げに日本語が混ざる）
- **英語で起動したとき、画面・メニュー・読み上げに日本語が混ざらないこと**
  （別のプロセスで英語にして集める。tests/en_probe.py。言語は起動したときに
  決まるので、このプロセスの中では切り替えられない）
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from _harness import Checker  # noqa: F401  プロジェクトの根を import パスに載せ、言語を日本語にする

from core import i18n, sibling  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JAPANESE = re.compile(r"[　-ヿ一-鿿＀-￯]")
FOLDERS = ("core", "ui", "integration")
# ほかのアプリも借りて読むファイル（言語の設定を読まない。言葉は ui/controller が言い換える）
SHARED_FILES = {"core/kinds.py", "core/notes.py"}
# 文言ではない日本語を持つ変数（部品の文言の表、.app の本当の名前、日本語のときだけ使うメニューの訳）
NOT_TEXT_NAMES = {"_PART_WORDS", "BUNDLE_NAME", "WINDOW_MENU_TITLE", "WINDOW_MENU_RULES"}
# 日本語のときだけ動く関数（アプリメニューの訳、部品が返すキーの名前の読み替え）
JAPANESE_ONLY_FUNCTIONS = {"_localize_app_menu", "part_key_label"}
# 読み上げの頭の印（日本語 → 英語）
PREFIXES = {"[エラー]": "[Error]", "[警告]": "[Warning]"}


def source_files() -> list[Path]:
    paths = [ROOT / "app.py"]
    for folder in FOLDERS:
        paths += sorted((ROOT / folder).glob("*.py"))
    return [p for p in paths if p.relative_to(ROOT).as_posix() not in SHARED_FILES]


def tr_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr":
            yield node


def _skipped_nodes(tree: ast.AST) -> set[int]:
    """文言として調べないノード。説明文と、上の変数・関数の中。"""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        ):
            skip.add(id(node.body[0].value))
        named = isinstance(node, ast.Assign) and any(getattr(t, "id", "") in NOT_TEXT_NAMES for t in node.targets)
        function = isinstance(node, ast.FunctionDef) and node.name in JAPANESE_ONLY_FUNCTIONS
        if named or function:
            skip.update(id(c) for c in ast.walk(node))
    return skip


def untranslated(path: Path, rel: str) -> list[str]:
    """tr(日本語, 英語) に入っていない日本語の文字列。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _skipped_nodes(tree)
    problems: list[str] = []
    for call in tr_calls(tree):
        ja, en = call.args
        skip.update(id(c) for c in ast.walk(ja))
        for child in ast.walk(en):
            if isinstance(child, ast.Constant) and isinstance(child.value, str) and JAPANESE.search(child.value):
                problems.append(f"{rel}:{call.lineno} 英語の側に日本語: {child.value[:40]}")
            skip.add(id(child))
    for node in ast.walk(tree):
        if (
            id(node) not in skip
            and isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and JAPANESE.search(node.value)
        ):
            problems.append(f"{rel}:{node.lineno} {node.value[:40]}")
    return problems


def _first_text(node: ast.AST) -> str:
    """文字列の先頭の決まった部分（f 文字列なら最初の差し込みの前まで）。"""
    if isinstance(node, ast.JoinedStr):
        node = node.values[0]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


class PickLanguageTest(unittest.TestCase):
    CASES = [
        (["ja-JP", "en-JP"], "ja"),
        (["en-US", "ja-JP"], "en"),
        (["en-GB"], "en"),
        (["fr-FR", "ja-JP"], "ja"),  # 日本語と英語のうち、先に出るほう
        (["fr-FR", "de-DE"], "en"),  # どちらも無ければ英語
        ([], "en"),
        (["ja_JP.UTF-8"], "ja"),  # 環境変数 LANG の書き方
        (["zh-Hans-CN", "en-CN"], "en"),
        (["Japanese_Japan"], "ja"),  # Windows のロケールの書き方
        (["English_United States"], "en"),
    ]

    def test_cases(self) -> None:
        for langs, want in self.CASES:
            with self.subTest(langs=langs):
                self.assertEqual(i18n.pick_language(langs), want)

    def test_tests_run_in_japanese(self) -> None:
        self.assertEqual(i18n.LANG, "ja")
        self.assertEqual(i18n.tr("日本語", "English"), "日本語")

    def test_plural(self) -> None:
        self.assertEqual(i18n.plural(1, "sample"), "1 sample")
        self.assertEqual(i18n.plural(0, "sample"), "0 samples")
        self.assertEqual(i18n.plural(3, "sample"), "3 samples")
        self.assertEqual(i18n.plural(1.0, "second"), "1 second")
        self.assertEqual(i18n.plural(0.08, "second"), "0.08 seconds")

    def test_sentences(self) -> None:
        self.assertEqual(i18n.sentences(["外しました", "2 件です"]), "外しました。2 件です。")

    def test_part_key_label_keeps_japanese_in_japanese(self) -> None:
        self.assertEqual(sibling.part_key_label("Cマイナー"), "Cマイナー")


class EveryStringIsPairedTest(unittest.TestCase):
    def test_no_japanese_string_outside_tr(self) -> None:
        problems: list[str] = []
        for path in source_files():
            problems += untranslated(path, path.relative_to(ROOT).as_posix())
        self.assertEqual(problems, [])

    def test_shared_files_do_not_read_the_language(self) -> None:
        """ほかのアプリも借りて読むファイルが core.i18n を読むと、借りている側で読めなくなる。"""
        for rel in SHARED_FILES:
            with self.subTest(file=rel):
                self.assertNotIn("i18n", (ROOT / rel).read_text(encoding="utf-8"))

    def test_status_prefixes_match_in_both_languages(self) -> None:
        """通知音は文言の先頭で選ぶ。英語の印を書き違えると、失敗なのに成功の音が鳴る。"""
        checked = 0
        for path in source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in tr_calls(tree):
                ja, en = (_first_text(arg) for arg in call.args)
                for ja_mark, en_mark in PREFIXES.items():
                    if ja.startswith(ja_mark):
                        checked += 1
                        self.assertTrue(en.startswith(en_mark), f"{path.name}:{call.lineno} {en[:30]}")
        self.assertGreater(checked, 10)


class PartWordsTest(unittest.TestCase):
    """借りている部品の文言が、言い換えの表で全部英語になること。"""

    MODULES = ("dsp", "splicename", "library", "prep", "keydetect", "audiofile")

    def _messages(self, path: Path) -> set[str]:
        """raise の中の文字列と、message= に渡す文字列。"""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: list[ast.AST] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                roots.append(node.exc)
            elif isinstance(node, ast.keyword) and node.arg == "message":
                roots.append(node.value)
        return {
            child.value
            for root in roots
            for child in ast.walk(root)
            if isinstance(child, ast.Constant) and isinstance(child.value, str) and JAPANESE.search(child.value)
        }

    def _check(self, path: Path) -> int:
        checked = 0
        for message in self._messages(path):
            checked += 1
            text = message
            for ja, en in sibling._PART_WORDS:
                text = text.replace(ja, en)
            self.assertIsNone(JAPANESE.search(text), f"{path.name}: {message} → {text}")
        return checked

    def test_every_message_has_english(self) -> None:
        base = sibling.find_sibling("sample_index", "ptcore/splicename.py")
        if base is None:
            self.skipTest("借りている部品が無い")
        checked = sum(self._check(base / "ptcore" / f"{m}.py") for m in self.MODULES)
        self.assertGreater(checked, 10)

    def test_shared_note_messages_have_english(self) -> None:
        self.assertGreater(self._check(ROOT / "core" / "notes.py"), 0)


def _probe() -> dict:
    env = dict(os.environ, SM_SILENT="1", SM_NO_ANNOUNCE="1")
    env[i18n.ENV_NAME] = "en"
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tests" / "en_probe.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode != 0:
        raise AssertionError(done.stderr[-2000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


class EnglishScreenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.out = _probe()

    def test_language(self) -> None:
        self.assertEqual(self.out["lang"], ["en"])

    def test_nothing_is_in_japanese(self) -> None:
        for group, texts in self.out.items():
            for text in texts:
                with self.subTest(group=group, text=text):
                    self.assertIsNone(JAPANESE.search(text))

    def test_names(self) -> None:
        self.assertEqual(self.out["window"][0], "PT SFZ Builder")
        self.assertIn("Actions", self.out["menus"])
        self.assertIn("Help", self.out["menus"])

    def test_every_group_was_collected(self) -> None:
        for group, texts in self.out.items():
            with self.subTest(group=group):
                self.assertTrue([t for t in texts if t], group)

    def test_singular_forms(self) -> None:
        """「1 samples」のような形で読まない。"""
        wrong = re.compile(
            r"\b1 (?:sample|slot|key|semitone|one-shot|prepared file|region|warning|file|megabyte|second|decibel)s\b"
        )
        for group, texts in self.out.items():
            for text in texts:
                with self.subTest(group=group, text=text):
                    self.assertIsNone(wrong.search(text))

    def test_part_message_keeps_file_names(self) -> None:
        """部品の文の中のファイル名（「マイナー」「不明」を含むもの）を書き換えない。"""
        self.assertEqual(self.out["path_kept"], ["True"])

    def test_key_labels(self) -> None:
        self.assertEqual(self.out["key_labels"], ["C minor", "F# major", "A", "unknown"])

    def test_notes_name_the_real_mapping(self) -> None:
        """core/assign.py の案内は ui を読めないので、配置の名前を文字で書いている。ずれたら気づく。"""
        phrase_label = self.out["labels"][2]
        self.assertIn(phrase_label, (ROOT / "core" / "assign.py").read_text(encoding="utf-8"))

    def test_sentences_are_spaced(self) -> None:
        """日本語は文を詰めて並べるので、英語でも詰めたままになりやすい（「done.Next」）。"""
        joined = re.compile(r"[a-z]\.[A-Z]")
        for group, texts in self.out.items():
            for text in texts:
                with self.subTest(group=group, text=text):
                    self.assertIsNone(joined.search(text))


if __name__ == "__main__":
    unittest.main()
