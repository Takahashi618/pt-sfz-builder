-- プラグインウィンドウを前に出して Cmd+O を撃つ（案 B の前半）。
--
--   osascript tools/press_cmd_o.applescript
--
-- **これだけでは開かないことが分かっている。** Pro Tools が Cmd+O を
-- 横取りし、自分の「セッションを開く」を出す（2026-09-04 実機確認）。
-- 案 B を残してあるのは、プラグイン側が対応したときに使えるため。
-- 実際に使っているのは座標クリック（`tools/sforzando_load.py`）。
--
-- パスを入れるところは `tools/fill_open_dialog.applescript` が受け持つ。
-- **同じ手順を 2 か所に書かない。**
--
-- 守っていること:
--   * **フォーカス確認を省略しない。** 最前面がプラグインウィンドウで
--     なければ撃たない。Pro Tools 本体のダイアログが出てしまう
--
-- 戻り値はタブ区切り。先頭が OK か ERR。

on frontWindowName(pt)
	tell application "System Events"
		try
			return (name of window 1 of pt) as text
		on error
			return ""
		end try
	end tell
end frontWindowName

on run argv
	tell application "System Events"
		if not (exists process "Pro Tools") then return "ERR" & tab & "NO_PRO_TOOLS"
		set pt to process "Pro Tools"
		tell pt
			set frontmost to true
			delay 0.4
			try
				set w to (first window whose name starts with "Plug-in:")
			on error
				return "ERR" & tab & "NO_PLUGIN_WINDOW"
			end try
			set pluginName to (name of w) as text
			perform action "AXRaise" of w
			delay 0.4
		end tell

		if my frontWindowName(pt) does not start with "Plug-in:" then
			return "ERR" & tab & "最前面がプラグインウィンドウではない: " & my frontWindowName(pt)
		end if

		tell pt
			keystroke "o" using command down
			delay 1.5
		end tell

		set dlg to my frontWindowName(pt)
		if dlg starts with "Plug-in:" then
			return "ERR" & tab & "ダイアログが出なかった: " & dlg
		end if
		return "OK" & tab & pluginName & tab & dlg
	end tell
end run
