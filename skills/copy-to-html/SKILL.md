---
name: copy-to-html
description: >-
  Convert Markdown to rich HTML and put it on the macOS clipboard, ready
  to paste into Outlook, Teams, Word, or Confluence with formatting
  intact. Wraps mdclip and installs it on first use. Use when the user
  invokes /copy-to-html, or asks to copy something "as html", "as rich
  text", or "to my clipboard" for pasting into an email, Teams message,
  or Confluence page.
---

# Copy to HTML

Everything is done by `scripts/copy-to-html.sh` (in this skill's
directory). The script finds or installs `mdclip`, converts, writes the
clipboard, and checks the clipboard now holds an HTML flavor. Do not
re-implement any of that by hand.

## Steps

1. Pick the Markdown source, in this order:
   - a file path the user gave -- pass it as `FILE`;
   - text the user gave or pointed at (a prior answer, a draft in the
     conversation) -- write it verbatim to a file in the scratchpad
     directory and pass that path;
   - nothing given -- the previous assistant message.
2. Pick flags from where it will be pasted:
   - Teams: `--target teams`
   - Confluence: `--target confluence`
   - Outlook, Word, other, or unstated: no flags
   - User wants newlines kept as line breaks: `--hardbreaks`
3. Run `<skill-dir>/scripts/copy-to-html.sh [flags] <file>`.
4. Report in one line: it succeeded, and the target used. On failure,
   show the script's error and stop.

## Notes

- The script overwrites the user's clipboard; that is the purpose.
- First run builds mdclip from source with Swift (needs Swift 5.10+) and
  installs it to `~/.local/bin/mdclip`. Say so if that happened.
- With no `FILE` and no piped stdin, the script converts whatever
  Markdown is already on the clipboard. Use that only when the user
  says to convert their clipboard.
