# PT SFZビルダー（PT SFZ Builder）

Splice などのオーディオサンプルを、Pro Tools の上で MIDI 鍵盤から弾けるようにする macOS のアプリです。
音源には、無料のサンプラー sforzando（Plogue 社）を使います。サンプルの並べ方を書いた定義ファイル（SFZ）をこのアプリが作り、
sforzando に読ませるので、サンプラーの画面を目で見て操作する必要がありません。
VoiceOver とキーボードだけで使えるように作っています。名前の「PT」は Pro Tools のことです。
画面と読み上げは、Mac の言語の設定に合わせて日本語か英語で出ます。

- 動く環境: Apple シリコン（M1 以降）の Mac、macOS 15 以降、Pro Tools、sforzando の AAX 版（無料）、VoiceOver。
  作者は macOS 15.7.8、Pro Tools 2026.4.1、sforzando 1.982 で確かめています
- 使うだけなら: [Releases](https://github.com/Takahashi618/pt-sfz-builder/releases) にある `PTSFZBuilder_1.0.1.zip`（表示名は PT SFZビルダー_1.0.1.zip）を開き、中の「はじめにお読みください.txt」を読んでください
- 使い方: [docs/manual.txt](docs/manual.txt)（HTML 版は [docs/manual.html](docs/manual.html)。ダウンロードしてブラウザで開きます）
- ライセンス: MIT ライセンス（Copyright (c) 2026 Takahashi）。全文は [LICENSE.txt](LICENSE.txt)。
  配布版のアプリに入っているほかの人の部品の条件は [同梱部品のライセンス.txt](同梱部品のライセンス.txt)
- このソフトウェアは、作者（Takahashi）の指示と判断のもとで、AI（Anthropic 社の Claude）を使って作りました。
  プログラムのコードと文章の大部分は AI が書いたものです
- Pro Tools は Avid Technology 社の、Splice は Splice 社の、sforzando は Plogue 社の製品です。このアプリは、それらの会社とは関係ありません

## ソースから動かす

Python 3.14 と、[requirements.txt](requirements.txt) の部品を入れます。ループの速さを保ったまま鍵盤に広げる機能と、テンポを合わせる機能には
ffmpeg も要ります（`brew install ffmpeg`。`brew install rubberband` もあれば音質が上がります）。

```bash
python3.14 -m pip install -r requirements.txt
```

```bash
python3.14 -X utf8 app.py
```

- Pro Tools と sforzando の画面を読んで操作するので、動かすアプリ（端末など）にアクセシビリティの許可が要ります
- スロットと設定は、取り出したフォルダの隣の `sfz_slots` に作ります（配布版は `~/Music/SFZBuilder`）。Splice の索引は `siblings/sample_index/data/` に作ります
- テスト: `python3.14 -X utf8 tests/run_all.py`（Pro Tools には触りません）
- 配布版（zip）を作る: `python3.14 -X utf8 tools/build_release.py`
  （[python.org](https://www.python.org/) の Python 3.14 で動かします。PyInstaller を使います）
- マニュアルを直したら: `python3.14 -X utf8 tools/doc_parts.py`（キーの一覧などを作り直し、txt も作ります）

### 中身

- `app.py`・`core/`・`ui/`・`integration/`: アプリ本体（wxPython）
- `core/i18n.py`: 表示の言語（Mac の言語の設定に合わせて日本語か英語。文言は `tr("日本語", "English")` と並べて書いています）
- `tools/*.applescript`: Pro Tools のプラグインの画面を読み、sforzando に定義ファイルを読ませる部分
- `siblings/`: 作者の別のプロジェクトから借りている部品の写し（読み上げと試聴、素材の索引と名前の解析、長さの変換）。コメントを除いた形で入れています
- `docs/`: マニュアルと「はじめにお読みください」の元
- コメントには、開発中に実機で測って分かったことを日付つきで残しています

## English

PT SFZ Builder is a macOS app that lets you play audio samples (from Splice or your own folders) from a MIDI keyboard in Pro Tools.
It writes SFZ definition files and loads them into the free sforzando sampler by Plogue, so you do not need to operate the sampler's window by sight.
It is designed to be used with VoiceOver and the keyboard only. "PT" stands for Pro Tools.

The app's window and speech follow your Mac's language settings: English or Japanese.

- Requirements: a Mac with Apple silicon (M1 or later), macOS 15 or later, Pro Tools, the AAX version of sforzando (free), VoiceOver.
  Tested on macOS 15.7.8, Pro Tools 2026.4.1, and sforzando 1.982
- To use it: open `PTSFZBuilder_1.0.1.zip` from [Releases](https://github.com/Takahashi618/pt-sfz-builder/releases) and read “README (English).txt” inside
- Manual: [docs/manual_en.txt](docs/manual_en.txt) (HTML version: [docs/manual_en.html](docs/manual_en.html))
- License: MIT License (Copyright (c) 2026 Takahashi). Full text in [LICENSE.txt](LICENSE.txt).
  Third-party components in the packaged app: [同梱部品のライセンス.txt](同梱部品のライセンス.txt)
- This software was made by the author (Takahashi) using AI (Claude by Anthropic), under the author's direction and judgment.
  Most of the code and text was written by the AI
- Pro Tools is a product of Avid Technology, Splice is a product of Splice, and sforzando is a product of Plogue. This app is not affiliated with those companies

### Running from source

Install Python 3.14 and [requirements.txt](requirements.txt), then run `python3.14 -X utf8 app.py`. Stretching loops across the keyboard and matching tempo need ffmpeg
(`brew install ffmpeg`; `brew install rubberband` improves the sound). The app you run it from (such as Terminal) needs Accessibility permission,
because it reads and operates Pro Tools and sforzando windows. Slots and settings are created in `sfz_slots` next to the folder
(the packaged app uses `~/Music/SFZBuilder`), and the Splice index in `siblings/sample_index/data/`. Code comments are mostly in Japanese.
Tests: `python3.14 -X utf8 tests/run_all.py` Packaging: `python3.14 -X utf8 tools/build_release.py`
(use the python.org Python 3.14 with PyInstaller installed)
