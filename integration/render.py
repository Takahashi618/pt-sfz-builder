"""フレーズの下ごしらえを実行する。**計画は `core/phrase.py` が立てている。**

音程ごとに長さを変えたファイルを作る。伸縮そのものは
借りている部品の `ptcore/dsp.py` に任せる（ffmpeg か rubberband を選び、
**音程を変えずに**長さだけ変える）。`core/rootkey.py` が `splicename` を
借りているのと同じ考え方で、**見つからなくても落ちない。**

### 作り直さない

ファイル名は「元のパス＋半音数」から決まるので、同じ素材を同じ音程へ
割り当て直しても**すでにあるものは作らない。** 25 個作るのに数秒かかるため、
ここを省けるかどうかで使い心地が変わる。

**元のファイルが新しくなっていたら作り直す。** 素材を差し替えたのに
古い下ごしらえを使い続けると、鳴る音と画面の表示が食い違う。

### 進み具合を伝える

**読み上げ利用者には「処理中」の視覚的な手掛かりが無い。**
`progress` を渡すと 1 件ごとに呼ぶので、呼び出し側が伝えられる。

### Finder から開くと ffmpeg が見つからない（2026-10-25 のレビューで直した）

`.app` を Finder から開くと、PATH は `/usr/bin:/bin:/usr/sbin:/sbin` だけになる。
伸縮の道具は `shutil.which` で探すので、**Homebrew の ffmpeg が入っていても
「入っていない」と判断され、「速さを保つ」とテンポ合わせが必ず失敗していた**
（「素材に合わせる」はループをこの配置にするので、ループは 1 つも割り当てられない）。
端末から起動すると PATH を引き継ぐので気づきにくい。道具を探す前に
`ensure_tool_path` で Homebrew の場所を足す（作者の別のアプリと同じ）。
"""

from __future__ import annotations

from core.i18n import COMMA, plural, tr

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from core.sibling import load_ptcore, part_message

__all__ = [
    "TOOL_DIRS",
    "RenderResult",
    "CleanResult",
    "ensure_tool_path",
    "render_phrase",
    "backend_name",
    "find_unused",
    "clean_rendered",
]

ProgressFn = Callable[[int, int, str], None]

# 同時に走らせる伸縮の数。**控えめにする。**
# Pro Tools が再生している最中に呼ばれることがあるので、
# CPU を占有すると音が途切れる。
_MAX_WORKERS = 4

# 伸縮の道具（ffmpeg・rubberband）を探す場所。Homebrew の既定の置き場所
TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


def ensure_tool_path(dirs: Sequence[str] = TOOL_DIRS) -> list[str]:
    """PATH に Homebrew の場所が無ければ足す（このプロセスの中だけ）。足した場所を返す。

    **実在する場所だけを、後ろに足す。** 利用者が PATH で決めた順を崩さない。
    """
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    added = [d for d in dirs if d not in parts and os.path.isdir(d)]
    if added:
        os.environ["PATH"] = os.pathsep.join(parts + added)
    return added


@dataclass
class RenderResult:
    """下ごしらえの結果。**失敗しても例外は投げない。**"""

    ok: bool
    made: int = 0
    skipped: int = 0
    # 元のファイルをそのまま使う件数。**「作り直していない」とは別物。**
    # 一緒に数えると、キャッシュが効いたのか加工が要らなかったのかを
    # 聞き分けられない。
    untouched: int = 0
    failures: list[str] = field(default_factory=list)
    message_ja: str = ""

    def describe_ja(self) -> str:
        if not self.ok:
            return self.message_ja
        parts = []
        if self.made:
            parts.append(tr(f"{self.made}個を作りました", f"Made {self.made}"))
        if self.skipped:
            parts.append(tr(f"{self.skipped}個は作り直していません", f"{self.skipped} not remade"))
        if self.untouched:
            parts.append(tr(
                f"{self.untouched}個は元のファイルをそのまま使います",
                f"{self.untouched} using the original file as is",
            ))
        return COMMA.join(parts) + tr("。", ".") if parts else tr(
            "下ごしらえは要りませんでした。",
            "No prepared files were needed.",
        )


def _load_dsp():
    """借りている部品の `ptcore/dsp.py` を遅延読み込みする。失敗したら None。

    **道具を探す前に PATH を整える**（Finder から開いたとき。モジュールの説明）。
    """
    ensure_tool_path()
    return load_ptcore("dsp")


def backend_name() -> str:
    """使える伸縮の道具。無ければ空文字。"""
    dsp = _load_dsp()
    if dsp is None:
        return ""
    try:
        return dsp.choose_backend().name
    except Exception:
        return ""


def _untouched(item) -> bool:
    """加工が要らない項目か。**出力先が入力と同じなら必ず True。**

    `PhraseRender` / `StretchRender` は `is_original` を持っているが、
    型で縛らない方針なので、**パスの一致でも判断する。**
    ここを取りこぼすと元の素材を壊す。
    """
    if getattr(item, "is_original", False):
        return True
    return os.path.abspath(item.dest) == os.path.abspath(item.source)


def _is_fresh(dest: str, source: str) -> bool:
    """すでにある下ごしらえが使えるか。

    **元のファイルより新しいこと**を条件にする。素材を差し替えたのに
    古い下ごしらえを使うと、鳴る音と画面の表示が食い違う。
    """
    try:
        if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            return False
        return os.path.getmtime(dest) >= os.path.getmtime(source)
    except OSError:
        return False


def render_phrase(
    renders: Sequence,
    *,
    progress: ProgressFn | None = None,
    force: bool = False,
) -> RenderResult:
    """計画どおりにファイルを作る。

    `renders` は `core/phrase.PhraseRender` の並び。型で縛らないのは、
    integration が core の細部に寄りかからないようにするため。

    **1 件でも失敗したら ok=False。** 欠けた鍵盤があると、そこだけ
    無音になって原因が分かりにくい。
    """
    # **元のファイルをそのまま指す項目は、何があっても触らない。**
    # 出力先が入力と同じなので、加工すると利用者の Splice 素材そのものを
    # 上書きしてしまう（ffmpeg は `-y` で入力を先に切り詰める）。
    # `force` でも例外にしない。作り直したいのは下ごしらえであって、
    # 元の素材ではない。
    work = [item for item in renders if not _untouched(item)]
    untouched = len(renders) - len(work)

    if not work:
        # **伸縮の道具が無くても、ここまでは進める。**
        return RenderResult(True, untouched=untouched)

    dsp = _load_dsp()
    if dsp is None:
        return RenderResult(
            False,
            untouched=untouched,
            message_ja=tr(
                "[エラー] 伸縮の道具が見つかりません。"
                "借りている部品が見つからないため、速さを保つ配置は使えません。",
                "[Error] The stretching tool was not found. A borrowed part is missing, so the "
                "keep-speed mapping cannot be used.",
            ),
        )
    if not backend_name():
        return RenderResult(
            False,
            untouched=untouched,
            message_ja=tr(
                "[エラー] ffmpeg も rubberband も入っていません。"
                "どちらかを入れると、速さを保つ配置が使えます。",
                "[Error] Neither ffmpeg nor rubberband is installed. Install either one to use "
                "the keep-speed mapping.",
            ),
        )

    total = len(work)
    made = 0
    skipped = 0
    done = 0
    lock = threading.Lock()
    # 並び順を保つ。**失敗の 1 件目を読み上げる**ので、
    # 終わった順に並べると毎回違う鍵盤の名前が出てしまう。
    results: list[str | None] = [None] * total

    def run(index: int, item) -> None:
        nonlocal made, skipped, done
        if not force and _is_fresh(item.dest, item.source):
            with lock:
                skipped += 1
                done += 1
                count = done
            if progress is not None:
                progress(count, total, item.dest)
            return
        try:
            # **置き場所を作るのも try の中。** 外へ出すと、外付けドライブが
            # 繋がっていないときなどに生の OSError が UI まで素通りし、
            # 読み上げ無しで落ちる（`.sfz` の書き込み側とそろえる）。
            os.makedirs(os.path.dirname(item.dest) or ".", exist_ok=True)
            outcome = dsp.process(
                item.source,
                item.dest,
                semitones=0.0,  # **音程は変えない。** 変えるのは長さだけ
                tempo_ratio=item.tempo_ratio,
            )
        except Exception as exc:  # dsp 側の想定外・置き場所が作れない
            results[index] = f"{os.path.basename(item.dest)}: {exc}"
        else:
            if outcome.ok:
                with lock:
                    made += 1
            else:
                results[index] = (
                    tr(
                        f"{os.path.basename(item.dest)}: "
                        f"{outcome.message or '理由不明'}",
                        f"{os.path.basename(item.dest)}: "
                        f"{part_message(outcome.message) if outcome.message else 'unknown reason'}",
                    )
                )
        with lock:
            done += 1
            count = done
        if progress is not None:
            progress(count, total, item.dest)

    # **同時に流す。** 1 件ずつだと 25 個で 1 秒近く UI が止まる
    # （rubberband を入れると数十秒になる）。実体は ffmpeg の別プロセスなので
    # GIL は関係ない。**同時数は控えめに。** 上げすぎると Pro Tools の
    # 再生に影響する。
    workers = max(1, min(_MAX_WORKERS, total))
    if workers == 1:
        for index, item in enumerate(work):
            run(index, item)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda pair: run(*pair), list(enumerate(work))))

    failures = [text for text in results if text]

    if failures:
        head = failures[0]
        rest = tr(
            f"ほか{len(failures) - 1}件",
            f" and {len(failures) - 1} more",
        ) if len(failures) > 1 else ""
        return RenderResult(
            False,
            made=made,
            skipped=skipped,
            untouched=untouched,
            failures=failures,
            message_ja=tr(
                f"[エラー] 下ごしらえに失敗しました。{head}{rest}",
                f"[Error] Preparing the files failed. {head}{rest}",
            ),
        )
    return RenderResult(True, made=made, skipped=skipped, untouched=untouched)


# --------------------------------------------------------------------------
# 片付け
# --------------------------------------------------------------------------


@dataclass
class CleanResult:
    """片付けの結果。**消す前に一覧を読み上げられるようにしてある。**"""

    ok: bool
    paths: list[str] = field(default_factory=list)
    removed: int = 0
    freed_bytes: int = 0
    message_ja: str = ""

    def describe_ja(self) -> str:
        if not self.ok:
            return self.message_ja
        if not self.paths:
            return tr("片付けるものはありませんでした。", "There was nothing to clean up.")
        mb = self.freed_bytes / (1024 * 1024)
        if self.removed:
            return tr(
                f"{self.removed}個を消しました。{mb:.0f} メガバイト空きました。",
                f"Deleted {self.removed}, freeing {plural(round(mb), 'megabyte')}.",
            )
        return tr(
            f"{len(self.paths)}個、{mb:.0f} メガバイトが使われていません。",
            f"{plural(len(self.paths), 'file')}, {plural(round(mb), 'megabyte')}, not in use.",
        )


def find_unused(slots_dir: str) -> CleanResult:
    """どのスロットからも参照されていない下ごしらえを挙げる。**消さない。**

    いまある `.sfz` を読み戻して、参照されているパスを集める
    （`core/sfz.parse` が使える形で書いてある）。
    **読めない `.sfz` が 1 つでもあれば中止する。** 参照を取りこぼすと、
    まだ要るファイルを消してしまう。

    **すべてのセッションの `.sfz` を見る。** スロットはセッションごとの
    フォルダに分かれているが、下ごしらえは共有なので、いま開いている
    セッションの分だけを見ると**別のセッションが使っているファイルを
    「使っていない」と判断して消してしまう。**
    """
    from core.phrase import RENDER_DIR_NAME, unused_renders
    from core.sfz import parse

    base = Path(slots_dir)
    render_dir = base / RENDER_DIR_NAME
    if not render_dir.is_dir():
        return CleanResult(True, message_ja=tr(
            "下ごしらえの置き場所がありません。",
            "There is no folder for prepared files.",
        ))

    referenced: set[str] = set()
    for sfz in sorted(base.glob("*.sfz")) + sorted(base.glob("*/*.sfz")):
        try:
            doc = parse(sfz.read_text(encoding="utf-8"))
        except Exception as exc:
            return CleanResult(
                False,
                message_ja=tr(
                    f"[警告] {sfz.name} を読めませんでした。"
                    f"参照を取りこぼすと要るファイルを消すので中止します。{exc}",
                    f"[Warning] Could not read {sfz.name}. Stopping, because missing a reference "
                    f"would delete a file that is needed. {exc}",
                ),
            )
        referenced.update(region.sample for region in doc.regions)

    present = [str(p) for p in sorted(render_dir.glob("*.wav"))]
    unused = unused_renders(referenced, present)
    total = 0
    for path in unused:
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return CleanResult(True, paths=unused, freed_bytes=total)


def clean_rendered(
    slots_dir: str, *, paths: Sequence[str] | None = None
) -> CleanResult:
    """使われていない下ごしらえを消す。

    **`find_unused` で挙げたものだけを消す。** 置き場所ごと消さない
    （いま鳴っているスロットのファイルまで巻き込む）。

    `paths` を渡すと、**読み上げて確認を取った一覧の中だけから消す。**
    渡さないと数え直すことになり、確認の前後で `.sfz` が書き換わったとき
    「言った数と消える数が違う」ことが起きる。

    **ただし、消す直前にもう一度数える。** 確認した一覧のうち、その間に
    どれかのスロットが使い始めたもの（別のセッションの割り当て・
    別に開いていたこのアプリ）は消さない。言った数より少なくなることは
    あっても、**使っているファイルを消すことは無い。** 数えられなければ
    （読めない `.sfz` がある）何も消さない。
    """
    found = find_unused(slots_dir)
    if not found.ok:
        return found
    if paths is not None:
        unused_now = set(found.paths)
        found = CleanResult(True, paths=[p for p in paths if p in unused_now])
    if not found.paths:
        return found

    removed = 0
    freed = 0
    for path in found.paths:
        try:
            size = os.path.getsize(path)
            os.remove(path)
        except OSError:
            continue
        removed += 1
        freed += size
    return CleanResult(True, paths=found.paths, removed=removed, freed_bytes=freed)
