"""英語の画面で出る文言を集めて JSON で出す（tests/test_i18n.py が別のプロセスで動かす）。

言語は起動したときに決まるので、`SFZBUILDER_LANG=en` を付けて新しいプロセスで動かす。
窓は出さない。Pro Tools にもつながない。スロットは一時フォルダ。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SM_SILENT", "1")
os.environ.setdefault("SM_NO_ANNOUNCE", "1")

from app import _EmptyLibrary  # noqa: E402


class _Library(_EmptyLibrary):
    def scan(self):
        return {"total": 1, "parsed": 1, "unreadable": 1}

    def load(self, quiet=True):
        return True


def _widgets(parent) -> list[str]:
    texts: list[str] = []
    for child in parent.GetChildren():
        texts += [child.GetName(), child.GetLabel()]
        if hasattr(child, "GetStrings"):
            texts += list(child.GetStrings())
        texts += _widgets(child)
    return texts


def collect(tmp: Path) -> dict[str, list[str]]:
    import wx

    from core import i18n, phrase, rootkey, sibling, tempo, tone
    from core.assign import AssignRequest, SampleRef, plan_assignment
    from core.mapping import MODE_CHROMATIC, MODE_DRUMKIT, MODE_PHRASE
    from core.slots import PluginKind, SlotLayout
    from core.target import PluginTarget
    from integration import axread, reloader, render, sforzando_log
    from ui import borrowed
    from ui.assign_dialog import SPANS, AssignDialog
    from ui.controller import MODE_LABELS, AppController, AssignForm, SearchForm, summary_en
    from ui.keys_dialog import KEY_HELP, KeysDialog, key_rows
    from ui.main_frame import MainFrame, _version_text

    out: dict[str, list[str]] = {"lang": [i18n.LANG]}
    app = wx.App(False)

    target = PluginTarget(track_name="Inst1", plugin=PluginKind.SFORZANDO)
    c = AppController(
        layout=SlotLayout(slots_dir=str(tmp)),
        library=_Library(),
        target_reader=lambda: (target, target.describe_ja(), "song"),
        plugin_loader=lambda _p, _t: SimpleNamespace(ok=True, message_ja=""),
        # **本物の再生部品は作らない**（音の装置を開いてしまう）
        player=borrowed._player.PreviewPlayer(borrowed._player.NullBackend()),
    )

    # --- 窓の部品 ---------------------------------------------------------
    frame = MainFrame(c)
    bar = frame.GetMenuBar()
    out["window"] = [frame.GetTitle()]
    out["menus"] = [bar.GetMenuLabelText(i) for i in range(bar.GetMenuCount())]
    out["menu_items"] = [
        text
        for i in range(bar.GetMenuCount())
        for item in bar.GetMenu(i).GetMenuItems()
        if not item.IsSeparator()
        for text in (item.GetItemLabelText(), item.GetHelp())
    ]
    out["widgets"] = [t for t in _widgets(frame) if t]
    out["summary"] = [frame._settings_summary(), _version_text()]
    dialog = AssignDialog(frame, AssignForm())
    out["settings"] = [t for t in _widgets(dialog) if t] + [dialog.GetTitle()]
    dialog.Destroy()
    keys = KeysDialog(frame)
    out["keys"] = [t for t in _widgets(keys) if t] + key_rows() + [keys.GetTitle()]
    keys.Destroy()
    out["key_table"] = [text for row in KEY_HELP for text in row]

    # --- 操作の結果 -------------------------------------------------------
    results = [
        c.search(SearchForm(text="bass", key="C", relative=True, bpm="120", kind="loop", pack="P")),
        c.search(SearchForm(bpm="x")),
        c.search(SearchForm()),
        c.toggle_preview(None),
        c.toggle_preview("/Volumes/Audio/a.wav"),
        c.assign([], AssignForm()),
        c.load_into_plugin(),
        c.rescan_library(),
        c.set_splice_root(str(tmp / "missing")),
        c.set_splice_root(str(tmp)),
        c.unused_renders_ja(),
        c.clean_renders(),
    ]
    for _ in range(4):
        results.append(c.cycle_pack_order())
    c.target = None
    results.append(c.detect_target())
    results.append(c.assign(["/Volumes/Audio/a.wav"], AssignForm(mode=MODE_CHROMATIC)))
    results.append(c.assign(["/Volumes/Audio/a.wav", "/Volumes/Audio/b.wav"], AssignForm(mode=MODE_DRUMKIT)))
    results.append(c.assign(["/Volumes/Audio/a.mp3"], AssignForm(mode=MODE_CHROMATIC)))
    results.append(c.assign(["/Volumes/Audio/c.wav"], AssignForm(target_bpm="x")))
    results.append(c.assign(["/Volumes/Audio/c.wav"], AssignForm(root_key="?")))
    results.append(c.assign(["/Volumes/Audio/Loop 120.wav"], AssignForm(mode=MODE_CHROMATIC, target_bpm="90")))
    out["controller"] = [r.message_ja for r in results]
    out["controller"] += [
        c.slot_summary_ja(),
        c.stretch_backend_ja(),
        c.wait_note_ja(["/x.wav"], AssignForm(mode=MODE_PHRASE)),
        c.resolve_mode(["/a.wav", "/b.wav"], AssignForm())[1],
        c.resolve_mode(["/a.wav"], AssignForm())[1],
        AssignForm(target_bpm="x").bpm_value()[1],
        AssignForm(target_bpm="999").bpm_value()[1],
    ]
    out["labels"] = list(MODE_LABELS.values()) + [name for name, _ in SPANS]
    out["summary_en"] = [
        summary_en(SimpleNamespace(description="Bass", bpm=120, key="C", key_quality="minor", kind="loop", duration=2.0)),
        summary_en(SimpleNamespace(filename="kick.wav", bpm=None, key=None, kind="", duration=None)),
    ]

    # --- 文を組み立てるところ ---------------------------------------------
    out["tone"] = list(tone.PRESETS) + [t.describe_ja() for t in tone.PRESETS.values()]
    out["tone"].append(tone.ToneSettings(attack=1.0, fil_type="lpf_2p", cutoff=800.0, resonance=1.0).describe_ja())
    out["tempo"] = [
        d.message_ja + " " + " ".join(d.warnings) + " " + d.describe_ja()
        for d in (
            tempo.decide_tempo("a.wav", 120),
            tempo.decide_tempo("a_170_.wav", 85),
            tempo.decide_tempo("a_100_.wav", 120),
            tempo.decide_tempo("a_60_.wav", 170),
            tempo.decide_tempo("a_100_.wav", 999),
            tempo.decide_tempo("a_100_.wav", None),
        )
    ]
    plan = phrase.plan_phrase("/Volumes/Audio/loop.wav", 60, span=2, out_dir="/Volumes/Audio/out")
    out["phrase"] = [plan.describe_ja()] + [r.describe_ja() for r in plan.renders]
    out["rootkey"] = [
        rootkey.read_key_from_filename("Vox Cmin.wav").label,
        rootkey.read_key_from_filename("Vox.wav").label,
        rootkey._message(60, "filename", rootkey.read_key_from_filename("Vox Cmin.wav")),
        rootkey._message(60, "default", None),
    ]
    out["render"] = [
        render.RenderResult(True, made=2, skipped=1, untouched=1).describe_ja(),
        render.RenderResult(True).describe_ja(),
        render.CleanResult(True, paths=("/a", "/b"), freed_bytes=1048576).describe_ja(),
        render.CleanResult(True, removed=2, freed_bytes=1048576).describe_ja(),
        render.CleanResult(True).describe_ja(),
    ]
    out["log"] = [
        sforzando_log.SforzandoState().describe_ja(),
        sforzando_log.SforzandoState(
            sfz_path="/Volumes/Audio/slot01.sfz",
            regions=1,
            samples=["a.wav", "b.wav", "c.wav", "d.wav"],
            watched_dir="/Volumes/Audio",
            reload_count=1,
        ).describe_ja(),
    ]
    out["axread"] = [
        axread.AxReadResult(False, error="Pro Tools").describe_ja(),
        axread.AxReadResult(True).describe_ja(),
    ]
    out["permission"] = [
        reloader.permission_hint("execution error: not allowed assistive access. (-1719)") or "",
        reloader.permission_hint("Not authorized to send Apple events to System Events. (-1743)") or "",
    ]
    out["parts"] = [sibling.part_message(ja) for ja, _en in sibling._PART_WORDS]
    # 文の中のファイル名は書き換えない（日本語が残るので、結果だけを持ち帰る）
    kept = sibling.part_message("コピーできません: /Volumes/Audio/Cマイナー 不明.wav")
    out["path_kept"] = [str(kept == "Cannot copy: /Volumes/Audio/Cマイナー 不明.wav")]
    out["key_labels"] = [sibling.part_key_label(label) for label in ("Cマイナー", "F#メジャー", "A", "不明")]

    # --- 計画そのもの -----------------------------------------------------
    request = AssignRequest(
        target=target,
        samples=[SampleRef("/Volumes/Audio/Vox Cmin.wav", kind="one_shot")],
        mode=MODE_CHROMATIC,
        tone=tone.get_preset(tone.DEFAULT_PRESET),
        root_key=None,
        octave=3,
        known_slot_number=None,
    )
    out["assign"] = [plan_assignment(request, c._service.ledger).describe_ja()]

    frame.Destroy()
    del app
    return out


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sfz_en_probe_") as tmp:
        out = collect(Path(tmp))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
