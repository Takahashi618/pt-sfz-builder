"""sforzando にスロットの `.sfz` を読ませる（手で試すときの入口）。

    python3.14 tools/sforzando_load.py import <スロットの置き場所>/<セッション>/slot01.sfz --track Inst1
    python3.14 tools/sforzando_load.py reload
    python3.14 tools/sforzando_load.py empty
    python3.14 tools/sforzando_load.py --dry-run import <path>
    python3.14 tools/sforzando_load.py --check

**本体は `integration/sforzando_load.py`。** アプリは `app.py --sforzando-load` で
同じものを別のプロセスとして動かす（配布版の .app は `.py` の道具をそのまま
動かせないので、本体を integration/ に移した。2026-10-25）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integration.sforzando_load import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
