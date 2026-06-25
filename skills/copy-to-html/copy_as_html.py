#!/usr/bin/env python3
"""
Reads markdown from stdin, converts to HTML, and copies to the macOS
clipboard as public.html so Teams preserves formatting on paste.

Requires the `markdown` package (pip3 install markdown) or pandoc.
"""
import subprocess
import sys


def md_to_html(text: str) -> str:
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
        "Install 'markdown' (pip3 install markdown) or pandoc to use this skill."
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
