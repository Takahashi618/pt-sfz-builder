"""service.py のテスト。実行層の全経路を実ファイルで通す。

`SlotLayout` が Windows の絶対パスも受けるので、一時ディレクトリを使って
**本当に書き込むところまで**確かめられる。AppleScript だけスタブにする。
"""

import tempfile
from pathlib import Path

from _harness import Checker

from core.assign import AssignRequest, SampleRef
from core.slots import PluginKind, SlotLayout, SlotLedger
from core.target import PluginTarget
from integration.reloader import NullReload, ReloadOutcome, ReloadResult
from integration.service import AssignService, load_ledger, save_ledger

c = Checker("service")

SFZ = PluginKind.SFORZANDO
TARGET = PluginTarget(plugin=SFZ, track_name="Inst1")
VOX = SampleRef("/Volumes/Audio/Splice/Karra Vox Chop 120bpm Cmin.wav")


class StubTrigger:
    """再読込を差し替える。渡された内容を記録する。"""

    def __init__(self, result: ReloadResult) -> None:
        self.result = result
        self.calls: list = []

    def reload(self, request):
        self.calls.append(request)
        return self.result


def posix(path: Path) -> str:
    """Windows のパスを区切り記号だけ揃えて渡す。"""
    return str(path).replace("\\", "/")


with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)
    slots_dir = tmp / "sfz_slots"
    layout = SlotLayout(slots_dir=posix(slots_dir), slot_count=4)
    ledger_path = tmp / "ledger.json"

    # --- 正常系 ---
    trigger = StubTrigger(ReloadResult(ReloadOutcome.DONE, "SLOT_01 を選び直して反映しました。"))
    service = AssignService(
        SlotLedger.create(layout, [SFZ]), trigger, ledger_path=ledger_path
    )
    outcome = service.assign(AssignRequest(target=TARGET, samples=[VOX]))

    c.check("成功する", outcome.ok, outcome.describe_ja())
    c.check("書き込み先が返る", outcome.written_path is not None)

    written = Path(outcome.written_path)
    c.check("ファイルが実際にできる", written.is_file())
    c.equal("スロット 1 のファイル名", written.name, "slot01.sfz")

    body = written.read_text(encoding="utf-8")
    c.check("ルートキーが入る", "pitch_keycenter=60" in body)
    c.check("サンプルのパスが入る", VOX.path in body)
    c.check("sample= は行の最後", body.rstrip().endswith(VOX.path))
    c.equal("改行は LF", written.read_bytes().count(b"\r\n"), 0)

    c.check("台帳が保存される", ledger_path.is_file())
    c.equal("再読込が 1 回呼ばれる", len(trigger.calls), 1)
    c.equal("設定名が渡る", trigger.calls[0].setting_name, "SLOT_01")
    c.equal("パスが渡る", trigger.calls[0].file_path, str(written))
    c.check("完了を過去形で伝える", "割り当てました" in outcome.message_ja, outcome.message_ja)
    c.check("再読込の結果も伝える", "反映しました" in outcome.message_ja)
    # **ルートキーをどう決めたかは言う**（2026-10-25）。既定値に落ちたときの
    # 「鳴らして確かめてください」が、以前は割り当ての結果で消えていた。
    c.equal(
        "ルートキーの決め方だけを言う",
        outcome.notes,
        ("ルートキー C3。ファイル名のCマイナーから決めました。",),
    )
    c.check(
        "警告は無い",
        not any("[警告]" in note for note in outcome.notes),
        str(outcome.notes),
    )

    # --- 計画の段階で止まれば何も書かない ---
    before = sorted(p.name for p in slots_dir.iterdir())
    outcome = service.assign(
        AssignRequest(target=TARGET, samples=[SampleRef("/a/loop.mp3")])
    )
    c.check("中止される", not outcome.ok)
    c.equal("ファイルは増えない", sorted(p.name for p in slots_dir.iterdir()), before)
    c.check("理由を伝える", "mp3" in outcome.message_ja, outcome.message_ja)

    # --- 再読込に失敗しても、書けていれば成功扱い ---
    failing = StubTrigger(
        ReloadResult(ReloadOutcome.FAILED, "[警告] 選び直せませんでした。", detail="no window")
    )
    service2 = AssignService(SlotLedger.create(layout, [SFZ]), failing)
    outcome = service2.assign(AssignRequest(target=TARGET, samples=[VOX]))
    c.check("書けていれば成功", outcome.ok, outcome.describe_ja())
    c.check("失敗を注意に載せる", any("[警告]" in n for n in outcome.notes), str(outcome.notes))
    c.check("完了報告はする", "割り当てました" in outcome.message_ja)

    # --- 既定は FolderWatchReload ---
    # sforzando が置き場所を監視していて、書き換えれば自動で読み直す
    # （2026-09-04 実機確認）。**こちらからトリガーを撃つ必要が無い。**
    service3 = AssignService(SlotLedger.create(layout, [SFZ]))
    outcome = service3.assign(AssignRequest(target=TARGET, samples=[VOX]))
    c.check("トリガー無しでも書ける", outcome.ok)
    c.equal("反映されたとみなす", outcome.reload.outcome, ReloadOutcome.DONE)
    c.check("自動で反映されると伝える", "自動で反映" in outcome.describe_ja(), outcome.describe_ja())
    # **「選び直してください」と言わない。** 実際には要らないので、
    # 言うと利用者に無駄な操作をさせることになる。
    c.check("選び直しを促さない", "選び直す" not in outcome.describe_ja())

    # 明示的に NullReload を渡せば、従来どおり「選び直し」を促す
    service3b = AssignService(SlotLedger.create(layout, [SFZ]), NullReload())
    outcome = service3b.assign(AssignRequest(target=TARGET, samples=[VOX]))
    c.equal("NullReload なら何もしない", outcome.reload.outcome, ReloadOutcome.SKIPPED)
    c.check("こちらは選び直しを促す", "選び直す" in outcome.describe_ja())

    # --- 台帳を保存できなくても割り当ては効く ---
    blocked_ledger = tmp / "ledger_dir"
    blocked_ledger.mkdir()
    service4 = AssignService(
        SlotLedger.create(layout, [SFZ]), ledger_path=blocked_ledger
    )
    outcome = service4.assign(AssignRequest(target=TARGET, samples=[VOX]))
    c.check("書き込みは成功する", outcome.ok, outcome.describe_ja())
    c.check("台帳の失敗を警告する", any("台帳" in n for n in outcome.notes), str(outcome.notes))

    # --- 下ごしらえに失敗したら台帳を動かさない ---
    #
    # **ffmpeg も rubberband も無い Mac は現実にある。** そこで
    # 「速さを保つ」を選ぶと下ごしらえが失敗する。以前は台帳だけが
    # 割り当て済みになり、`.sfz` の無いスロットが使用中として残った
    # （Cmd+Shift+L が実体の無い音色を読み上げ、次の割り当ては
    # そのスロットを飛ばす）。

    from core.mapping import MODE_PHRASE
    from integration.render import RenderResult

    failing = SlotLedger.create(layout, [SFZ])
    ledger_file = tmp / "phrase_ledger.json"
    service_r = AssignService(
        failing,
        NullReload(),
        ledger_path=ledger_file,
        renderer=lambda renders, progress=None: RenderResult(
            False, message_ja="[エラー] ffmpeg も rubberband も入っていません。"
        ),
    )
    outcome = service_r.assign(
        AssignRequest(target=TARGET, samples=[VOX], mode=MODE_PHRASE)
    )
    c.check("下ごしらえに失敗したら中止", not outcome.ok)
    c.check("理由を読み上げる", "ffmpeg" in outcome.message_ja, outcome.message_ja)
    c.check(
        "sfz は書かれない",
        not (Path(layout.path(1, SFZ))).is_file()
        or Path(layout.path(1, SFZ)).read_text(encoding="utf-8") != outcome.plan.sfz_text,
    )
    c.equal("台帳のトラック名は空のまま", failing.get(SFZ, 1).track_name, None)
    c.equal("台帳の種別も空のまま", failing.get(SFZ, 1).mode, None)
    c.check("スロットは空きのまま", failing.get(SFZ, 1).is_free)
    c.check("台帳も保存されない", not ledger_file.is_file())

    # 同じスロットへ次の割り当てが入れる（焦げ付かない）
    service_r2 = AssignService(failing, NullReload(), ledger_path=ledger_file)
    ok2 = service_r2.assign(AssignRequest(target=TARGET, samples=[VOX]))
    c.check("次の割り当ては通る", ok2.ok, ok2.describe_ja())
    c.equal("同じスロット 1 を使う", ok2.plan.slot.number, 1)

    # --- 書き込みに失敗したら中止 ---
    blocker = tmp / "blocked"
    blocker.write_text("x", encoding="utf-8")
    bad_layout = SlotLayout(slots_dir=posix(blocker), slot_count=2)
    service5 = AssignService(SlotLedger.create(bad_layout, [SFZ]))
    outcome = service5.assign(AssignRequest(target=TARGET, samples=[VOX]))
    c.check("書けなければ中止", not outcome.ok)
    c.check("エラー接頭辞", outcome.message_ja.startswith("[エラー]"), outcome.message_ja)

    # --- 解除 ---
    outcome = service.release(SFZ, 1)
    c.check("解除できる", outcome.ok)
    c.check("解除したと伝える", "解除しました" in outcome.message_ja, outcome.message_ja)
    c.check("台帳から外れる", service.ledger.get(SFZ, 1).is_free)
    c.check("ファイルは消さない", written.is_file())

    # --- 台帳の読み書き ---
    fresh = load_ledger(tmp / "nothere.json", layout=layout, plugins=[SFZ])
    c.equal("無ければ新規に作る", len(fresh.slots_of(SFZ)), 4)

    saved_path = tmp / "saved.json"
    save_ledger(fresh, saved_path)
    c.check("保存できる", saved_path.is_file())
    c.equal("読み戻せる", load_ledger(saved_path).assignments, fresh.assignments)

    broken = tmp / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    c.raises("壊れていれば知らせる（黙って作り直さない）", ValueError, load_ledger, broken)

    # --- 台帳を置いた場所のセッションを優先する ---
    #
    # **台帳の中身と、置かれているフォルダが食い違うことがある**
    # （セッション名を残す前に書かれた台帳、フォルダごと写した台帳）。
    # 食い違ったまま使うと、別のセッションのスロットを書き換える。
    old_layout = SlotLayout(slots_dir=posix(tmp), slot_count=2)  # session 無し
    stale = tmp / "260904_1" / "ledger.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    save_ledger(SlotLedger.create(old_layout, [SFZ]), stale)

    wanted = SlotLayout(slots_dir=posix(tmp), slot_count=2, session="260904_1")
    loaded = load_ledger(stale, layout=wanted, plugins=[SFZ])
    c.equal("置いた場所のセッションになる", loaded.layout.session, "260904_1")
    c.check(
        "書き込み先もそのフォルダ",
        loaded.layout.path(1, SFZ).endswith("/260904_1/slot01.sfz"),
        loaded.layout.path(1, SFZ),
    )


    # --- 台帳を置いた場所も、いま使っている場所を優先する（2026-10-25）---
    #
    # 台帳には書いたときの置き場所（絶対パス）が入っている。フォルダごと
    # 動かした台帳をそのまま使うと、`.sfz` を元の場所へ書きに行き、
    # いま sforzando が見ている場所には何も届かない。
    moved_from = SlotLayout(slots_dir="/Volumes/古いドライブ/sfz_slots", slot_count=2)
    moved = tmp / "moved" / "ledger.json"
    moved.parent.mkdir(parents=True, exist_ok=True)
    save_ledger(SlotLedger.create(moved_from, [SFZ]), moved)
    here = SlotLayout(slots_dir=posix(tmp / "moved"), slot_count=2)
    loaded = load_ledger(moved, layout=here, plugins=[SFZ])
    c.equal("いまの置き場所になる", loaded.layout.slots_dir, here.slots_dir)
    c.check(
        "書き込み先もいまの置き場所",
        loaded.layout.path(1, SFZ).startswith(here.slots_dir),
        loaded.layout.path(1, SFZ),
    )
    c.equal("スロットの数は台帳のまま", loaded.layout.slot_count, 2)

raise SystemExit(c.summary())
