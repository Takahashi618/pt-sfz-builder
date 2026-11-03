"""ui/controller.py のテスト。**wx は使わない。**

画面を作らずに、押されたときの判断を全部通す。ライブラリ・前面の
プラグイン・読み込ませる操作は、どれもスタブを注入する。

**「素材が無い」「前面がプラグインでない」「索引が読めない」といった
うまくいかない場合を重点的に見る。** うまくいく場合は実機で確かめている。
"""

from dataclasses import dataclass
from pathlib import Path

from _harness import Checker

from core.kinds import KIND_LABELS
from core.mapping import MODE_CHROMATIC, MODE_DRUMKIT, MODE_PHRASE
from core.slots import PluginKind, SlotLayout, SlotLedger
from core.target import PluginTarget
from integration.reloader import NullReload
from integration.service import AssignService
from ui.controller import (
    MODE_AUTO,
    AppController,
    AssignForm,
    Outcome,
    SearchForm,
    _note_number,
)

c = Checker("controller")


@dataclass
class FakeEntry:
    """`SampleEntry` の代わり。

    **`duration` も要る。** 種別は長さで判定し直すため（`core/kinds.py`）。
    """

    path: str
    text: str = "テスト素材"
    kind: str = "one_shot"
    duration: float | None = 1.0
    pack: str = ""
    mtime: float = 0.0
    filename: str = ""
    description: str = ""

    @property
    def kind_label(self) -> str:
        """**本物と同じく `kind` から作る。**

        固定の文字列を返していたときは、`result_labels` が
        「種別を入れ替えてから `summary()` を呼ぶ」ようになっても
        気づけなかった。
        """
        return KIND_LABELS.get(self.kind or "", "不明")

    def summary(self) -> str:
        return f"{self.text}、{self.kind_label}"


class FakePlayer:
    """**音は出さない。** 呼ばれ方だけ確かめる。"""

    def __init__(self, fails: bool = False) -> None:
        self.current_path = None
        self.fails = fails
        self.calls: list[str] = []

    def load(self, path):
        if self.fails:
            raise RuntimeError("読めません")
        self.current_path = str(path)
        self.calls.append("load")

    def play(self):
        self.calls.append("play")

    def stop(self):
        self.calls.append("stop")

    def toggle_play_stop(self):
        self.calls.append("toggle")

    def describe_state_ja(self):
        return "再生中、0.0秒目"

    def describe_state_en(self):
        return "playing, at 0.0 seconds"


class FakeLibrary:
    def __init__(self, entries=None, raises=False):
        self.entries = entries or []
        self.raises = raises
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("壊れた索引")
        return self.entries

    def packs(self):
        return ["Pack A", "Pack B"]

    def keys(self):
        return ["C", "Am"]


TARGET = PluginTarget(plugin=PluginKind.SFORZANDO, track_name="Inst1")


def make(
    tmpdir,
    *,
    library=None,
    target=TARGET,
    loader=None,
    message="見つかりました",
    player=None,
    session="",
):
    layout = SlotLayout(slots_dir=tmpdir)
    service = AssignService(
        SlotLedger.create(layout, [PluginKind.SFORZANDO]), NullReload()
    )
    return AppController(
        layout=layout,
        library=library if library is not None else FakeLibrary(),
        target_reader=lambda: (target, message, session),
        plugin_loader=loader or (lambda path, track: Outcome(True, "読み込ませました。")),
        service=service,
        player=player if player is not None else FakePlayer(),
    )


import tempfile

with tempfile.TemporaryDirectory() as raw:
    tmp = raw

    # ======================================================================
    # 検索
    # ======================================================================

    lib = FakeLibrary(
        [
            FakeEntry("/a.wav", "ギター、120 BPM", kind="loop", duration=8.0,
                      filename="Guitar_Loop_120.wav"),
            FakeEntry("/b.wav", kind="loop", duration=8.0, filename="guitar_strum.wav"),
        ]
    )
    app = make(tmp, library=lib)

    result = app.search(SearchForm(text="guitar", kind="loop"))
    c.check("見つかれば成功", result.ok)
    c.check("件数を言う", "2 件" in result.message_ja, result.message_ja)
    c.check("何で絞ったかを言う", "guitar" in result.message_ja)
    c.equal("結果を持つ", len(app.results), 2)
    # **絞り込みと同じ種別を出す。** 長さで判定し直したものを持たせてから
    # `summary()` を呼んでいるので、名前だけの判定とは食い違わない。
    c.equal("一覧の文字列", app.result_labels()[0], "ギター、120 BPM、ループ")
    c.equal("パスを取り出せる", app.result_path(0), "/a.wav")
    c.equal("範囲外は None", app.result_path(9), None)
    c.equal("負の番号も None", app.result_path(-1), None)

    # 条件はライブラリへそのまま渡る。**語だけは自分で照合する**（全角・NFD を
    # そろえるため。2026-10-25）
    c.equal("語はライブラリに渡さない", lib.calls[-1]["text"], None)
    # **種別だけはライブラリに任せない。** あちらはファイル名だけで判定する。
    c.equal("種別は渡さない", lib.calls[-1]["kind"], None)
    c.equal("空の条件は None にする", lib.calls[-1]["key"], None)

    # --- 見つからない ---
    app = make(tmp, library=FakeLibrary([]))
    result = app.search(SearchForm(text="なにか"))
    c.check("0 件は成功ではない", not result.ok)
    c.check("条件を添えて伝える", "なにか" in result.message_ja, result.message_ja)
    c.equal("結果は空", app.results, [])

    # --- BPM が数字でない ---
    app = make(tmp, library=FakeLibrary([FakeEntry("/a.wav")]))
    result = app.search(SearchForm(bpm="はやい"))
    c.check("数字でなければ止める", not result.ok)
    c.check("何が悪いかを言う", "BPM" in result.message_ja, result.message_ja)
    c.equal("ライブラリは呼ばない", len(app.results), 0)

    # --- 索引が読めない ---
    app = make(tmp, library=None)
    app._library = None
    app._library_tried = True
    result = app.search(SearchForm(text="x"))
    c.check("索引が無ければ失敗", not result.ok)
    c.check(
        "代わりの手段を案内する",
        "ファイルを選んで割り当て" in result.message_ja,
        result.message_ja,
    )
    c.equal("パックは空", app.packs(), [])
    c.equal("キーも空", app.keys(), [])

    # --- ライブラリが例外を投げる ---
    app = make(tmp, library=FakeLibrary(raises=True))
    result = app.search(SearchForm(text="x"))
    c.check("例外は外へ出さない", not result.ok)
    c.check("理由を添える", "壊れた索引" in result.message_ja, result.message_ja)

    # ======================================================================
    # 割り当て先
    # ======================================================================

    app = make(tmp)
    found = app.detect_target()
    c.check("見つかる", found.ok)
    c.equal("対象を覚える", app.target, TARGET)

    app = make(tmp, target=None, message="プラグインのウィンドウが開いていません。")
    found = app.detect_target()
    c.check("見つからなければ失敗", not found.ok)
    c.check("理由をそのまま返す", "開いていません" in found.message_ja)

    # ======================================================================
    # 割り当て
    # ======================================================================

    app = make(tmp)
    result = app.assign([], AssignForm())
    c.check("素材が無ければ止める", not result.ok)
    c.check("何が足りないかを言う", "素材" in result.message_ja, result.message_ja)

    # **対象を調べていなくても、こちらで調べる。** 2 回押させない。
    app = make(tmp)
    c.equal("最初は対象を知らない", app.target, None)
    result = app.assign(["/tmp/x.wav"], AssignForm())
    c.check("割り当てられる", result.ok, result.message_ja)
    c.equal("ついでに対象を覚える", app.target, TARGET)
    c.check("書いた先を覚える", app.last_written is not None)
    c.check("読み上げにトラック名が入る", "Inst1" in result.message_ja, result.message_ja)

    # 前面がプラグインでなければ、割り当てずに理由を返す
    app = make(tmp, target=None, message="対象ではありません。")
    result = app.assign(["/tmp/x.wav"], AssignForm())
    c.check("対象が無ければ割り当てない", not result.ok)
    c.check("理由を返す", "対象ではありません" in result.message_ja)
    c.equal("何も書いていない", app.last_written, None)

    # ルートキーを指定する
    app = make(tmp)
    result = app.assign(["/tmp/x.wav"], AssignForm(root_key="F", octave=3))
    c.check("指定したルートキーで通る", result.ok, result.message_ja)
    c.check("読み上げに F3 が出る", "F3" in result.message_ja, result.message_ja)

    # **知らない音名は弾く。** 黙って既定値に落とすと、違う高さで鳴る
    app = make(tmp)
    result = app.assign(["/tmp/x.wav"], AssignForm(root_key="H"))
    c.check("知らない音名は止める", not result.ok)
    c.check("何が分からないかを言う", "H" in result.message_ja, result.message_ja)

    # ドラムキット
    app = make(tmp)
    result = app.assign(
        ["/tmp/a.wav", "/tmp/b.wav"], AssignForm(mode=MODE_DRUMKIT)
    )
    c.check("ドラムキットも通る", result.ok, result.message_ja)
    c.check("並べ方を言う", "順に配置" in result.message_ja, result.message_ja)

    # ======================================================================
    # プラグインへ読み込ませる
    # ======================================================================

    app = make(tmp)
    result = app.load_into_plugin()
    c.check("割り当て前は押させない", not result.ok)
    c.check("先に何をすべきか言う", "割り当て" in result.message_ja, result.message_ja)

    calls: list[tuple[str, str]] = []

    def loader(path: str, track: str) -> Outcome:
        calls.append((path, track))
        return Outcome(True, "読み込ませました。")

    app = make(tmp, loader=loader)
    app.assign(["/tmp/x.wav"], AssignForm())
    result = app.load_into_plugin()
    c.check("読み込ませられる", result.ok)
    c.equal("書いたファイルを渡す", [p for p, _ in calls], [app.last_written])
    # **書いたときのトラックも渡す。** 道具はそのトラックの画面だけを押す
    # （以前は前にある sforzando を押していた。2026-10-25 のレビュー）。
    c.equal("割り当てたトラックを渡す", [t for _, t in calls], ["Inst1"])

    # 失敗はそのまま伝える
    app = make(tmp, loader=lambda p, t: Outcome(False, "プラグインの画面が要ります。"))
    app.assign(["/tmp/x.wav"], AssignForm())
    result = app.load_into_plugin()
    c.check("失敗を伝える", not result.ok)
    c.check("直し方を言う", "画面" in result.message_ja)

    # ======================================================================
    # 台帳の要約
    # ======================================================================

    app = make(tmp)
    c.check("空なら空と言う", "使っていません" in app.slot_summary_ja())
    app.assign(["/tmp/x.wav"], AssignForm())
    summary = app.slot_summary_ja()
    c.check("使ったスロットを言う", "スロット1" in summary, summary)
    c.check("トラック名も言う", "Inst1" in summary)
    c.check("句点が重ならない", "。。" not in summary, summary)

# ==========================================================================
# 音名 → MIDI ノート番号
# ==========================================================================

c.equal("C3 は 60", _note_number("C", 3), 60)
c.equal("F3 は 65", _note_number("F", 3), 65)
c.equal("C4 は 72", _note_number("C", 4), 72)
c.equal("知らない音名は None", _note_number("H", 3), None)
c.equal("範囲外のオクターブも None", _note_number("C", 99), None)

# ==========================================================================
# SearchForm の読み上げ
# ==========================================================================

c.equal("条件なし", SearchForm().describe_ja(), "条件なし")
c.check("語だけ", "guitar" in SearchForm(text="guitar").describe_ja())
form = SearchForm(key="Am", relative=True)
c.check("平行調も言う", "平行調" in form.describe_ja(), form.describe_ja())
form = SearchForm(bpm="128", tolerance=4)
c.check("BPM と許容", "128 BPM、前後4" in form.describe_ja(), form.describe_ja())
c.check("種別は日本語", "ループ" in SearchForm(kind="loop").describe_ja())

# ==========================================================================
# Outcome
# ==========================================================================

c.check("真偽値として使える", bool(Outcome(True, "")) is True)
c.check("失敗は偽", bool(Outcome(False, "")) is False)

# ==========================================================================
# セッションのテンポ
# ==========================================================================

with tempfile.TemporaryDirectory() as tmp2:
    app = make(tmp2)
    c.equal("最初は覚えていない", app.load_session_bpm(), "")

    # **数字でなければ止める。** 黙って無視すると、合わせたつもりで使い続ける。
    result = app.assign(["/tmp/x.wav"], AssignForm(target_bpm="はやい"))
    c.check("数字でなければ止める", not result.ok)
    c.check("何が悪いかを言う", "テンポ" in result.message_ja, result.message_ja)
    c.equal("覚えない", app.load_session_bpm(), "")

    # 範囲外も止める
    result = app.assign(["/tmp/x.wav"], AssignForm(target_bpm="9999"))
    c.check("範囲外は止める", not result.ok)
    c.check("範囲を言う", "範囲外" in result.message_ja, result.message_ja)

    # **どの経路から割り当てても覚える。**
    result = app.assign(["/tmp/x.wav"], AssignForm(target_bpm="128"))
    c.check("割り当てられる", result.ok, result.message_ja)
    c.equal("覚えている", app.load_session_bpm(), "128")

    # 空欄は「指定しない」であって間違いではない
    result = app.assign(["/tmp/x.wav"], AssignForm(target_bpm=""))
    c.check("空欄でも通る", result.ok, result.message_ja)
    c.equal("空欄を覚える", app.load_session_bpm(), "")

    # 読めない置き場所でも落ちない（覚えられないだけ）
    app.session_path = Path("/nonexistent/dir/session.json")
    app.save_session_bpm("140")
    c.equal("読めなければ空", app.load_session_bpm(), "")

# AssignForm.bpm_value 単体
c.equal("空欄は None", AssignForm(target_bpm="").bpm_value(), (None, ""))
c.equal("空白だけも None", AssignForm(target_bpm="  ").bpm_value(), (None, ""))
c.equal("数字は通る", AssignForm(target_bpm="128").bpm_value()[0], 128)
c.equal("前後の空白は無視", AssignForm(target_bpm=" 90 ").bpm_value()[0], 90)
c.check("数字でなければ理由が付く", AssignForm(target_bpm="x").bpm_value()[1] != "")
c.check("範囲外も理由が付く", AssignForm(target_bpm="1").bpm_value()[1] != "")

# ==========================================================================
# 試聴 — **作者の別のアプリと同じ操作**（スペースで再生と停止）
# ==========================================================================

with tempfile.TemporaryDirectory() as tmp3:
    player = FakePlayer()
    app = make(tmp3, library=FakeLibrary([FakeEntry("/a.wav")]), player=player)
    c.check("試聴できる", app.can_preview)

    result = app.toggle_preview("/a.wav")
    c.check("再生できる", result.ok)
    c.equal("読み込んで再生する", player.calls, ["load", "play"])
    c.check("状態を読み上げる", "再生中" in result.message_ja, result.message_ja)

    # 同じファイルなら切り替え
    player.calls.clear()
    app.toggle_preview("/a.wav")
    c.equal("2 回目は切り替え", player.calls, ["toggle"])

    # 別のファイルなら読み直す
    player.calls.clear()
    app.toggle_preview("/b.wav")
    c.equal("別のファイルは読み直す", player.calls, ["load", "play"])

    # 選んでいなければ促す
    result = app.toggle_preview(None)
    c.check("選んでいなければ失敗", not result.ok)
    c.check("選ぶよう促す", "選んで" in result.message_ja, result.message_ja)

    # 止める
    player.calls.clear()
    app.stop_preview()
    c.equal("止められる", player.calls, ["stop"])

    # **読めなくても落ちない。**
    broken = make(tmp3, player=FakePlayer(fails=True))
    result = broken.toggle_preview("/a.wav")
    c.check("読めなければ失敗を返す", not result.ok)
    c.check("理由を添える", "読めません" in result.message_ja, result.message_ja)

    # プレイヤーが無くても落ちない
    class NoPlayer:
        pass

    silent = AppController(
        layout=SlotLayout(slots_dir=tmp3),
        library=FakeLibrary(),
        target_reader=lambda: (TARGET, "", ""),
        plugin_loader=lambda p, t: Outcome(True, ""),
        service=AssignService(
            SlotLedger.create(SlotLayout(slots_dir=tmp3), [PluginKind.SFORZANDO]),
            NullReload(),
        ),
        player=False,  # False は「注入したが使えない」を表す
    )
    silent._player = None
    c.check("プレイヤーが無ければ can_preview は False", not silent.can_preview)
    result = silent.toggle_preview("/a.wav")
    c.check("無ければ失敗を返す", not result.ok)
    c.check("何が要るかを言う", "just_playback" in result.message_ja, result.message_ja)
    silent.stop_preview()  # 落ちないこと

# ==========================================================================
# 素材に向いた配置
# ==========================================================================

with tempfile.TemporaryDirectory() as tmp4:
    lib = FakeLibrary(
        [FakeEntry("/loop.wav", "ループ", kind="loop"), FakeEntry("/one.wav", "単発")]
    )
    app = make(tmp4, library=lib)
    app.search(SearchForm())
    c.equal("ループの種別", app.result_kind(0), "loop")
    c.equal("範囲外は空", app.result_kind(9), "")

    # **配置は割り当てるその場で決める。** 一覧の選び直しの副作用に
    # していたときは、検索直後の先頭の項目に効かなかった
    # （`SetSelection` は `EVT_LISTBOX` を出さない）。
    auto = AssignForm()
    c.equal("既定は「素材に合わせる」", auto.mode, MODE_AUTO)

    mode, note = app.resolve_mode(["/loop.wav"], auto)
    c.equal("ループは速さを保つ", mode, MODE_PHRASE)
    c.check("決めたことを言う", "速さを保つ" in note, note)

    mode, note = app.resolve_mode(["/one.wav"], auto)
    c.equal("ワンショットは鍵盤全体", mode, MODE_CHROMATIC)
    c.check("これも言う", note, note)

    # **戻れること。** 片道だったときは、一度ループで寄せたあとに
    # ワンショットを選ぶと 1 発ものが 25 個も引き伸ばされた。
    mode, _ = app.resolve_mode(["/loop.wav"], auto)
    c.equal("直前がループでも独立して決まる", app.resolve_mode(["/one.wav"], auto)[0], MODE_CHROMATIC)

    mode, note = app.resolve_mode(["/loop.wav", "/one.wav"], auto)
    c.equal("2 個以上はドラムキット", mode, MODE_DRUMKIT)
    c.check("個数も言う", "2個" in note, note)

    # 自分で選んでいれば、そのまま使う
    fixed = AssignForm(mode=MODE_CHROMATIC)
    c.equal("自分で選んだ配置は変えない", app.resolve_mode(["/loop.wav"], fixed)[0], MODE_CHROMATIC)
    c.equal("そのときは何も言わない", app.resolve_mode(["/loop.wav"], fixed)[1], "")

    # 待たせる前に伝えられるか
    c.check("ループでは下ごしらえが要る", app.will_render(["/loop.wav"], auto))
    c.check("ワンショットでは要らない", not app.will_render(["/one.wav"], auto))

    # ライブラリに無いファイル（直接指定）は鍵盤全体
    c.equal("知らないファイルは鍵盤全体", app.resolve_mode(["/x/unknown.wav"], auto)[0], MODE_CHROMATIC)

# ==========================================================================
# 種別は長さで判定する — **作者の別のアプリと規則を揃える**
# ==========================================================================

with tempfile.TemporaryDirectory() as tmp5:
    # ファイル名は one_shot だが 8 秒ある → ループとして扱う。
    # **実測でワンショット判定 685 件のうち 227 件が 2 秒超だった。**
    lib = FakeLibrary(
        [
            FakeEntry("/long.wav", "長い素材", kind="one_shot", duration=8.0),
            FakeEntry("/short.wav", "短い素材", kind="one_shot", duration=0.5),
            FakeEntry("/fx.wav", "効果音の素材", kind="fx", duration=9.0),
        ]
    )
    app = make(tmp5, library=lib)

    app.search(SearchForm(kind="loop"))
    c.equal("長いワンショットはループ側に入る", len(app.results), 1)
    c.equal("それは長いほう", app.result_path(0), "/long.wav")

    app.search(SearchForm(kind="one_shot"))
    c.equal("ワンショットは短いものだけ", len(app.results), 1)
    c.equal("それは短いほう", app.result_path(0), "/short.wav")

    # **効果音は長さで覆さない。**
    app.search(SearchForm(kind="fx"))
    c.equal("長い効果音は効果音のまま", len(app.results), 1)
    c.equal("種別も効果音", app.result_kind(0), "fx")

    # **一覧の表示も判定し直したものを出す。**
    # そうしないと「ループで絞ったのにワンショットと読まれる」ことになる。
    app.search(SearchForm(kind="loop"))
    c.check("表示もループに直る", "ループ" in app.result_labels()[0], app.result_labels()[0])
    c.check("ワンショットとは読ませない", "ワンショット" not in app.result_labels()[0])

    # 条件なしなら全部出る
    app.search(SearchForm())
    c.equal("絞らなければ全部", len(app.results), 3)

# ==========================================================================
# パックの並び順
# ==========================================================================

with tempfile.TemporaryDirectory() as tmp6:
    # Big が最多、A small がいちばん新しい、という配置にする
    entries = (
        [FakeEntry(f"/big{i}.wav", pack="Big", mtime=100.0) for i in range(5)]
        + [FakeEntry("/small.wav", pack="A small", mtime=900.0)]
        + [
            FakeEntry("/mid1.wav", pack="Mid", mtime=500.0),
            FakeEntry("/mid2.wav", pack="Mid", mtime=200.0),
        ]
    )
    app = make(tmp6, library=FakeLibrary(entries))

    # **既定は中身の多い順。** 名前順だと大きなパックが埋もれる。
    c.equal("既定は多い順", app.pack_order, "count")
    c.equal("多い順に並ぶ", app.packs(), ["Big", "Mid", "A small"])

    result = app.cycle_pack_order()
    c.check("順送りできる", result.ok)
    c.check("どれにしたか言う", "名前順" in result.message_ja, result.message_ja)
    c.equal("名前順に並ぶ", app.packs(), ["A small", "Big", "Mid"])

    result = app.cycle_pack_order()
    c.check("次は更新の新しい順", "更新の新しい順" in result.message_ja, result.message_ja)
    # **新しい順。** 最近さわったパックを探すため。
    c.equal("新しい順に並ぶ", app.packs(), ["A small", "Mid", "Big"])

    result = app.cycle_pack_order()
    c.check("次は追加した順", "追加した順" in result.message_ja, result.message_ja)
    # **向きを読み上げに入れる。** 聞いただけで新旧どちらが上か分かるように。
    c.check("向きも言う", "古いもの" in result.message_ja, result.message_ja)
    # **古い順。** Big が最初（100）、A small が最後（900）。
    c.equal("古い順に並ぶ", app.packs(), ["Big", "Mid", "A small"])

    result = app.cycle_pack_order()
    c.check("一周して多い順へ", "多い順" in result.message_ja, result.message_ja)
    c.equal("また多い順", app.packs(), ["Big", "Mid", "A small"])

    # **既定以外にしてから確かめる。** 既定のままだと、覚えているのか
    # 単に既定へ戻っているのか区別が付かない。
    app.cycle_pack_order()

    # **覚える。** 次に開いたときも同じ並びで出す。
    app2 = make(tmp6, library=FakeLibrary(entries))
    c.equal("並び順を覚えている", app2.pack_order, "name")

    # テンポと並び順は**両方とも残る**（片方の保存で他方を消さない）
    app2.save_session_bpm("128")
    app3 = make(tmp6, library=FakeLibrary(entries))
    c.equal("テンポも残る", app3.load_session_bpm(), "128")
    c.equal("並び順も残る", app3.pack_order, "name")

# ==========================================================================
# セッションが変わったら、前のセッションの音を上書きしない
# ==========================================================================
#
# **これが無いと、別の曲で割り当てたときに前の曲の音が変わる。**
# Pro Tools の既定のトラック名（Inst1…）はどのセッションでも同じで、
# 台帳はトラック名でスロットを決めるため、同じスロットを掴む。
# sforzando はセッションにパスしか覚えていないので、開き直すと
# 後から書いた音が鳴る（2026-09-05 に実機のログで確認）。

with tempfile.TemporaryDirectory() as tmp7:
    def app_for(session):
        """本番と同じく、サービスを自分で組み立てる controller を作る。"""
        return AppController(
            layout=SlotLayout(slots_dir=tmp7),
            library=FakeLibrary([FakeEntry("/a.wav", "素材", duration=0.5)]),
            target_reader=lambda: (TARGET, "見つかりました", session),
            plugin_loader=lambda path, track: Outcome(True, ""),
            player=FakePlayer(),
        )

    a = app_for("260904_1")
    found = a.detect_target()
    c.equal("セッション名を拾う", a.session, "260904_1")
    c.check("読み上げに出す", "260904_1" in found.message_ja, found.message_ja)
    ok = a.assign(["/a.wav"], AssignForm())
    c.check("割り当てられる", ok.ok, ok.message_ja)
    path_a = a.last_written
    c.check("セッションのフォルダへ書く", "260904_1" in path_a, path_a)

    b = app_for("260825_1")
    b.detect_target()
    c.equal("別のセッション", b.session, "260825_1")
    ok = b.assign(["/a.wav"], AssignForm())
    c.check("こちらも割り当てられる", ok.ok, ok.message_ja)
    path_b = b.last_written
    c.check("別のファイルになる", path_a != path_b, f"{path_a} / {path_b}")
    c.check("前のセッションの sfz は残る", Path(path_a).is_file())
    c.check("台帳も別", a.ledger_path != b.ledger_path)

    # **下ごしらえは共有のまま。** 同じ素材を同じ倍率に伸ばしたものは
    # セッションが違っても同じ。1 回 90 メガバイトになるので複製できない。
    c.equal("下ごしらえは共有", a.layout.render_dir, b.layout.render_dir)

    # セッション名が読めないときは切り替えない。**空で切り替えると
    # 全セッション共有の置き場所へ落ち、上書きが復活する。**
    keep = a.ledger_path
    c.check("空文字では切り替えない", not a.use_session(""))
    c.equal("台帳はそのまま", a.ledger_path, keep)
    c.check("同じ名前でも切り替えない", not a.use_session("260904_1"))

    # テンポは曲ごとに覚える。
    # **読むのはセッションが決まったあと。** 起動直後はまだ名前が
    # 分からないので、画面側は `_sync_session()` で読み直している。
    a.save_session_bpm("128")
    b.save_session_bpm("90")

    def bpm_of(session):
        app = app_for(session)
        app.detect_target()
        return app.load_session_bpm()

    c.equal("A のテンポ", bpm_of("260904_1"), "128")
    c.equal("B のテンポ", bpm_of("260825_1"), "90")

    # パックの並び順はアプリ全体の好み。曲によらない。
    a.pack_order = "name"
    a.cycle_pack_order()
    c.equal("並び順はセッションをまたぐ", app_for("260825_1").pack_order, a.pack_order)


# ==========================================================================
# 2026-10-25 のレビューで直したこと
# ==========================================================================

import json
import sys
import unicodedata

import ui.controller as controller_mod
from integration.sforzando_log import SforzandoState
from ui.controller import loader_base_command, loader_command, tool_message

with tempfile.TemporaryDirectory() as tmp8:
    # --- 対応していないプラグイン ---
    #
    # Decent Sampler の窓を前にしたまま割り当てると、台帳に枠が無いので
    # 「空きスロットがありません」と、本当の理由と違うことを言っていた。
    decent = PluginTarget(plugin=PluginKind.DECENT_SAMPLER, track_name="Inst2")
    app = make(tmp8, target=decent)
    result = app.assign(["/tmp/x.wav"], AssignForm())
    c.check("Decent Sampler には割り当てない", not result.ok)
    c.check(
        "本当の理由を言う",
        "まだ割り当てられません" in result.message_ja,
        result.message_ja,
    )
    c.check(
        "空きスロットの話にしない",
        "空きスロット" not in result.message_ja,
        result.message_ja,
    )
    c.equal("何も書かない", app.last_written, None)

    # --- 読み込ませる道具の呼び方 ---
    #
    # **配布版の sys.executable は python ではない。** どちらの版も
    # app.py の --sforzando-load を通す（配布版でだけ壊れる道を作らない）。
    head = loader_base_command()
    c.equal("自分の python で起こす", head[0], sys.executable)
    c.check("app.py を通す", head[1].endswith("app.py"), str(head))
    c.equal("入口の印", head[-1], "--sforzando-load")
    cmd = loader_command("/s/slot01.sfz", "Inst1")
    c.equal("トラックを渡す", cmd[-4:], ["import", "/s/slot01.sfz", "--track", "Inst1"])
    c.check("トラックが無ければ付けない", "--track" not in loader_command("/s/a.sfz", ""))

    # 道具の言うことは、そのまま読み上げに使う
    c.equal(
        "最後の MESSAGE 行を拾う",
        tool_message("トラック「Inst1」\nMESSAGE\t前の文\n途中\nMESSAGE\t後の文\n"),
        "後の文",
    )
    c.equal("無ければ空", tool_message("何かの出力\n"), "")

    # --- 監視しているかの判断は、濁点の分かれ方（NFD）をそろえて比べる ---
    #
    # Cocoa を通ったパス（sforzando のログ）は NFD になることがある。
    # 比べ損ねると、監視されているのに「いま必要です」と言い続ける。
    app = make(tmp8)
    nfc = str(Path(tmp8) / "セッション・ブー" / "slot01.sfz")
    app.last_written = unicodedata.normalize("NFC", nfc)
    nfd = unicodedata.normalize("NFD", nfc)
    c.check("NFC と NFD は文字列として違う", nfc != nfd)
    saved_read_states = controller_mod.read_states
    try:
        controller_mod.read_states = lambda: {nfd: SforzandoState(sfz_path=nfd, watching=True)}
        c.check("NFD のログでも監視中と分かる", not app.needs_loading())
        controller_mod.read_states = lambda: {nfd: SforzandoState(sfz_path=nfd, watching=False)}
        c.check("監視が止まっていれば要る", app.needs_loading())
        controller_mod.read_states = lambda: {}
        c.check("ログが無ければ要る（押させるほうへ倒す）", app.needs_loading())
    finally:
        controller_mod.read_states = saved_read_states

    # --- 索引が無いときの言い方 ---
    #
    # **初めて使う人は、まだ索引を持っていない。** 「読めません。ファイルを
    # 直接指定してください」とだけ言っていたので、作れば済むことが伝わらなかった。
    saved_index = controller_mod.splice_index_path
    saved_ptcore = controller_mod.load_ptcore
    try:
        controller_mod.splice_index_path = lambda d: str(Path(d) / "無い索引.json")
        fresh = AppController(
            layout=SlotLayout(slots_dir=tmp8),
            target_reader=lambda: (TARGET, "", ""),
            plugin_loader=lambda p, t: Outcome(True, ""),
            player=FakePlayer(),
        )
        result = fresh.search(SearchForm(text="kick"))
        c.check("索引が無ければ失敗", not result.ok)
        c.check(
            "作り方を言う",
            "コマンド+R" in result.message_ja,
            result.message_ja,
        )
        controller_mod.load_ptcore = lambda name: None
        parts_missing = AppController(
            layout=SlotLayout(slots_dir=tmp8),
            target_reader=lambda: (TARGET, "", ""),
            plugin_loader=lambda p, t: Outcome(True, ""),
            player=FakePlayer(),
        )
        result = parts_missing.search(SearchForm(text="kick"))
        c.check(
            "部品が無いときは、そう言う",
            "部品が見つかりません" in result.message_ja,
            result.message_ja,
        )
    finally:
        controller_mod.splice_index_path = saved_index
        controller_mod.load_ptcore = saved_ptcore

    # --- Splice のフォルダを選び直す ---
    splice = Path(tmp8) / "MySplice"
    (splice / "sounds" / "packs").mkdir(parents=True)
    app = make(tmp8)
    result = app.set_splice_root(str(splice))
    c.check("選び直せる", result.ok, result.message_ja)
    c.equal(
        "Splice のフォルダを選んでも、パックの並ぶフォルダを使う",
        app.splice_root,
        splice / "sounds" / "packs",
    )
    saved = json.loads((Path(tmp8) / "session.json").read_text(encoding="utf-8"))
    c.equal("覚える（アプリ全体の設定）", saved.get("splice_root"), str(splice / "sounds" / "packs"))
    c.equal("前のフォルダの検索結果は捨てる", app.results, [])
    again = make(tmp8)
    c.equal("次に開いたときも同じ", again.splice_root, splice / "sounds" / "packs")
    c.check("無いフォルダは断る", not app.set_splice_root(str(Path(tmp8) / "無い")).ok)

    # 無いフォルダの索引は作らない（「0 件」と言うだけで、何が悪いのか分からない）
    nowhere = make(tmp8)
    nowhere._splice_choice = str(Path(tmp8) / "どこにも無い")
    result = nowhere.rescan_library()
    c.check("無いフォルダは数えない", not result.ok)
    c.check(
        "選び直し方を言う",
        "Splice のフォルダを選ぶ" in result.message_ja,
        result.message_ja,
    )


# ==========================================================================
# 検索語とパックの照合（2026-10-25）
# ==========================================================================

import unicodedata as _ud

with tempfile.TemporaryDirectory() as tmp9:
    nfd_name = _ud.normalize("NFD", "ドラム_ループ_90.wav")
    lib = FakeLibrary(
        [
            FakeEntry("/k.wav", filename="Kick_Hard.wav", pack="Trap"),
            FakeEntry("/d.wav", filename=nfd_name, pack="Trap Vol. 2"),
            FakeEntry("/s.wav", filename="Snare.wav", pack="Trap", description="crisp"),
        ]
    )
    app = make(tmp9, library=lib)

    # **日本語入力のまま打った全角でも見つかる。**
    result = app.search(SearchForm(text="ｋｉｃｋ"))
    c.equal("全角の語でも見つかる", [e.path for e in app.results], ["/k.wav"])
    # **Finder が作った NFD の名前も、打った NFC の語で見つかる。**
    result = app.search(SearchForm(text="ドラム"))
    c.equal("NFD の名前も見つかる", [e.path for e in app.results], ["/d.wav"])
    result = app.search(SearchForm(text="trap snare"))
    c.equal("語は全部含むものだけ（パック名も見る）", [e.path for e in app.results], ["/s.wav"])
    result = app.search(SearchForm(text="CRISP"))
    c.equal("説明も見る。大文字小文字は区別しない", [e.path for e in app.results], ["/s.wav"])

    # **パックは名前が同じものだけ。** ライブラリは部分一致で絞るので、
    # 「Trap」を選ぶと「Trap Vol. 2」まで混ざっていた。
    result = app.search(SearchForm(pack="Trap"))
    c.equal(
        "似た名前のパックを混ぜない",
        sorted(e.path for e in app.results),
        ["/k.wav", "/s.wav"],
    )

raise SystemExit(c.summary())
