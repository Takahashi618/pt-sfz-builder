-- Pro Tools のプラグインウィンドウを機械可読な形で列挙する。
--
-- `integration/axread.py` が解析する前提の固定書式。
--
-- 1 行 1 ウィンドウ。タブ区切り。**前面から順**に並ぶ。
--
--   SESSION <TAB> name
--   WIN <TAB> title <TAB> track <TAB> plugin <TAB> x <TAB> y <TAB> w <TAB> h
--       <TAB> vx <TAB> vy <TAB> vw <TAB> vh
--
-- 先頭の SESSION は開いているセッションの名前。編集窓かミックス窓の
-- 名前（`Edit: 260904_1` / `Mix: 260904_1`）から取る。
-- **スロットをセッションごとに分けるのに要る。** 分けないと、別の
-- セッションで割り当てたときに前のセッションの音を上書きしてしまう
-- （2026-09-05 に確認）。取れなければ空文字。**推測で埋めない。**
--
-- 後半 4 つは `FXTDMEditView`（プラグインの描画領域）の矩形。
-- **この値は当てにならないことがある。** 2026-09-04 の実測で、
-- sforzando は正しい絶対座標（20,128）を返したが、Decent Sampler は
-- (0,1164) という窓の外の値を返した。Python 側で妥当性を検証する。
--
-- 取れなかった項目は空文字にする。**推測で埋めない。**
-- Python 側が「取れていない」ことを判断できなくなるため。
--
-- 値に改行が混ざることがある（Plugin Selector の title は
-- "Plugin Selector\nPackage: AAX Native" だった。2026-09-04 実測）。
-- 行の区切りが壊れるので、**改行は空白へ潰してから出す。**
--
-- 読み取りだけなので前面化は要らない。
--
-- 使い方: osascript tools/ax_plugin_windows.applescript

on flatten(t)
	if t is missing value then return ""
	set s to t as text
	set out to ""
	repeat with ch in (characters of s)
		set c to ch as text
		if c is linefeed or c is return or c is tab then
			set out to out & " "
		else
			set out to out & c
		end if
	end repeat
	return out
end flatten

on valueOfPopUp(w, wantedTitle)
	tell application "System Events"
		repeat with b in (pop up buttons of w)
			try
				set t to my flatten(title of b)
				if t starts with wantedTitle then return my flatten(value of b)
			end try
		end repeat
	end tell
	return ""
end valueOfPopUp

tell application "System Events"
	if not (exists process "Pro Tools") then return "NO_PRO_TOOLS"
	tell process "Pro Tools"
		set out to ""
		-- セッション名。編集窓・ミックス窓のどちらからでも取れる。
		set sessionName to ""
		repeat with w in (every window)
			set n to ""
			try
				set n to my flatten(name of w)
			end try
			if n starts with "Edit: " then
				set sessionName to text 7 thru -1 of n
				exit repeat
			else if n starts with "Mix: " and sessionName is "" then
				set sessionName to text 6 thru -1 of n
			end if
		end repeat
		set out to out & "SESSION" & tab & sessionName & linefeed
		repeat with w in (every window)
			set wName to ""
			try
				set wName to my flatten(name of w)
			end try
			if wName starts with "Plug-in:" then
				set trackName to my valueOfPopUp(w, "Track Selector")
				set pluginName to my valueOfPopUp(w, "Plugin Selector")
				set x to ""
				set y to ""
				set ww to ""
				set hh to ""
				try
					set p to position of w
					set s to size of w
					set x to (item 1 of p) as text
					set y to (item 2 of p) as text
					set ww to (item 1 of s) as text
					set hh to (item 2 of s) as text
				end try
				set vx to ""
				set vy to ""
				set vw to ""
				set vh to ""
				try
					set g to (first group of w whose title is "FXTDMEditView")
					set gp to position of g
					set gs to size of g
					set vx to (item 1 of gp) as text
					set vy to (item 2 of gp) as text
					set vw to (item 1 of gs) as text
					set vh to (item 2 of gs) as text
				end try
				set out to out & "WIN" & tab & wName & tab & trackName & tab & pluginName
				set out to out & tab & x & tab & y & tab & ww & tab & hh
				set out to out & tab & vx & tab & vy & tab & vw & tab & vh & linefeed
			end if
		end repeat
		return out
	end tell
end tell
