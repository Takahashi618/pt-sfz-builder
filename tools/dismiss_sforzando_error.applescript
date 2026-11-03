-- sforzando のエラーダイアログを畳む。
--
--   osascript tools/dismiss_sforzando_error.applescript
--
-- **サンプルが見つからないと、sforzando はモーダルのエラーを出す。**
--
--     sforzando Error
--     No sound asset loaded
--     Not Found: /…/存在しない.wav
--     [OK]
--
-- これが出ている間、**プラグインへのクリックが全部素通りする。**
-- しかもフォルダの監視は効き続けるので、書き換えは反映される。
-- そのため「読み込みは動いているのに操作だけ効かない」という
-- 分かりにくい状態になる（2026-09-04 に実際に踏んだ）。
--
-- 名前の無いウィンドウで、AXButton 'OK' と 'sforzando Error' を含む
-- AXStaticText を持つものを探す。**Pro Tools 本体のダイアログと
-- 取り違えないよう、両方の条件で絞る。**
--
-- 出力は 1 行。DISMISSED / NONE / エラー。

tell application "System Events"
	if not (exists process "Pro Tools") then return "NO_PRO_TOOLS"
	tell process "Pro Tools"
		repeat with w in (every window)
			set nm to ""
			try
				set nm to (name of w) as text
			end try
			if nm is "" then
				set hasOK to false
				set isSforzando to false
				set detail to ""
				try
					repeat with e in (UI elements of w)
						try
							if (role of e is "AXButton") and ((title of e) as text is "OK") then
								set hasOK to true
							end if
						end try
						try
							if role of e is "AXStaticText" then
								set v to (value of e) as text
								set detail to detail & v & " "
								if v contains "sforzando" or v contains "sound asset" or v contains "Not Found" then
									set isSforzando to true
								end if
							end if
						end try
					end repeat
				end try
				if hasOK and isSforzando then
					perform action "AXPress" of (first button of w whose title is "OK")
					delay 0.4
					return "DISMISSED" & tab & detail
				end if
			end if
		end repeat
		return "NONE"
	end tell
end tell
