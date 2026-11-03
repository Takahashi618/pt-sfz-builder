"""sforzando_log.py のテスト。

**実物のログは読まない。** 2026-09-04 に採れた実際の断片を文字列として
埋め込み、そこから状態を組み立てられることを確かめる。
実機が無くても全経路を通せる。
"""

from pathlib import Path

from _harness import Checker

from integration.sforzando_log import (
    NAMES_IN_SUMMARY,
    SforzandoState,
    parse_by_file,
    parse_log,
    read_states,
)

c = Checker("sforzando_log")

# 実機のログから採った断片。**行はそのまま。**
REAL = """\
I:8471126720:10340407572:starting FolderWatcher
I:8471126720:10340407575:FolderWatcher start for */Volumes/Audio/sfz_slots*
I:8471126720:16359360265:islot:0 slot01.sfz was externally modified! Reloading...
I:8471126720:16359360320:ISlotDetails::reload()
I:8471126720:16359361008:0x401e48000 SFZInstrument::setFile(/Volumes/Audio/sfz_slots/slot01.sfz)
I:8471126720:16359361586:SourceManager rem:/Volumes/Audio/sfz_slots/testtones/sine.wav
I:8471126720:16359361832:SourceManager add:/Volumes/Audio/sfz_slots/testtones/square.wav
I:8471126720:16359361973:0x401e48000 instrument: regions:1 * 3176 = 3176
W:8471126720:9727730069:Scala open() /Library/.../Scales/01 - equal.scl cannot be found!
"""

state = parse_log(REAL)
c.equal(
    "読んでいる SFZ",
    state.sfz_path,
    "/Volumes/Audio/sfz_slots/slot01.sfz",
)
c.equal("リージョン数", state.regions, 1)
c.equal("監視しているフォルダ", state.watched_dir, "/Volumes/Audio/sfz_slots")
c.equal("自動再読込の回数", state.reload_count, 1)
c.equal("載っているサンプルは 1 個", len(state.samples), 1)
c.check("rem されたものは残らない", not any("sine" in s for s in state.samples))
c.check("add されたものが載る", state.samples[0].endswith("square.wav"))
c.equal("警告を拾う", len(state.warnings), 1)
c.check("警告の中身", "Scala" in state.warnings[0])
c.check("読み上げにファイル名が出る", "slot01.sfz" in state.describe_ja())
c.check("読み上げにサンプル名が出る", "square.wav" in state.describe_ja())

# --- 何も無いログ ---
empty = parse_log("")
c.equal("空なら SFZ は None", empty.sfz_path, None)
c.equal("サンプルも空", empty.samples, [])
c.equal("リージョンも None", empty.regions, None)
c.equal("再読込は 0 回", empty.reload_count, 0)
c.check("分からないと言う", "分かりません" in empty.describe_ja(), empty.describe_ja())
c.check("SforzandoState として返る", isinstance(empty, SforzandoState))

# --- 行が混ざっても落ちない ---
# 複数スレッドが同時に書くので、実際にこういう行が出る。
BROKEN = (
    "I:1:2:10567838805:SourceManager rem:I:13524856832:I:Streamer::doCloseFile:0x13e0a1c00\n"
    "I:1:3:SourceManager add:/tmp/a.wav\n"
)
broken = parse_log(BROKEN)
c.check("壊れた行でも例外にならない", isinstance(broken, SforzandoState))
c.check("読める分は読む", any(s.endswith("a.wav") for s in broken.samples), str(broken.samples))

# --- 同じサンプルを何度も add しても重複しない ---
dup = parse_log(
    "I:1:1:SourceManager add:/tmp/a.wav\n" * 3
    + "I:1:1:SourceManager add:/tmp/b.wav\n"
)
c.equal("重複は持たない", dup.samples, ["/tmp/a.wav", "/tmp/b.wav"])

# --- 追加と削除の順序 ---
seq = parse_log(
    "I:1:1:SourceManager add:/tmp/a.wav\n"
    "I:1:2:SourceManager add:/tmp/b.wav\n"
    "I:1:3:SourceManager rem:/tmp/a.wav\n"
)
c.equal("削除されたものは消える", seq.samples, ["/tmp/b.wav"])

# --- パスにスペースが入っていても最後まで取る ---
# **Splice のファイル名は普通にスペースを含む。** ここで切れると
# 「見つからない」と誤検知する。
spaced = parse_log(
    "I:1:1:SourceManager add:/Volumes/Audio/Splice/Karra Vox Chop 120bpm Cmin.wav\n"
)
c.equal(
    "スペース入りのパスを丸ごと取る",
    spaced.samples,
    ["/Volumes/Audio/Splice/Karra Vox Chop 120bpm Cmin.wav"],
)

# --- 日本語が入っていても取れる ---
jp = parse_log("I:1:1:SourceManager add:/Volumes/Audio/素材/ドラム ループ.wav\n")
c.equal("日本語のパス", jp.samples, ["/Volumes/Audio/素材/ドラム ループ.wav"])

# --- 文字コードの判定が走ったか ---
c.check("既定では立たない", not empty.encoding_guessed)
binary = parse_log("I:1:1:Binary detected! off:6 = 131 brute force detected UTF-8!\n")
c.check("Binary detected を拾う", binary.encoding_guessed)

# --- 読み直しを何度も数える ---
many = parse_log("I:1:1:islot:0 x.sfz was externally modified! Reloading...\n" * 5)
c.equal("回数を数える", many.reload_count, 5)

# --- 最後の setFile が勝つ（読み替えたとき） ---
switched = parse_log(
    "I:1:1:SFZInstrument::setFile(/tmp/one.sfz)\n"
    "I:1:2:SFZInstrument::setFile(/tmp/two.sfz)\n"
)
c.equal("最後に読んだものを返す", switched.sfz_path, "/tmp/two.sfz")

# --- setFile が空でも落ちない ---
blank = parse_log("I:1:1:SFZInstrument::setFile()\n")
c.equal("空なら None", blank.sfz_path, None)

# --- サンプルが見つからないとき ---
# 実機で採った形。**どのファイルが無いかまで書いてある。**
MISSING = """\
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
E:8471126720:16515727910:PLAF::Factory::open() file not found:/Volumes/Audio/sfz_slots/testtones/存在しない.wav
E:8471126720:16515727920:PROC_INIT_RESULT:3
"""
bad = parse_log(MISSING)
c.equal("見つからないファイルを拾う", len(bad.missing_samples), 1)
c.check("パスごと拾う", bad.missing_samples[0].endswith("存在しない.wav"), str(bad.missing_samples))
c.equal("今回のエラーを数える", len(bad.errors), 2)
c.check("問題ありとみなす", bad.has_problem)
c.check("読み上げで警告する", "見つからない" in bad.describe_ja(), bad.describe_ja())

# **警告だけなら問題にしない。** Scala の警告は常に出ていて音には関係ない。
# ここを問題扱いすると、本当の失敗が埋もれる。
warn_only = parse_log("W:1:1:Scala open() ... cannot be found!\n")
c.equal("警告は拾う", len(warn_only.warnings), 1)
c.check("だが問題ではない", not warn_only.has_problem)
c.equal("エラーは 0", len(warn_only.errors), 0)

# 正常なログは問題なし
c.check("正常なら問題なし", not state.has_problem)
c.equal("エラーは 0 件", len(state.errors), 0)

# 同じファイルが何度も報告されても 1 件
dupmiss = parse_log("E:1:1:PLAF::Factory::open() file not found:/tmp/x.wav\n" * 3)
c.equal("重複は持たない", dupmiss.missing_samples, ["/tmp/x.wav"])

# スペース入りのパスでも最後まで取る
spacedmiss = parse_log(
    "E:1:1:PLAF::Factory::open() file not found:/Volumes/Audio/Splice/Vox Chop C min.wav\n"
)
c.equal(
    "スペース入りも丸ごと",
    spacedmiss.missing_samples,
    ["/Volumes/Audio/Splice/Vox Chop C min.wav"],
)

# --- PARSELOG DUMP ---
# **人が読める形の失敗理由がここに入る。** 行の形が他と違うので別扱い。
DUMP = """\
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
E:1:2:****PARSELOG DUMP+****
No sound asset loaded
Not Found:
 /tmp/存在しない.wav

E:1:3:****PARSELOG DUMP-****
"""
dumped = parse_log(DUMP)
c.check("失敗理由を取り出す", "No sound asset loaded" in dumped.parse_report, dumped.parse_report)
c.check("どのファイルかも入る", "存在しない.wav" in dumped.parse_report)
c.check("空行は落とす", "" not in dumped.parse_report.splitlines())
c.check("問題ありとみなす", dumped.has_problem)

# --- 読み込みのたびに数え直す ---
# **素朴に全体を集計すると、失敗した読み込みのあとに前回の値が残る。**
# それだと「リージョン 3 個」と出て、成功したように見えてしまう。
# **実機では読み込みのたびに `SourceManager wiping:N` が出る。**
# これを省いた作り物で試すと、実物と違う結論になる。
SEQUENCE = """\
I:1:1:SFZInstrument::setFile(/tmp/a.sfz)
I:1:2:SourceManager wiping:0
I:1:3:SourceManager add:/tmp/one.wav
I:1:4:SourceManager add:/tmp/two.wav
I:1:5:instrument: regions:2 * 100 = 200
I:1:6:SFZInstrument::setFile(/tmp/b.sfz)
I:1:7:SourceManager wiping:2
E:1:8:PLAF::Factory::open() file not found:/tmp/gone.wav
E:1:9:0x1 no regions in file!
"""
seq2 = parse_log(SEQUENCE)
c.equal("最後に読もうとしたファイル", seq2.sfz_path, "/tmp/b.sfz")
c.equal("前回のサンプルは残らない", seq2.samples, [])
c.equal("前回のリージョン数も残らない", seq2.regions, None)
c.equal("今回の失敗を報告する", seq2.missing_samples, ["/tmp/gone.wav"])
c.check("問題ありとみなす", seq2.has_problem)

# 成功した読み込みのあとは、ちゃんと値が入る
SUCCESS = SEQUENCE + "I:1:8:SFZInstrument::setFile(/tmp/c.sfz)\n" \
    "I:1:9:SourceManager add:/tmp/three.wav\n" \
    "I:1:10:instrument: regions:1 * 100 = 100\n"
ok_state = parse_log(SUCCESS)
c.equal("失敗の記録は持ち越さない", ok_state.missing_samples, [])
c.equal("古いエラーも持ち越さない", ok_state.errors, [])
c.check("問題なしに戻る", not ok_state.has_problem)
c.equal("今回のサンプル", ok_state.samples, ["/tmp/three.wav"])
c.equal("今回のリージョン数", ok_state.regions, 1)

# --- すでに載っているサンプルは載せ直さない ---
# **2026-09-04 に 2 通りの形で踏んだ誤判定。** SourceManager wiping:N が
# 「何個外したか」を表す。ここを正としないと取りこぼす。

# 形 1: 全部同じ。wiping:0 / adding:0 で、add: も rem: も出ない。
REUSED = """\
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:2:SourceManager add:/tmp/bass.wav
I:1:3:instrument: regions:1 * 3176 = 3176
I:1:4:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:5:SourceManager wiping:0
I:1:6:SourceManager adding:0
I:1:7:SourceManager: All files were used in a patch on the same slot
I:1:8:instrument: regions:1 * 3176 = 3176
"""
reused = parse_log(REUSED)
c.equal("載っているサンプルは消えない", reused.samples, ["/tmp/bass.wav"])
c.equal("リージョン数も取れる", reused.regions, 1)
c.check("問題なし", not reused.has_problem)
c.check("読み上げにサンプル名が出る", "bass.wav" in reused.describe_ja(), reused.describe_ja())

# 形 2: 一部だけ同じ。wiping:0 のまま新しい分だけ add: が出る。
PARTIAL = REUSED + """\
I:1:9:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:10:SourceManager wiping:0
I:1:11:SourceManager adding:2
I:1:12:SourceManager add:/tmp/lead.wav
I:1:13:SourceManager add:/tmp/pad.wav
I:1:14:instrument: regions:3 * 1 = 3
"""
partial = parse_log(PARTIAL)
c.equal("前の分も残る", len(partial.samples), 3)
c.check("前の分", "/tmp/bass.wav" in partial.samples, str(partial.samples))
c.check("足した分", "/tmp/pad.wav" in partial.samples)
c.equal("リージョン数と一致する", partial.regions, len(partial.samples))

# wiping:N が今の件数以上なら、全部外れたとみなす。
# **行が混ざって rem: が 1 本消えても取りこぼさない。**
WIPED = PARTIAL + """\
I:1:15:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:16:SourceManager wiping:3
I:1:17:SourceManager rem:/tmp/bass.wav
I:1:18:SourceManager add:/tmp/new.wav
I:1:19:instrument: regions:1 * 1 = 1
"""
wiped = parse_log(WIPED)
c.equal("全部外れて 1 個だけになる", wiped.samples, ["/tmp/new.wav"])

# 失敗した読み込み。wiping で全部外れ、add: が来ない。
FAILED_AFTER_REUSE = REUSED + """\
I:1:9:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:10:SourceManager wiping:1
E:1:11:PLAF::Factory::open() file not found:/tmp/gone.wav
"""
failed = parse_log(FAILED_AFTER_REUSE)
c.equal("失敗したら空", failed.samples, [])
c.check("問題ありとみなす", failed.has_problem)

# --- 監視の開始と停止 ---
# **監視は「何か読み込んでいる間だけ」効く。** 空にすると止まる。
c.check("読み込み中は監視が動いている", state.watching)

EMPTIED = REUSED + """\
I:1:9:0x31e8f2a00 Engine::onCTRLCommand (0,2,35,empty,,0)
I:1:10:stopping FolderWatcher
I:1:11:FolderWatcher::die() in
I:1:12:0x401e48000SFZInstrument::~SFZInstrument()in
I:1:13:0x401e48000 instrument::clearFile in
"""
emptied = parse_log(EMPTIED)
c.check("空にすると監視が止まる", not emptied.watching)
c.check("空になったと分かる", emptied.emptied)
c.equal("読んでいるファイルも無くなる", emptied.sfz_path, None)
c.equal("サンプルも無くなる", emptied.samples, [])
c.equal("リージョン数も無くなる", emptied.regions, None)
c.check("空だと伝える", "スロットは空です" in emptied.describe_ja(), emptied.describe_ja())
c.check("監視が止まったとも伝える", "監視は止まっています" in emptied.describe_ja())
c.check("何をすればよいかを言う", "読み込み直し" in emptied.describe_ja())
# **「分からない」と「空」は違う。** 何も無いログは前者。
c.check("空のログは分からないと言う", "分かりません" in parse_log("").describe_ja())
c.check("問題としては扱わない", not emptied.has_problem)

# 空にしたあと、もう一度読み込めば監視も戻る
RELOADED_AFTER_EMPTY = EMPTIED + """\
I:1:14:FolderWatcher start for */tmp*
I:1:15:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:16:SourceManager add:/tmp/new.wav
I:1:17:instrument: regions:1 * 1 = 1
"""
back = parse_log(RELOADED_AFTER_EMPTY)
c.check("読み込み直せば監視が戻る", back.watching)
c.check("空ではなくなる", not back.emptied)
c.equal("新しいサンプル", back.samples, ["/tmp/new.wav"])
c.equal("読んでいるファイル", back.sfz_path, "/tmp/slot01.sfz")

# --- 読み上げは短く保つ ---
# **ドラムキットは 61 個になることがある。** 全部読ませると名前だけで
# 何分もかかる。数が分かれば足りる（読み上げで使う前提の設計）。
MANY = "I:1:1:SFZInstrument::setFile(/tmp/x.sfz)\nI:1:2:SourceManager wiping:0\n" + "".join(
    f"I:1:{i}:SourceManager add:/tmp/sample_{i:02d}.wav\n" for i in range(3, 43)
)
many = parse_log(MANY)
c.equal("40 個ぜんぶ数える", len(many.samples), 40)
summary = many.describe_ja()
c.check("件数は出す", "サンプル 40 個" in summary, summary)
c.check("残りの数を言う", "ほか 37 個" in summary, summary)
c.check("名前は 3 つまで", summary.count(".wav") <= NAMES_IN_SUMMARY, summary)
c.check("読み上げが長くなりすぎない", len(summary) < 300, f"{len(summary)} 文字")

# 少ないときは全部出す
c.check("3 個以下なら「ほか」は出ない", "ほか" not in reused.describe_ja())

# ==========================================================================
# 複数スロット — インスタンスが 2 つ以上あるとき
# ==========================================================================
#
# sforzando を 2 つ挿すと **どちらも同じログに書く。** `islot:0` は
# どのインスタンスでも 0 なので使えない。**`.sfz` のパスで分ける。**
# 2026-09-04 に 2 インスタンスで実測した形。

TWO_SLOTS = """\
W:1:0:Scala open() ... cannot be found!
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:2:SourceManager wiping:0
I:1:3:SourceManager add:/tmp/kick.wav
I:1:4:instrument: regions:1 * 1 = 1
I:1:5:FolderWatcher start for */tmp*
I:1:6:SFZInstrument::setFile(/tmp/slot02.sfz)
I:1:7:SourceManager wiping:0
I:1:8:SourceManager add:/tmp/snare.wav
I:1:9:SourceManager add:/tmp/hat.wav
I:1:10:instrument: regions:2 * 1 = 2
I:1:11:FolderWatcher start for */tmp*
I:1:12:islot:0 slot02.sfz was externally modified! Reloading...
I:1:13:SFZInstrument::setFile(/tmp/slot02.sfz)
I:1:14:SourceManager wiping:2
I:1:15:SourceManager add:/tmp/tom.wav
I:1:16:instrument: regions:1 * 1 = 1
"""

slots = parse_by_file(TWO_SLOTS)
c.equal("スロットが 2 つに分かれる", sorted(slots), ["/tmp/slot01.sfz", "/tmp/slot02.sfz"])

one = slots["/tmp/slot01.sfz"]
two = slots["/tmp/slot02.sfz"]
c.equal("slot01 のリージョン", one.regions, 1)
c.equal("slot01 のサンプル", one.samples, ["/tmp/kick.wav"])
c.equal("slot02 のリージョン（最後の読み込み）", two.regions, 1)
c.equal("slot02 のサンプル", two.samples, ["/tmp/tom.wav"])
c.check("それぞれ監視している", one.watching and two.watching)

# **片方の書き換えは、もう片方に影響しない。**
c.equal("slot01 は読み直していない", one.reload_count, 0)
c.equal("slot02 だけ読み直した", two.reload_count, 1)

# 区切りより前の行（起動時の警告）は、どちらにも配る
c.equal("警告は両方に届く", (len(one.warnings), len(two.warnings)), (1, 1))

# 1 スロットしか無ければ 1 つ
c.equal("1 スロットなら 1 つ", len(parse_by_file(REUSED)), 1)
c.equal("何も無ければ空", parse_by_file(""), {})

# --- 一覧が取れないことと、載っていないことは違う ---
# **別のインスタンスが同じファイルを持っていると add: が出ない。**
# リージョンはあるのに一覧が空になる。これを「載っていない」と
# 言ってはいけない（2026-09-04 に実際に出た）。
SHARED = """\
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:2:SourceManager wiping:61
I:1:3:instrument: regions:1 * 3176 = 3176
"""
shared = parse_log(SHARED)
c.equal("リージョンはある", shared.regions, 1)
c.equal("一覧は空", shared.samples, [])
c.check("「取れていない」と分かる", shared.samples_unknown)
c.check("問題ではない", not shared.has_problem)
c.check("取れなかったと言う", "取れませんでした" in shared.describe_ja(), shared.describe_ja())
c.check("「載っていません」とは言わない", "読み込まれていません" not in shared.describe_ja())

# 本当に何も載っていない場合は samples_unknown にしない
nothing_loaded = parse_log(
    "I:1:1:SFZInstrument::setFile(/tmp/x.sfz)\nI:1:2:SourceManager wiping:0\n"
)
c.check("リージョンが無ければ「取れていない」ではない", not nothing_loaded.samples_unknown)

# 失敗しているときも samples_unknown にしない（原因は別にある）
c.check("失敗時は「取れていない」ではない", not bad.samples_unknown)

# --- 捨てられたあとの行を前のスロットへ入れない ---
#
# **sforzando は import のとき `setFile` より先に監視を始める。**
# 区間を閉じずにいると、別のインスタンスの監視開始を、空にした
# スロットの監視再開と読み違える。その結果「いまは必要ありません」と
# 名乗るのに、実際の監視は止まっていて反映されない。

EMPTIED_THEN_OTHER = """\
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:2:instrument: regions:1 * 1 = 1
I:1:3:FolderWatcher start for */tmp*
I:1:4:Engine::onCTRLCommand (0,2,35,empty,,0)
I:1:5:stopping FolderWatcher
I:1:6:0x1SFZInstrument::~SFZInstrument()in
I:1:7:FolderWatcher start for */tmp*
I:1:8:SFZInstrument::setFile(/tmp/slot02.sfz)
I:1:9:instrument: regions:1 * 1 = 1
"""
pair = parse_by_file(EMPTIED_THEN_OTHER)
c.equal("2 スロット分に分かれる", len(pair), 2)
c.check("空にした側は空のまま", pair["/tmp/slot01.sfz"].emptied)
c.check("空にした側は監視していない", not pair["/tmp/slot01.sfz"].watching)
c.check("入れた側は監視している", pair["/tmp/slot02.sfz"].watching)
c.check("入れた側は空ではない", not pair["/tmp/slot02.sfz"].emptied)

# **同じスロットを入れ直したときは監視を取りこぼさない。**
# 区間の外の行は捨てずに、次の `setFile` の頭へ回している。
RELOAD_SAME = """\
I:1:1:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:2:FolderWatcher start for */tmp*
I:1:3:stopping FolderWatcher
I:1:4:0x1SFZInstrument::~SFZInstrument()in
I:1:5:FolderWatcher start for */tmp*
I:1:6:SFZInstrument::setFile(/tmp/slot01.sfz)
I:1:7:instrument: regions:1 * 1 = 1
"""
again = parse_by_file(RELOAD_SAME)["/tmp/slot01.sfz"]
c.check("入れ直せば空ではない", not again.emptied)
c.check("入れ直した監視を拾う", again.watching)

# --- 同じ内容なら読み直さない ---
import tempfile

with tempfile.TemporaryDirectory() as tmpdir:
    log = Path(tmpdir) / "aria.log"
    log.write_text(EMPTIED_THEN_OTHER, encoding="utf-8")
    first = read_states(log)
    c.check("読める", first is not None)
    c.check("同じ内容なら同じ物を返す", read_states(log) is first)
    log.write_text(
        EMPTIED_THEN_OTHER + "I:1:9:SFZInstrument::setFile(/tmp/slot03.sfz)\n",
        encoding="utf-8",
    )
    c.equal("追記されたら読み直す", len(read_states(log)), 3)
    c.equal("無いファイルは None", read_states(Path(tmpdir) / "nope.log"), None)

raise SystemExit(c.summary())
