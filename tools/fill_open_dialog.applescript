-- macOS 標準の「開く」ダイアログにパスを入れて確定する。
--
--   osascript tools/fill_open_dialog.applescript /path/to/slot01.sfz
--
-- **ダイアログはすでに開いている前提。** 開くところは呼び出し側の仕事
-- （sforzando ならファイルメニューの import を座標で押す。
-- Cmd+O は Pro Tools が横取りするので使えない）。
--
-- **この手順はここ 1 か所だけに置く。** 以前は `sforzando_load.py` の中と
-- `open_preset_by_path.applescript` の中に同じ流れが 2 つあり、
-- 待ち時間がすでに食い違っていた（0.9/0.6/1.2 と 0.8/0.5/1.0）。
-- 実機で詰め直しても片方にしか入らない。
--
-- 守っていること:
--   * **テキスト入力はクリップボード経由。** 直接キーストロークを送ると
--     IME で文字が壊れる。**利用者のクリップボードは元に戻す**
--   * ダイアログが出ていなければ撃たない
--   * 終わってもダイアログが残っていたら Esc で畳む。
--     開いたままだと次の操作が全部そこへ吸われる
--   * **途中で失敗しても、クリップボードは戻す**（2026-10-25 のレビューで直した）。
--     以前はキー送信が許可の不足などで止まると、戻さずに抜けていたので、
--     利用者のクリップボードに読み込ませた .sfz のパスが残った
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
	if (count of argv) < 1 then return "ERR" & tab & "パスを渡してください"
	set thePath to item 1 of argv

	set savedClip to ""
	try
		set savedClip to the clipboard as text
	end try

	tell application "System Events"
		if not (exists process "Pro Tools") then return "ERR" & tab & "NO_PRO_TOOLS"
		set pt to process "Pro Tools"
		tell pt
			set frontmost to true
			delay 0.3
		end tell

		set dlg to my frontWindowName(pt)
		if dlg starts with "Plug-in:" or dlg is "" then
			return "ERR" & tab & "ダイアログが出ていない: " & dlg
		end if

		try
			tell pt
				-- Cmd+Shift+G でパスの直接入力へ
				keystroke "g" using {command down, shift down}
				delay 0.9
				set the clipboard to thePath
				delay 0.3
				keystroke "v" using command down
				delay 0.6
				key code 36 -- Return: パスを確定
				delay 1.2
				key code 36 -- Return: 開く
				delay 2.0
			end tell
		on error errMsg number errNum
			try
				set the clipboard to savedClip
			end try
			return "ERR" & tab & errMsg & " (" & errNum & ")"
		end try

		set after1 to my frontWindowName(pt)

		-- **残っていたら畳む。** 開いたままだと次の操作が吸われる。
		if after1 is not "" and after1 does not start with "Plug-in:" ¬
			and after1 does not start with "Mix:" ¬
			and after1 does not start with "Edit:" then
			tell pt
				key code 53 -- Escape
				delay 0.6
			end tell
			set after1 to (my frontWindowName(pt)) & " (escaped)"
		end if

		try
			set the clipboard to savedClip
		end try

		return "OK" & tab & dlg & tab & after1
	end tell
end run
