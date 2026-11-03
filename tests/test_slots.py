"""slots.py のテスト。スロット台帳の割り当てと永続化。

台帳はプラグイン側から問い合わせられない情報を持つ「ただ一つの正」なので、
割り当て先を決める分岐を全部通しておく。
"""

from _harness import Checker

from core.mapping import MODE_CHROMATIC, MODE_DRUMKIT, build_chromatic, build_drumkit
from core.slots import (
    PluginKind,
    SlotAssignment,
    SlotError,
    SlotLayout,
    SlotLedger,
    slot_number_from_setting_name,
)

c = Checker("slots")

SFZ = PluginKind.SFORZANDO
DS = PluginKind.DECENT_SAMPLER

# --- PluginKind ---
c.equal("台帳に保存する値は安定した文字列", SFZ.value, "sforzando")
c.equal("読み上げは日本語", SFZ.label_ja, "スフォルツァンド")
c.equal("sforzando の拡張子は sfz", SFZ.file_extension, "sfz")
c.equal("Decent Sampler の拡張子は dspreset", DS.file_extension, "dspreset")
c.check("全種別に表示名がある", all(k.display_name for k in PluginKind))
c.check("全種別に設定フォルダ名がある", all(k.settings_folder for k in PluginKind))

# --- SlotLayout ---
layout = SlotLayout(slots_dir="/Volumes/Audio/sfz_slots", slot_count=4)
c.equal("ファイル名は 2 桁ゼロ埋め", layout.filename(1, SFZ), "slot01.sfz")
c.equal("プラグインで拡張子が変わる", layout.filename(1, DS), "slot01.dspreset")
c.equal(
    "絶対パスを組み立てる",
    layout.path(3, SFZ),
    "/Volumes/Audio/sfz_slots/slot03.sfz",
)
c.equal("設定名", layout.setting_name(3), "SLOT_03")
c.equal("番号の一覧", layout.numbers(), [1, 2, 3, 4])
c.raises("範囲外のスロット番号", SlotError, layout.filename, 5, SFZ)
c.raises("0 番は無い", SlotError, layout.setting_name, 0)
c.raises("相対パスは不可", SlotError, lambda: SlotLayout(slots_dir="sfz_slots"))
c.raises("末尾スラッシュは不可", SlotError, lambda: SlotLayout(slots_dir="/a/b/"))
c.raises("slot_count 0 は不可", SlotError, lambda: SlotLayout(slot_count=0))
c.raises("slot_count 1000 は不可", SlotError, lambda: SlotLayout(slot_count=1000))
c.raises("setting_prefix は空にできない", SlotError, lambda: SlotLayout(setting_prefix=" "))

# パス長を揃える制約が無いことの確認（旧方式との違い）
long_layout = SlotLayout(slot_count=120)
c.check(
    "3 桁になってもパス長を揃えなくてよい",
    long_layout.filename(120, SFZ) == "slot120.sfz",
)

# --- SlotAssignment ---
slot = SlotAssignment(number=1, plugin=SFZ)
c.check("初期状態は未結び付き", slot.is_free)
c.check("初期状態は中身なし", not slot.has_content)
c.check("未割り当てと読み上げる", "未割り当て" in slot.describe_ja())

slot.track_name = "Inst 1"
c.check("結び付いたら is_free は False", not slot.is_free)
c.check("トラック名を読み上げる", "Inst 1" in slot.describe_ja())

c.equal(
    "辞書へ出して戻せる",
    SlotAssignment.from_dict(slot.to_dict()),
    slot,
)

# --- 台帳の生成 ---
ledger = SlotLedger.create(layout, plugins=[SFZ])
c.equal("スロット数だけ作られる", len(ledger.slots_of(SFZ)), 4)
c.equal("別プラグインは空", ledger.slots_of(DS), [])
c.raises("無い番号は取れない", SlotError, ledger.get, SFZ, 99)
c.check("未初期化の要約", "未初期化" in SlotLedger().summary_ja())

# --- resolve: 空きスロットへ新規に結び付ける ---
first = ledger.resolve(SFZ, "Inst 1")
c.equal("最小番号が使われる", first.number, 1)
c.equal("トラック名が記録される", first.track_name, "Inst 1")

second = ledger.resolve(SFZ, "Inst 2")
c.equal("次は 2 番", second.number, 2)

# --- resolve: トラック名で既存を引く ---
again = ledger.resolve(SFZ, "Inst 1")
c.equal("同じトラックなら同じスロット", again.number, 1)
c.equal("大文字小文字を無視する", ledger.resolve(SFZ, "inst 1").number, 1)
c.equal("前後の空白を無視する", ledger.resolve(SFZ, "  Inst 1  ").number, 1)

# --- resolve: known_number は台帳より優先 ---
forced = ledger.resolve(SFZ, "Inst 1", known_number=4)
c.equal("設定名から分かった番号を優先する", forced.number, 4)
c.equal("そのスロットにトラック名を移す", forced.track_name, "Inst 1")

# --- resolve: 異常系 ---
c.raises("空のトラック名は拒む", SlotError, ledger.resolve, SFZ, "   ")

full = SlotLedger.create(SlotLayout(slot_count=1), plugins=[SFZ])
full.resolve(SFZ, "Inst 1")
c.raises("空きが尽きたら知らせる", SlotError, full.resolve, SFZ, "Inst 2")

# --- assign: クロマティック ---
ledger2 = SlotLedger.create(layout, plugins=[SFZ])
target = ledger2.resolve(SFZ, "Inst 1")
inst = build_chromatic("/a/Vox Chop.wav", 65, name="Vox Chop")
ledger2.assign(target, inst)
c.equal("種別が記録される", target.mode, MODE_CHROMATIC)
c.equal("サンプル数は 1", target.sample_count, 1)
c.equal("ルートキーが記録される", target.root_key, 65)
c.check("中身ありになる", target.has_content)
c.check("要約が入る", "Vox Chop" in target.summary_ja, target.summary_ja)
c.check("読み上げにルートキーが出る", "F3" in target.describe_ja(), target.describe_ja())

# --- assign: ドラムキット ---
kit_slot = ledger2.resolve(SFZ, "Inst 2")
kit = build_drumkit(["/a/kick.wav", "/a/snare.wav", "/a/hat.wav"])
ledger2.assign(kit_slot, kit)
c.equal("種別はドラムキット", kit_slot.mode, MODE_DRUMKIT)
c.equal("サンプル数は 3", kit_slot.sample_count, 3)
c.equal("開始ノートが入る", kit_slot.root_key, 36)
c.check("個数を読み上げる", "3個" in kit_slot.describe_ja(), kit_slot.describe_ja())

# --- release ---
ledger2.release(SFZ, target.number)
c.check("解除すると未結び付きへ戻る", target.is_free)
c.check("中身も消える", not target.has_content)
c.equal("要約も消える", target.summary_ja, "")

# --- 経路 ---
c.equal(
    "定義ファイルのパスを引ける",
    ledger2.path_for(kit_slot),
    f"/Volumes/Audio/sfz_slots/slot{kit_slot.number:02d}.sfz",
)
c.equal("設定名を引ける", ledger2.setting_name_for(kit_slot), f"SLOT_{kit_slot.number:02d}")

# --- 永続化 ---
restored = SlotLedger.from_json(ledger2.to_json())
c.equal("配置設定が戻る", restored.layout, ledger2.layout)
c.equal("割り当ても戻る", restored.assignments, ledger2.assignments)
c.check(
    "JSON に日本語がそのまま入る（ensure_ascii=False）",
    "\\u" not in ledger2.to_json(),
)
c.raises(
    "未対応バージョンは拒む",
    SlotError,
    SlotLedger.from_json,
    '{"version": 99, "assignments": []}',
)

# --- 要約 ---
summary = ledger2.summary_ja()
c.check("使用中の数を伝える", "使用中" in summary, summary)

# --- 設定名からの逆算 ---
c.equal("SLOT_03 は 3 番", slot_number_from_setting_name("SLOT_03", layout), 3)
c.equal("拡張子付きでも読める", slot_number_from_setting_name("SLOT_03.tfx", layout), 3)
c.equal("大文字小文字を無視", slot_number_from_setting_name("slot_03", layout), 3)
c.equal("前後の空白を無視", slot_number_from_setting_name("  SLOT_03 ", layout), 3)
c.equal("範囲外は None", slot_number_from_setting_name("SLOT_99", layout), None)
c.equal("無関係な名前は None", slot_number_from_setting_name("My Preset", layout), None)

# ==========================================================================
# セッションごとに分ける（2026-09-05）
# ==========================================================================
#
# **分けないと、別のセッションで割り当てたときに前のセッションの音を
# 上書きする。** Pro Tools の既定のトラック名（Inst1…）はどのセッションでも
# 同じで、台帳はトラック名でスロットを決めるため、同じスロットを掴む。
# sforzando はセッションにパスしか覚えていないので、開き直すと
# 後から書いた音が鳴る（2026-09-05 に実機のログで確認）。

from core.slots import sanitize_session

plain = SlotLayout(slots_dir="/x/sfz_slots")
sess_a = SlotLayout(slots_dir="/x/sfz_slots", session="260904_1")
sess_b = SlotLayout(slots_dir="/x/sfz_slots", session="260825_1")

c.equal("セッション名が無ければ根に置く", plain.path(1, SFZ), "/x/sfz_slots/slot01.sfz")
c.equal(
    "セッションごとにフォルダを分ける",
    sess_a.path(1, SFZ),
    "/x/sfz_slots/260904_1/slot01.sfz",
)
c.check(
    "別のセッションは別のファイル",
    sess_a.path(1, SFZ) != sess_b.path(1, SFZ),
)
c.equal("台帳もセッションごと", sess_a.ledger_path, "/x/sfz_slots/260904_1/ledger.json")

# **下ごしらえは共有。** 同じ素材を同じ倍率に伸ばしたファイルは
# セッションが違っても同じ。1 回 90 メガバイトになるので複製できない。
c.equal("下ごしらえは根の下", sess_a.render_dir, "/x/sfz_slots/rendered")
c.equal("どのセッションでも同じ", sess_a.render_dir, sess_b.render_dir)
c.equal("セッション無しでも同じ", plain.render_dir, sess_a.render_dir)

# フォルダ名に使えない文字は潰す。**上の階層へ出さない。**
c.equal("区切りは潰す", sanitize_session("a/b"), "a_b")
c.equal("上へ出られない", sanitize_session("../evil"), "_evil")
c.equal("空白だけなら空", sanitize_session("   "), "")
c.equal("点だけなら空", sanitize_session("."), "")
c.equal("そのまま使える名前は変えない", sanitize_session("260904_1"), "260904_1")
c.equal(
    "危ない名前でも根より下に留まる",
    SlotLayout(slots_dir="/x/sfz_slots", session="../../etc").session_dir,
    "/x/sfz_slots/_.._etc",
)

# **台帳を読み戻してもセッションが残ること。**
# 残さないと、2 回目以降の割り当てが全セッション共有の場所へ書かれる
# （2026-09-05 に実際に踏んだ）。
round_trip = SlotLedger.from_json(
    SlotLedger.create(sess_a, plugins=[SFZ]).to_json()
)
c.equal("セッション名が往復する", round_trip.layout.session, "260904_1")
c.equal(
    "読み戻したパスも同じ",
    round_trip.layout.path(1, SFZ),
    "/x/sfz_slots/260904_1/slot01.sfz",
)

raise SystemExit(c.summary())
