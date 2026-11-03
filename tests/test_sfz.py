"""sfz.py のテスト。生成の規約と、往復（render → parse → 同じモデル）。

往復テストを置いているのは、**自分の生成物を自分で読み返せることを保証するため。**
外部のパーサ実装に頼らずに、1 行 1 オプコードなどの規約違反を機械的に捕まえられる。
"""

from _harness import Checker

from core.sfz import (
    Opcode,
    Region,
    SfzDocument,
    SfzError,
    fmt_number,
    parse,
    render,
)

c = Checker("sfz")

# --- fmt_number: 指数表記を出さないことが要点 ---
c.equal("0.001 はそのまま", fmt_number(0.001), "0.001")
c.equal("0.02 はそのまま", fmt_number(0.02), "0.02")
c.equal("整数は小数点を付けない", fmt_number(18000), "18000")
c.equal("100.0 は '100'", fmt_number(100.0), "100")
c.equal("0.00001 が指数表記にならない", fmt_number(0.00001), "0.00001")
c.equal("負値も扱える", fmt_number(-0.5), "-0.5")
c.equal("6 桁未満は 0 に丸まる", fmt_number(0.0000001), "0")
c.raises("bool は弾く（int の派生なので素通りしやすい）", SfzError, fmt_number, True)
c.raises("NaN は弾く", SfzError, fmt_number, float("nan"))
c.raises("無限大は弾く", SfzError, fmt_number, float("inf"))

# --- Opcode: 名前と値の検証 ---
c.equal("render は name=value", Opcode("cutoff", "800").render(), "cutoff=800")
c.equal("number() は書式を委ねる", Opcode.number("cutoff", 800.0).value, "800")
c.raises("大文字を含む名前は不正", SfzError, Opcode, "Cutoff", "800")
c.raises("数字始まりの名前は不正", SfzError, Opcode, "2pole", "1")
c.raises("値に改行は入れられない", SfzError, Opcode, "cutoff", "80\n0")

# --- ノート値: 音名表記を通さないことが肝 ---
c.equal("数値のノートは通る", Opcode("pitch_keycenter", "60").value, "60")
c.raises(
    "音名 'c4' は弾く（C4=60 か 72 かが実装で割れる）",
    SfzError,
    Opcode,
    "pitch_keycenter",
    "c4",
)
c.raises("128 は範囲外", SfzError, Opcode, "hikey", "128")
c.raises("-1 は範囲外", SfzError, Opcode, "lokey", "-1")

# --- Region ---
c.raises("空の sample は弾く", SfzError, Region, "")
c.raises("空白だけの sample も弾く", SfzError, Region, "   ")
c.raises("sample に改行は入れられない", SfzError, Region, "/a\n/b.wav")
c.equal(
    "get() でオプコードを引ける",
    Region("/a.wav", [Opcode("loop_mode", "no_loop")]).get("loop_mode"),
    "no_loop",
)
c.equal("無いオプコードは None", Region("/a.wav").get("cutoff"), None)

# --- SfzDocument ---
c.raises(
    "default_path は末尾に / が要る",
    SfzError,
    SfzDocument,
    [Region("/a.wav")],
    [],
    [],
    "/Volumes/Audio/samples",
)

# --- render の規約 ---
doc = SfzDocument(
    regions=[
        Region(
            sample="/Volumes/Audio/Splice/Vox Chop C min.wav",
            opcodes=[
                Opcode.number("lokey", 0),
                Opcode.number("hikey", 127),
                Opcode.number("pitch_keycenter", 60),
                Opcode("loop_mode", "no_loop"),
            ],
        )
    ],
    global_opcodes=[Opcode.number("ampeg_release", 0.08)],
    comments=["スロット1", "生成: 2026-09-01T00:00:00+00:00"],
)
text = render(doc)
lines = [line for line in text.splitlines() if line.strip()]

c.check("コメントが // で出る", lines[0] == "// スロット1")
c.check("<global> が出る", "<global>" in lines)
c.check("<region> が出る", "<region>" in lines)
c.check(
    "sample= が region の最後の行",
    lines[-1] == "sample=/Volumes/Audio/Splice/Vox Chop C min.wav",
    detail=f"実際の末尾: {lines[-1]!r}",
)
c.check(
    "1 行 1 オプコード（= を含む行に空白区切りの続きが無い）",
    all(
        line.startswith("sample=") or " " not in line
        for line in lines
        if "=" in line and not line.startswith("//")
    ),
)
c.check("末尾は改行で終わる", text.endswith("\n"))

# --- 往復。スペースを含むパスが壊れないことが最重要 ---
c.equal("render → parse で元に戻る", parse(text), doc)

doc_dp = SfzDocument(
    regions=[Region("kick.wav", [Opcode.number("key", 36)])],
    default_path="/Volumes/Audio/Splice/",
)
c.equal("default_path も往復する", parse(render(doc_dp)), doc_dp)

doc_multi = SfzDocument(
    regions=[
        Region("/a/kick.wav", [Opcode.number("key", 36)]),
        Region("/a/snare 01.wav", [Opcode.number("key", 37)]),
    ]
)
c.equal("複数リージョンも往復する", parse(render(doc_multi)), doc_multi)

# --- parse: 壊れた入力を黙って受けない ---
c.raises("sample= の無い <region>", SfzError, parse, "<region>\nkey=36\n")
c.raises("未対応のヘッダ", SfzError, parse, "<group>\nkey=36\n")
c.raises("ヘッダより前のオプコード", SfzError, parse, "key=36\n")
c.raises("= の無い行", SfzError, parse, "<region>\nkey 36\nsample=/a.wav\n")

raise SystemExit(c.summary())
