"""ファイルを壊さずに書き換える。

書きかけの `.sfz` をプラグインに読まれると、鍵盤を弾いても無音になったり
エラーが出たりする。**一時ファイルへ全部書いてから差し替える**ことで、
読み手からは「古い内容」か「新しい内容」のどちらかしか見えないようにする。

`os.replace()` は同じファイルシステム内であれば差し替えを原子的に行う。
一時ファイルを**書き込み先と同じディレクトリに作る**のはそのため。
`/tmp` などに作るとボリュームをまたいで失敗することがある。

改行は **LF に固定**する。実行環境によって中身が変わらないようにしておく。
"""

from __future__ import annotations

from .i18n import tr

import os
import tempfile
from pathlib import Path

__all__ = ["write_atomic", "read_text"]


def write_atomic(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """`path` に `text` を書く。途中の状態が見えないようにする。

    親ディレクトリが無ければ作る。書き込みに失敗したときは一時ファイルを
    片付けたうえで例外を投げ直す。**元のファイルはそのまま残る。**

    Returns:
        書き込んだファイルのパス。
    """
    if not isinstance(text, str):
        raise TypeError(tr(
            f"text は文字列にしてください: {type(text).__name__}",
            f"text must be a string: {type(text).__name__}",
        ))

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 同じディレクトリに作る。os.replace が原子的に働く条件。
    # 先頭のドットは、作業中のファイルが一覧に紛れ込みにくくするため。
    handle_fd, temporary_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(handle_fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            # ディスクまで届かせてから差し替える。電源断で空ファイルが残るのを避ける。
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        # KeyboardInterrupt でも後片付けしたいので BaseException で受ける。
        temporary.unlink(missing_ok=True)
        raise

    return target


def read_text(path: str | Path, *, encoding: str = "utf-8") -> str:
    """書いた内容を読み戻す。検証用。

    改行は LF で書いているので、そのまま読めば元の文字列に戻る。
    """
    return Path(path).read_text(encoding=encoding)
