"""tools/*.applescript が構文として通るか。**動かさない。**

AppleScript を使う部分のテストは全部スタブを注入しているので、
スクリプトそのものの書き間違いはテストでは捕まらなかった（実機で初めて分かる）。
`osacompile` で組み立てるだけなら、Pro Tools にも System Events にも触らない。

macOS でだけ確かめる（Windows では osacompile が無い）。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from _harness import Checker

c = Checker("applescripts")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
scripts = sorted(TOOLS.glob("*.applescript"))

if sys.platform == "darwin":
    c.check("スクリプトがある", len(scripts) >= 5, str(len(scripts)))
    with tempfile.TemporaryDirectory() as tmp:
        for script in scripts:
            done = subprocess.run(
                ["osacompile", "-o", str(Path(tmp) / f"{script.stem}.scpt"), str(script)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            c.check(
                f"{script.name} が構文として通る",
                done.returncode == 0,
                (done.stderr or done.stdout).strip(),
            )
else:
    c.check("macOS 以外では確かめない", True)

raise SystemExit(c.summary())
