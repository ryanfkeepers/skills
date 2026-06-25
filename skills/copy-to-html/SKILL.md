---
name: copy-to-html
description: >
  Copy markdown content to the macOS clipboard as HTML (public.html) so
  Teams preserves formatting on paste. Use when copying formatted content
  for Teams, when Teams paste loses formatting, or when /copy-to-html is
  invoked.
allowed-tools:
  - Write
  - Bash(dangerouslyDisableSandbox=true)
---

# copy-to-html

Replace any `pbcopy` step with this skill when the paste destination is
Teams. Teams ignores plain text clipboard and only renders `public.html`.

## How to copy

**Step 1** — Write the markdown content to a temp file:

```
Write /tmp/copy-to-html-input.md with the content to copy
```

**Step 2** — Write the conversion script to `/tmp/copy_as_html.py`:

```python
#!/usr/bin/env python3
import subprocess
import sys


def md_to_html(text):
    try:
        import markdown
        return markdown.markdown(text, extensions=["extra", "nl2br"])
    except ImportError:
        pass
    proc = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html"],
        input=text.encode(),
        capture_output=True,
    )
    if proc.returncode == 0:
        return proc.stdout.decode()
    raise RuntimeError(
        "Install 'markdown' (pip3 install markdown) or pandoc."
    )


html = md_to_html(sys.stdin.read())
proc = subprocess.Popen(
    ["osascript", "-e", """
use framework "AppKit"
on run argv
    set htmlString to item 1 of argv
    set htmlData to (current application's NSString's stringWithString:htmlString)'s dataUsingEncoding:(current application's NSUTF8StringEncoding)
    set pb to current application's NSPasteboard's generalPasteboard()
    pb's clearContents()
    pb's setData:htmlData forType:"public.html"
end run
""", html],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
_, err = proc.communicate()
if proc.returncode != 0:
    print(err.decode(), file=sys.stderr)
    sys.exit(1)
print("Copied.")
```

**Step 3** — Run it (`dangerouslyDisableSandbox: true` required for osascript):

```bash
python3 /tmp/copy_as_html.py < /tmp/copy-to-html-input.md
```

After a successful copy, confirm to the user:

> Copied to clipboard. Cmd+V to paste in Teams.

## Dependencies

The script tries `markdown` first, then `pandoc`. If both are missing:

```
pip3 install markdown
```
