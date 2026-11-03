"""sforzando のログを読んで、**いま何が読み込まれているか**を知る。

2026-09-04 に見つけた。sforzando は状態の変化をログに書く。
**画面を撮らずに、機械的に検証できる。**

    ~/Library/Application Support/Plogue/Aria/AriaEnginePro Tools.log

    I:8471126720:16359360265:islot:0 slot01.sfz was externally modified! Reloading...
    I:8471126720:16359361008:0x401e48000 SFZInstrument::setFile(/…/slot01.sfz)
    I:8471126720:16359361586:SourceManager rem:/…/testtones/sine.wav
    I:8471126720:16359361832:SourceManager add:/…/testtones/square.wav
    I:8471126720:16359361973:0x401e48000 instrument: regions:1 * 3176 = 3176

書式は `<レベル>:<スレッド>:<時刻>:<本文>`。レベルは `I`（情報）、
`W`（警告）、`E`（エラー）。

### サンプルが見つからないと `E:` で出る（実運用で必ず起きる）

    E:…:PLAF::Factory::open() file not found:/…/testtones/存在しない.wav
    E:…:PROC_INIT_RESULT:3

**どのファイルが無いかまで書いてある。** 素材を移動・削除されたときに、
「音が出ない」ではなく「このファイルが見つかりません」と言える。

さらに `PARSELOG DUMP` の間に、**人が読める形の失敗理由**が入る。

    E:…:****PARSELOG DUMP+****
    No sound asset loaded
    Not Found:
     /…/testtones/存在しない.wav
    E:…:****PARSELOG DUMP-****

### 状態は「最後の読み込み」で数え直す

ログは追記されるので、**素朴に全体を集計すると古い値が混ざる。**
`SFZInstrument::setFile(...)` が読み込みの開始なので、**そこで一度
リセットしてから数え直す。** そうしないと、失敗した読み込みのあとに
前回のリージョン数が残り、成功したように見えてしまう。

エラーも同じ理由でリセットする。**直したあとに古いエラーが出続けると、
直ったのかどうかが分からなくなる。** 警告（`W:`）は起動時のものが
ほとんどで読み込みとは無関係なので、こちらは通しで持つ。

### 監視は `empty` で止まる

スロットを空にすると、フォルダの監視も止まる。

    Engine::onCTRLCommand (0,2,35,empty,,0)
    stopping FolderWatcher

つまり**監視は「何か読み込んでいる間だけ」効く。** 空にしたスロットへ
書き込んでも反映されない。もう一度 `import` が要る。

音色そのものも捨てられる（`SFZInstrument::~SFZInstrument()`）ので、
そこで読み取り側の状態も捨てる。**残しておくと「8 リージョン載っている」と
言い続けることになる。**

### すでに載っているサンプルは載せ直さない

**`SourceManager wiping:N` が「何個外したか」を表す。** ここが正。

    SourceManager wiping:0     ← 何も外していない。前のものはそのまま残る
    SourceManager adding:53    ← 53 個を足した

読み直した結果に前と同じサンプルが含まれていると、その分は載せ直さず
`add:` も出ない。**読み込みのたびに一覧を捨てると、その分を取りこぼす。**

2026-09-04 に 2 通りの形で踏んだ。

| 場面 | ログ | 素朴に捨てた場合 |
| --- | --- | --- |
| 全部同じ | `wiping:0` / `adding:0` | 「1 個も載っていない」と誤報告 |
| 8 個が同じで 53 個を追加 | `wiping:0` / `adding:53` | 8 個を取りこぼす |

そこで**サンプルの一覧は読み込みをまたいで持ち、`wiping:N` で減らす。**
`N` が今の件数以上なら全部外れたとみなす。**行が混ざって `rem:` が
1 本消えても、件数で判断できるので取りこぼさない。**

リージョン数やエラーは読み込みごとの値なので、こちらは捨ててよい。

### 行が壊れることがある

**複数のスレッドが同時に書くので、行が混ざる。** 実際にこういう行が出た。

    10567838805:SourceManager rem:I:13524856832:I:Streamer::doCloseFile:…

そのため**行の形を厳密に決めつけない。** 本文に目印が含まれていれば拾う、
という寛容な読み方にする。厳密に構文解析すると、混ざった行で落ちる。

### 日本語のコメントは「バイナリ」と疑われるが通る

生成する SFZ には日本語のコメントが入る。sforzando の文字コード判定は
まず高位バイトを見て `Binary detected!` と言い、そのあと
`brute force detected UTF-8!` で正しく読み直す。**結果として通る**が、
判定に頼っている以上、いつか外れうる。ログで見張れるようにしておく。

### インスタンスが複数あっても 1 本のログを共有する

sforzando を 2 つ挿すと、**どちらも同じログファイルに書く。**
見分ける手掛かりは 2 つあるが、使えるのは片方だけ。

| 手掛かり | 使えるか |
| --- | --- |
| `islot:0` | **使えない。** どのインスタンスも 0（1 インスタンス 1 スロットのため） |
| `SFZInstrument::setFile(<パス>)` | **使える。** スロットごとにファイルが違う |
| オブジェクトのアドレス（`0x467a68000`） | 使えるが、トラックとの対応が付かない |

**`.sfz` のパスで分ける。** 本設計はスロットごとに固定のパスを使うので、
これがそのままスロットの識別子になる（`parse_by_file`）。

2026-09-04 に 2 インスタンスで確認した。**片方を書き換えても、
もう片方は反応しない。** 監視は同じフォルダに対して 2 本走るが、
自分が読んでいるファイルの変更にだけ反応する。

    islot:0 slot02.sfz was externally modified! Reloading...
    0x467a68000 SFZInstrument::setFile(/…/slot02.sfz)   ← Inst2 だけ

**ただしサンプルの管理はインスタンスをまたいで共有されている。**
別のインスタンスが既に読んでいるファイルは、`add:` が出ない。

    SourceManager wiping:61
    SourceManager rem: …（61 本）
    instrument: regions:1        ← 1 個載ったのに add: が無い
                                    （noise.wav は隣のインスタンスが保持していた）

そのため**スロットごとのサンプル一覧は当てにならないことがある。**
リージョン数は各インスタンスの値なので信用してよい。
「一覧が取れない」と「載っていない」を混同しないこと
（`samples_unknown`）。

OS 非依存。ファイルを読んで文字列を解釈するだけなので Windows でもテストできる。
"""

from __future__ import annotations

from core.i18n import COMMA, plural, sentences, tr

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "LOG_PATH",
    "NAMES_IN_SUMMARY",
    "SforzandoState",
    "parse_log",
    "parse_by_file",
    "read_state",
    "read_states",
]

LOG_PATH = (
    Path.home()
    / "Library/Application Support/Plogue/Aria/AriaEnginePro Tools.log"
)

# 読み上げに並べるファイル名の数。**全部読ませない。**
# ドラムキットは 61 個になることがあり、そのまま読ませると
# 名前だけで何分もかかる。数が分かれば足りる。
NAMES_IN_SUMMARY = 3

# 目印。**行の先頭からではなく、本文のどこにあっても拾う**（行が混ざるため）。
_SET_FILE = re.compile(r"SFZInstrument::setFile\(([^)]*)\)")
_ADD = re.compile(r"SourceManager add:(\S.*?)(?=\s*(?:[IWE]:\d|$))")
_REM = re.compile(r"SourceManager rem:(\S.*?)(?=\s*(?:[IWE]:\d|$))")
_REGIONS = re.compile(r"instrument:\s*regions:(\d+)")
_WATCH = re.compile(r"FolderWatcher start for \*(.*?)\*")
_WATCH_STOP = re.compile(r"stopping FolderWatcher")
# スロットを空にすると音色が破棄される。**ここで状態を捨てる。**
_DESTROYED = re.compile(r"SFZInstrument::~SFZInstrument")
_NOT_FOUND = re.compile(r"file not found:(\S.*?)(?=\s*(?:[IWE]:\d|$))")
_DUMP_BEGIN = re.compile(r"PARSELOG DUMP\+")
_DUMP_END = re.compile(r"PARSELOG DUMP-")
# 「何個外したか」。**サンプル一覧の増減はここを正とする。**
_WIPING = re.compile(r"SourceManager wiping:(\d+)")
_RELOADED = re.compile(r"was externally modified! Reloading")
_BINARY = re.compile(r"Binary detected!")


@dataclass
class SforzandoState:
    """ログから読み取れた、いまの状態。

    **どれも「ログにそう書いてあった」以上の意味は無い。**
    プラグインに問い合わせているわけではないので、ログが切り詰められて
    いれば取りこぼす。分からないものは None / 空にする。
    """

    sfz_path: str | None = None
    samples: list[str] = field(default_factory=list)
    regions: int | None = None
    watched_dir: str | None = None
    reload_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing_samples: list[str] = field(default_factory=list)
    parse_report: str = ""
    watching: bool = False
    emptied: bool = False
    encoding_guessed: bool = False

    @property
    def samples_unknown(self) -> bool:
        """**載っているはずなのに一覧が取れていない**か。

        別のインスタンスが同じファイルを既に保持していると `add:` が
        出ないため、リージョンはあるのに一覧が空になる。
        **これを「載っていない」と言ってはいけない。**
        """
        return (
            self.regions is not None
            and self.regions > 0
            and not self.samples
            and not self.has_problem
        )

    @property
    def has_problem(self) -> bool:
        """読み込みに失敗しているか。**警告は含めない。**

        Scala のスケールが無いといった警告は常に出ていて、音には関係ない。
        これを問題として扱うと、本当の失敗が埋もれる。
        """
        return bool(self.missing_samples) or bool(self.parse_report)

    def describe_ja(self) -> str:
        """読み上げ用。**分からないことは分からないと言う。**"""
        if self.sfz_path is None:
            # **「分からない」と「空」は違う。** 空だと分かっているなら、
            # 何をすれば使えるようになるかまで言う。
            if self.emptied:
                return tr(
                    "スロットは空です。**監視は止まっています**"
                    "（書き換えても反映されません）。読み込み直しが要ります。",
                    "The slot is empty. **Watching has stopped** (changes will not apply). It "
                    "needs to be loaded again.",
                )
            return tr(
                "sforzando が何を読んでいるかは、ログからは分かりませんでした。",
                "The log does not show what sforzando is reading.",
            )
        lines = [tr(
            f"読み込み中: {Path(self.sfz_path).name}",
            f"Reading: {Path(self.sfz_path).name}",
        )]
        if self.regions is not None:
            lines.append(tr(f"リージョン {self.regions} 個", plural(self.regions, "region")))
        if self.samples:
            shown = [Path(s).name for s in self.samples[:NAMES_IN_SUMMARY]]
            names = COMMA.join(shown)
            rest = len(self.samples) - len(shown)
            if rest > 0:
                names += tr(f" ほか {rest} 個", f" and {rest} more")
            lines.append(tr(
                f"サンプル {len(self.samples)} 個（{names}）",
                f"{plural(len(self.samples), 'sample')} ({names})",
            ))
        elif self.samples_unknown:
            lines.append(
                tr(
                    "サンプルの一覧は取れませんでした"
                    "（ほかのインスタンスと共有されているため）",
                    "The sample list could not be read (it is shared with another instance)",
                )
            )
        else:
            lines.append(tr("サンプルは読み込まれていません", "No samples are loaded"))
        if self.watched_dir and self.watching:
            lines.append(tr(f"監視中: {self.watched_dir}", f"Watching: {self.watched_dir}"))
        elif self.watched_dir:
            lines.append(tr(
                "**監視は止まっています**（書き換えても反映されません）",
                "**Watching has stopped** (changes will not apply)",
            ))
        if self.reload_count:
            lines.append(tr(
                f"自動で読み直した回数: {self.reload_count}",
                f"Automatic reloads: {self.reload_count}",
            ))
        if self.missing_samples:
            names = COMMA.join(Path(s).name for s in self.missing_samples)
            lines.append(tr(
                f"**見つからないサンプルがあります**（{names}）",
                f"**Some samples were not found** ({names})",
            ))
        elif self.parse_report:
            head = self.parse_report.splitlines()[0] if self.parse_report else ""
            lines.append(tr(
                f"**読み込みに失敗しています**（{head}）",
                f"**Loading failed** ({head})",
            ))
        if self.warnings:
            lines.append(tr(f"警告 {len(self.warnings)} 件", plural(len(self.warnings), "warning")))
        return sentences(lines)


def parse_log(text: str) -> SforzandoState:
    """ログ全体から状態を組み立てる。**純粋関数。**

    `SourceManager add:` と `rem:` を順に追って、いま載っているものを求める。
    同じファイルが何度も add されうるので、重複は持たない。
    """
    state = SforzandoState()
    samples: list[str] = []
    in_dump = False
    dump: list[str] = []

    for raw in text.splitlines():
        line = raw.rstrip()

        # PARSELOG DUMP の中は、素の文章がそのまま入る。**行の形が違う。**
        if _DUMP_END.search(line):
            in_dump = False
            state.parse_report = "\n".join(
                item for item in (d.strip() for d in dump) if item
            )
            continue
        if in_dump:
            dump.append(line)
            continue
        if _DUMP_BEGIN.search(line):
            in_dump = True
            dump = []
            continue

        if not line:
            continue

        found = _SET_FILE.search(line)
        if found:
            # **読み込みの開始。ここで数え直す。**
            # そうしないと、失敗した読み込みのあとに前回の値が残る。
            # **読み込みの開始。読み込みごとの値だけ捨てる。**
            # サンプルの一覧は捨てない。前の分が残ることがあるため。
            state.sfz_path = found.group(1).strip() or None
            state.emptied = False
            state.regions = None
            state.missing_samples = []
            state.parse_report = ""
            state.errors = []

        found = _WIPING.search(line)
        if found and int(found.group(1)) >= len(samples):
            # 今載っている分が全部外れた。**個別の rem: を待たない。**
            # 行が混ざって rem: が消えることがあるので、件数で判断する。
            samples = []

        for match in _REM.finditer(line):
            path = match.group(1).strip()
            if path in samples:
                samples.remove(path)

        for match in _ADD.finditer(line):
            path = match.group(1).strip()
            if path and path not in samples:
                samples.append(path)

        found = _REGIONS.search(line)
        if found:
            state.regions = int(found.group(1))

        found = _WATCH.search(line)
        if found:
            state.watched_dir = found.group(1).strip() or None
            state.watching = True

        if _WATCH_STOP.search(line):
            state.watching = False

        if _DESTROYED.search(line):
            # 音色が捨てられた。**載っているものは何も無い。**
            state.emptied = True
            state.sfz_path = None
            state.regions = None
            state.missing_samples = []
            state.parse_report = ""
            samples = []

        if _RELOADED.search(line):
            state.reload_count += 1

        if _BINARY.search(line):
            state.encoding_guessed = True

        for match in _NOT_FOUND.finditer(line):
            path = match.group(1).strip()
            if path and path not in state.missing_samples:
                state.missing_samples.append(path)

        if line.startswith("W:"):
            state.warnings.append(line)
        elif line.startswith("E:"):
            state.errors.append(line)

    state.samples = samples
    return state


def parse_by_file(text: str) -> dict[str, SforzandoState]:
    """`.sfz` のパスごとに状態を組み立てる。**複数スロット用。**

    ログを `SFZInstrument::setFile(...)` で区切り、同じパスの区間だけを
    集めて解釈し直す。**解釈そのものは `parse_log` を使い回す**ので、
    片方だけ挙動が食い違うことがない。

    最初の区切りより前の行（起動時の警告など）はどのスロットのものとも
    言えないので、**すべてのスロットに配る。** 警告はそこにしか無い。

    ### 捨てられたところで区間を閉じる

    `~SFZInstrument`（音色が捨てられた）以降の行は、**次の `setFile` まで
    どのスロットのものでもない。** ここを閉じずに次の `setFile` まで
    前のスロットへ入れていたときは、**別のインスタンスが出す
    「FolderWatcher start」を、空にしたスロットの監視再開と読み違えていた**
    （sforzando は import のとき `setFile` より先に監視を始める）。

    その結果 `needs_loading()` が False になり、「プラグインに読み込ませる」
    が「いまは必要ありません」と名乗るのに、実際の監視は止まっていて
    次の割り当てが永久に反映されない、という状態になっていた。

    閉じているあいだの行は**次の `setFile` の区間へ回す。** 捨てるのでは
    なく回すのは、監視開始が `setFile` の直前に出るため。回さないと、
    入れ直したスロットが「監視されていない」に見える（安全側ではあるが、
    毎回押させることになる）。
    """
    lines = (text or "").splitlines(keepends=True)
    preamble: list[str] = []
    segments: dict[str, list[str]] = {}
    current: str | None = None
    started = False
    # 区間の外に出た行。次の `setFile` の頭へ付ける。
    pending: list[str] = []

    for line in lines:
        found = _SET_FILE.search(line)
        if found:
            current = found.group(1).strip() or None
            if current:
                started = True
                segments.setdefault(current, []).extend(pending)
            pending = []
        if current is None:
            # 最初の setFile より前だけが前置き。捨てられたあとの行は
            # **どのスロットのものとも言えない**ので、次の区間へ回す。
            (preamble if not started else pending).append(line)
            continue
        segments[current].append(line)
        if _DESTROYED.search(line):
            current = None

    head = "".join(preamble)
    return {
        path: parse_log(head + "".join(body)) for path, body in segments.items()
    }


def read_state(path: str | Path | None = None) -> SforzandoState | None:
    """実物のログを読む。無ければ None。

    **インスタンスが複数あると、最後に触られたものの状態になる。**
    スロットごとに知りたいときは `read_states()` を使う。
    """
    target = Path(path) if path else LOG_PATH
    if not target.is_file():
        return None
    return parse_log(target.read_text(encoding="utf-8", errors="replace"))


# 直前に読んだログ。**割り当てのたびに全体を読み直さない。**
# 実測で 208 KB / 2372 行に 5 ミリ秒ほどかかり、ログは追記され続ける。
# 鍵は (パス, 大きさ, 更新時刻)。どれかが変われば読み直す。
_states_cache: tuple[tuple[str, int, float], dict[str, "SforzandoState"]] | None = None


def read_states(path: str | Path | None = None) -> dict[str, SforzandoState] | None:
    """実物のログを `.sfz` のパスごとに読む。無ければ None。

    **同じ内容なら前の結果を返す。** ログは追記され続けるので、
    割り当てや読み込みのたびに全体を読み直すと、UI を止める時間が
    じわじわ延びる。
    """
    global _states_cache
    target = Path(path) if path else LOG_PATH
    try:
        stat = target.stat()
    except OSError:
        return None
    if not target.is_file():
        return None

    key = (str(target), stat.st_size, stat.st_mtime)
    if _states_cache is not None and _states_cache[0] == key:
        return _states_cache[1]

    states = parse_by_file(target.read_text(encoding="utf-8", errors="replace"))
    _states_cache = (key, states)
    return states
