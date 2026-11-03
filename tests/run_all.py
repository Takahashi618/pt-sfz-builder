"""tests/ 配下の test_*.py を順に実行し、結果をまとめる。

    python -X utf8 tests/run_all.py

各テストは独立したプロセスで走らせる。モジュールの読み込み順に依存した
「たまたま通る」状態を作らないため。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# **音も読み上げも出さず、言語は日本語にそろえる**（`_harness.py` と同じ。先に wx を読む
# テストもあるので、子のプロセスへ最初から渡しておく）。
SILENT_ENV = {"SM_SILENT": "1", "SM_NO_ANNOUNCE": "1", "SFZBUILDER_LANG": "ja"}

# 1 ファイルの上限（秒）。**上限が無いと、モーダルを開いてしまったテストで
# ビルドごと止まる**（入力を待って返らない。2026-10-25 に踏んだ）。
# いちばん長い画面のテストでも 20 秒ほどなので、十分に余裕を見る。
TIMEOUT_SEC = 300


def main() -> int:
    tests = sorted(HERE.glob("test_*.py"))
    if not tests:
        print("テストが見つかりません")
        return 1

    failed: list[str] = []
    for path in tests:
        try:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=dict(os.environ, **SILENT_ENV),
                timeout=TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            print(f"{path.stem}: {TIMEOUT_SEC} 秒で終わらなかった（モーダルを開いていないか）")
            failed.append(path.name)
            continue
        if result.stdout.strip():
            print(result.stdout.rstrip())
        if result.stderr.strip():
            print(result.stderr.rstrip())
        if result.returncode != 0:
            failed.append(path.name)

    print()
    if failed:
        print(f"失敗: {len(failed)}/{len(tests)} ファイル — {', '.join(failed)}")
        return 1
    print(f"全 {len(tests)} ファイル合格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
