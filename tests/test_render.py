"""integration/render.py のテスト。**ffmpeg は呼ばない。**

伸縮の実体（借りている部品の `ptcore/dsp.py`）を差し替えて、
作り直しの判断・失敗の扱い・進み具合の通知を確かめる。
"""

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from _harness import Checker

from core.phrase import plan_phrase
from integration import render as render_mod
from integration.render import (
    RenderResult,
    clean_rendered,
    find_unused,
    render_phrase,
)

c = Checker("render")


@dataclass
class FakeProcessResult:
    ok: bool
    message: str = ""


class FakeDsp:
    """`dsp` の代わり。呼ばれた引数を控える。"""

    def __init__(self, *, ok=True, message="", backend="ffmpeg", raises=False):
        self.ok = ok
        self.message = message
        self.backend = backend
        self.raises = raises
        self.calls: list[tuple[str, str, float, float]] = []

    def process(self, source, dest, semitones=0.0, tempo_ratio=1.0):
        self.calls.append((source, dest, semitones, tempo_ratio))
        if self.raises:
            raise RuntimeError("想定外")
        if self.ok:
            Path(dest).write_bytes(b"x" * 16)
        return FakeProcessResult(self.ok, self.message)

    def choose_backend(self):
        class B:
            name = self.backend

        return B()


def install(fake) -> None:
    render_mod._load_dsp = lambda: fake  # type: ignore[assignment]


# ==========================================================================
# Finder から開いたときの PATH（2026-10-25 のレビュー）
# ==========================================================================
#
# **Finder から開いた .app の PATH には Homebrew が無い。** 伸縮の道具を
# `shutil.which` で探すので、入っていても「入っていない」になり、
# 「速さを保つ」とテンポ合わせが必ず失敗していた。

from integration.render import TOOL_DIRS, backend_name, ensure_tool_path  # noqa: E402

saved_path = os.environ.get("PATH", "")
try:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PATH"] = "/usr/bin:/bin"
        missing = os.path.join(tmp, "no_such_dir")
        added = ensure_tool_path((tmp, missing, "/usr/bin"))
        c.equal("無い場所と、もうある場所は足さない", added, [tmp])
        c.equal(
            "後ろに足す（利用者の順を崩さない）",
            os.environ["PATH"].split(os.pathsep),
            ["/usr/bin", "/bin", tmp],
        )
        c.equal("二度目は足さない", ensure_tool_path((tmp,)), [])

    # 実物で: Finder と同じ PATH から、入っている ffmpeg を見つけられるか
    homebrew = [d for d in TOOL_DIRS if os.path.isfile(os.path.join(d, "ffmpeg"))]
    if homebrew and render_mod._load_dsp() is not None:
        os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        c.check(
            "Finder の PATH でも伸縮の道具が見つかる",
            backend_name() != "",
            os.environ["PATH"],
        )
finally:
    os.environ["PATH"] = saved_path


with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / "loop.wav"
    src.write_bytes(b"src" * 100)
    out = str(Path(tmp) / "rendered")
    plan = plan_phrase(str(src), 60, span=2, out_dir=out)

    # ======================================================================
    # うまくいく場合
    # ======================================================================

    fake = FakeDsp()
    install(fake)
    steps: list[tuple[int, int]] = []
    result = render_phrase(
        plan.renders, progress=lambda i, n, d: steps.append((i, n))
    )
    c.check("成功する", result.ok)
    # **倍率 1 の鍵盤は元のファイルをそのまま指す**ので作らない。
    # 同じ中身のコピーを置かないための造り（`core/phrase.py`）。
    c.equal("4 個作る", result.made, 4)
    c.equal("倍率 1 の 1 個は触らない", result.untouched, 1)
    c.equal("飛ばした（作り直さなかった）ものは無い", result.skipped, 0)
    # 進み具合は**実際に作るものだけ**を数える。触らない 1 個を混ぜると
    # 「5 分の 5 まで行ったのに 4 個」と食い違って聞こえる。
    c.equal("進み具合は 4 回", len(steps), 4)
    c.equal("最後は 4/4", steps[-1], (4, 4))
    c.check(
        "触らない分も読み上げる",
        "元のファイルをそのまま使います" in result.describe_ja(),
        result.describe_ja(),
    )
    c.check("件数を読み上げる", "4個を作りました" in result.describe_ja(), result.describe_ja())

    root = [r for r in plan.renders if r.is_original]
    c.equal("倍率 1 はちょうど 1 個", len(root), 1)
    c.equal("元のファイルを指す", root[0].dest, str(src))

    # **音程は変えない。長さだけ。** ここを取り違えると二重に移調される。
    c.check("半音数は常に 0", all(call[2] == 0.0 for call in fake.calls))
    ratios = sorted(round(call[3], 6) for call in fake.calls)
    want = sorted(
        round(r.tempo_ratio, 6) for r in plan.renders if not r.is_original
    )
    c.equal("倍率は計画どおり", ratios, want)

    # ======================================================================
    # 作り直さない
    # ======================================================================

    fake2 = FakeDsp()
    install(fake2)
    result = render_phrase(plan.renders)
    c.check("2 回目も成功", result.ok)
    c.equal("何も作らない", result.made, 0)
    c.equal("4 個は飛ばす", result.skipped, 4)
    c.equal("倍率 1 の 1 個は触らない", result.untouched, 1)
    c.equal("dsp を呼ばない", len(fake2.calls), 0)
    c.check("飛ばしたと言う", "作り直していません" in result.describe_ja())

    # ======================================================================
    # force でも元の素材には触らない
    # ======================================================================
    #
    # **倍率 1 の項目は出力先が元のファイルそのもの。** ここを加工すると
    # 実物の ffmpeg は `-y` で入力を先に切り詰めるので、利用者の Splice
    # 素材が空になる。作り直したいのは下ごしらえであって元の素材ではない。

    fake3 = FakeDsp()
    install(fake3)
    result = render_phrase(plan.renders, force=True)
    c.equal("force でも作るのは 4 個", result.made, 4)
    c.equal("倍率 1 の 1 個は触らない", result.untouched, 1)
    c.equal("dsp を 4 回だけ呼ぶ", len(fake3.calls), 4)
    c.check(
        "元と出力が同じ呼び出しは無い",
        all(
            os.path.abspath(call[0]) != os.path.abspath(call[1])
            for call in fake3.calls
        ),
    )
    c.equal("元のファイルは無事", src.read_bytes(), b"src" * 100)

    # **元のファイルが新しくなったら作り直す。**
    # 素材を差し替えたのに古い下ごしらえを使うと、鳴る音と表示が食い違う。
    time.sleep(0.01)
    future = time.time() + 60
    os.utime(src, (future, future))
    fake4 = FakeDsp()
    install(fake4)
    result = render_phrase(plan.renders)
    # **倍率 1 のものは元そのものなので、そもそも触らない。**
    c.equal("元が新しければ作り直す", result.made, 4)
    c.equal("飛ばすものは無い", result.skipped, 0)
    c.equal("倍率 1 の 1 個は触らない", result.untouched, 1)

    # ======================================================================
    # 失敗
    # ======================================================================

    fake5 = FakeDsp(ok=False, message="ffmpeg が落ちた")
    install(fake5)
    result = render_phrase(plan.renders)
    c.check("失敗する", not result.ok)
    c.equal("失敗を全部数える", len(result.failures), 4)
    c.check("理由を読み上げる", "ffmpeg が落ちた" in result.message_ja, result.message_ja)
    c.check("件数も言う", "ほか3件" in result.message_ja, result.message_ja)

    # 例外も外へ出さない
    fake6 = FakeDsp(raises=True)
    install(fake6)
    result = render_phrase(plan.renders)
    c.check("例外は握る", not result.ok)
    c.check("RenderResult で返る", isinstance(result, RenderResult))
    c.check("理由が入る", "想定外" in result.message_ja, result.message_ja)

    # 伸縮の道具が無い
    install(FakeDsp(backend=""))
    result = render_phrase(plan.renders)
    c.check("道具が無ければ失敗", not result.ok)
    c.check("入れるものを言う", "ffmpeg" in result.message_ja, result.message_ja)

    # 借りている部品自体が無い
    render_mod._load_dsp = lambda: None  # type: ignore[assignment]
    result = render_phrase(plan.renders)
    c.check("借りている部品が無ければ失敗", not result.ok)
    c.check("何が無いかを言う", "借りている部品" in result.message_ja, result.message_ja)

    # 空の計画は成功扱い。**やることが無いのは失敗ではない。**
    result = render_phrase([])
    c.check("空でも成功", result.ok)
    c.check("要らなかったと言う", "要りません" in result.describe_ja())

    # **加工が要らないものだけなら、伸縮の道具が無くても成功する。**
    # 道具の有無を先に見ていたときは、テンポを変えないクロマティックが
    # ffmpeg の無い環境で理由もなく失敗していた。
    render_mod._load_dsp = lambda: None  # type: ignore[assignment]
    result = render_phrase([r for r in plan.renders if r.is_original])
    c.check("触らないものだけなら道具は要らない", result.ok)
    c.equal("触らないと数える", result.untouched, 1)

    # ======================================================================
    # 置き場所が作れない
    # ======================================================================
    #
    # **生の OSError を外へ出さない。** UI まで素通りすると、読み上げ無しで
    # 落ちる（`.sfz` の書き込み側は握っているので、そろえる）。

    install(FakeDsp())
    blocked = Path(tmp) / "blocked"
    blocked.write_bytes(b"file, not a directory")
    plan_blocked = plan_phrase(str(src), 60, span=1, out_dir=str(blocked / "sub"))
    result = render_phrase(plan_blocked.renders)
    c.check("置き場所が作れなくても例外は出さない", not result.ok)
    c.check("RenderResult で返る", isinstance(result, RenderResult))
    c.check(
        "理由を読み上げる",
        "下ごしらえに失敗しました" in result.message_ja,
        result.message_ja,
    )

# ==========================================================================
# 片付け
# ==========================================================================
#
# **消すほうは今まで通しで確かめていなかった。** 参照の照合を間違えると、
# いま鳴っているスロットのファイルを消してしまう。

with tempfile.TemporaryDirectory() as tmp:
    slots = Path(tmp)
    rendered = slots / "rendered"
    rendered.mkdir()
    keep = rendered / "keep__aaaaaaaa__p+01.wav"
    drop = rendered / "drop__bbbbbbbb__p+02.wav"
    keep.write_bytes(b"k" * 2048)
    drop.write_bytes(b"d" * 4096)
    (slots / "slot01.sfz").write_text(
        "<region>\nlokey=60\nhikey=60\npitch_keycenter=60\n"
        f"sample={keep}\n",
        encoding="utf-8",
    )

    # **別のセッションのフォルダも見る。** 下ごしらえは共有なので、
    # いま開いているセッションの分だけを見ると、別のセッションが
    # 使っているファイルを「使っていない」と判断して消してしまう。
    other = slots / "260825_1"
    other.mkdir()
    shared = rendered / "shared__cccccccc__p+03.wav"
    shared.write_bytes(b"s" * 1024)
    (other / "slot01.sfz").write_text(
        "<region>\nlokey=60\nhikey=60\npitch_keycenter=60\n"
        f"sample={shared}\n",
        encoding="utf-8",
    )

    found = find_unused(str(slots))
    c.check("走査は成功する", found.ok, found.message_ja)
    c.equal("使っていないのは 1 個", found.paths, [str(drop)])
    c.check(
        "別のセッションが使っているものは消さない",
        str(shared) not in found.paths,
        str(found.paths),
    )
    c.check("消す前は消さない", drop.is_file())
    c.check("量を言う", "使われていません" in found.describe_ja(), found.describe_ja())

    # **読み上げて確認を取った一覧をそのまま消す。**
    # 数え直すと、確認の前後で `.sfz` が変わったとき件数が食い違う。
    done = clean_rendered(str(slots), paths=found.paths)
    c.equal("1 個消した", done.removed, 1)
    c.check("参照されているものは残る", keep.is_file())
    c.check("参照されていないものは消える", not drop.is_file())

    # **確認のあとに使い始めたものは消さない。** 確認した一覧の中から、
    # 消す直前にもう一度数え、いまも使われていないものだけを消す
    # （2026-10-25 のレビュー。確認の間に別のセッションが割り当てると、
    # 鳴っているスロットのファイルまで消していた）。
    late = rendered / "late__dddddddd__p+04.wav"
    late.write_bytes(b"l" * 512)
    listed = find_unused(str(slots))
    c.equal("一度は使っていないと挙がる", listed.paths, [str(late)])
    (other / "slot02.sfz").write_text(
        "<region>\nlokey=61\nhikey=61\npitch_keycenter=61\n"
        f"sample={late}\n",
        encoding="utf-8",
    )
    done = clean_rendered(str(slots), paths=listed.paths)
    c.check("確認のあとに使い始めたものは残る", late.is_file())
    c.equal("消した数は 0", done.removed, 0)
    c.check("消さなかったと言う", "ありませんでした" in done.describe_ja(), done.describe_ja())

    # 読めない `.sfz` があれば中止する。取りこぼすと要るものを消す。
    (slots / "broken.sfz").write_text("<region>\nsample=", encoding="utf-8")
    keep.write_bytes(b"k" * 2048)
    broken = find_unused(str(slots))
    if broken.ok:
        # parse が通ってしまう書き方なら、少なくとも keep を消さないこと
        c.check("読めても keep は残す", str(keep) not in broken.paths)
    else:
        c.check("読めなければ中止する", not broken.ok)
        c.check("理由を言う", "中止します" in broken.message_ja, broken.message_ja)

raise SystemExit(c.summary())
