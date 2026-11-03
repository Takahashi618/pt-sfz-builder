PT SFZ Builder {VERSION}
README

This folder contains 8 files and 1 app. Some file names are in Japanese; the English name follows each.

  PT SFZビルダー.app  The app (Finder shows it as PT SFZ Builder when your Mac is in English)
  README (English).txt  This document
  Manual (English).html  How to use the app (opens in a browser; you can move by headings)
  Manual (English).txt  The same manual as plain text
  はじめにお読みください.txt  This document in Japanese
  マニュアル.html, マニュアル.txt  The manual in Japanese
  ライセンス.txt  License: the terms of use of this software (MIT License, in English with a Japanese summary)
  同梱部品のライセンス.txt  Third-party licenses: the terms of the parts made by others inside the app

== What it is

An app that lets you play audio samples, from Splice or your own files, from a MIDI keyboard in Pro Tools.
The sound comes from sforzando, a free sampler by Plogue. This app writes a definition file (SFZ) that says
how to arrange the samples and has sforzando read it, so you do not need to operate the sampler's window by sight.
It is designed to be used with VoiceOver and the keyboard only. "PT" in the name stands for Pro Tools.
Pro Tools is a product of Avid Technology; this app is not affiliated with Avid Technology.

== Requirements

- A Mac with Apple silicon (M1 or later), macOS 15 or later (tested by the author on 15.7.8)
- Pro Tools (tested by the author on 2026.4.1)
- The AAX version of sforzando (free; tested by the author on 1.982)
- VoiceOver
- The app's window and speech follow your Mac's language settings: English or Japanese (chapter 2 of the manual)
- Stretching a loop across the keyboard while keeping its speed, and matching tempo, need ffmpeg
  (install it with Homebrew). rubberband improves the sound quality

== Installing (short version)

1. Move "PT SFZビルダー.app" from this folder to the Applications folder
2. Open it. macOS may stop it from opening the first time.
   See "3.2 Opening the app for the first time" in the manual
3. Choose Open Accessibility Settings in the Actions menu and turn on PT SFZ Builder
   (see "3.3 Give permissions" in the manual)
4. In Pro Tools, insert sforzando on an instrument track and open its window
5. Press Command-R to build the Splice index, find a sample, and press Return in the list.
   Only the first time you assign on a track, press Load into Plugin

For details, read "Manual (English).html" (or "Manual (English).txt").
In the app, Command-Shift-K opens the list of keyboard commands.

== Made with AI

This software was made by the author (Takahashi) using AI (Anthropic's Claude),
under the author's direction and judgment.
Most of the program code and of the text, including the manual, was written by the AI.

== License

MIT License (Copyright (c) 2026 Takahashi). It is free to use, with no warranty.
For details, read "ライセンス.txt".
