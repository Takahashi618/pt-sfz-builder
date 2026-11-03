"""sfz_builder の実行層。Pro Tools や macOS に触れる部分をここに閉じ込める。

core 層は判断だけを行い、副作用を持たない。ここが実際に
ファイルを書き、AppleScript を叩き、結果を読み上げ文言にして返す。
"""
