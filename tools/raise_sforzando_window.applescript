-- 指定したトラックの sforzando の画面を前に出す。
--
--   osascript tools/raise_sforzando_window.applescript Inst1
--
-- **トラックで選ぶ（2026-10-25 のレビューで直した）。** 以前は「最初に
-- 見つかったプラグインの画面」を前に出していた。別のプラグイン
-- （Decent Sampler など）の画面が前にあると、そちらを前に出したまま
-- sforzando の位置を押すことになる。Pro Tools はプラグインの画面を
-- 同じ位置に開くので、重なった別の画面を押していた。
--
-- トラックを渡さなければ、最初に見つかった sforzando の画面を前に出す。
-- トラック名の比べ方は AppleScript の既定（大文字小文字を区別しない）。
--
-- 出力は 1 行。RAISED <TAB> トラック / NO_PRO_TOOLS / NO_PLUGIN_WINDOW

on run argv
	set wantTrack to ""
	if (count of argv) > 0 then set wantTrack to item 1 of argv
	tell application "System Events"
		if not (exists process "Pro Tools") then return "NO_PRO_TOOLS"
		tell process "Pro Tools"
			set frontmost to true
			delay 0.3
			repeat with w in (every window)
				set wName to ""
				try
					set wName to (name of w) as text
				end try
				if wName starts with "Plug-in:" then
					set trackName to ""
					set pluginName to ""
					repeat with b in (pop up buttons of w)
						try
							set t to (title of b) as text
							if t starts with "Track Selector" then set trackName to (value of b) as text
							if t starts with "Plugin Selector" then set pluginName to (value of b) as text
						end try
					end repeat
					if pluginName contains "sforzando" then
						if wantTrack is "" or trackName is wantTrack then
							perform action "AXRaise" of w
							return "RAISED" & tab & trackName
						end if
					end if
				end if
			end repeat
			return "NO_PLUGIN_WINDOW"
		end tell
	end tell
end run
