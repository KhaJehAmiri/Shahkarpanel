#!/usr/bin/env python3
"""Strip Cursor attribution and Phase-prefixed boilerplate from commit messages (history rewrite)."""
import re
import sys

text = sys.stdin.read()
lines = text.split("\n")

lines = [ln for ln in lines if "Co-authored-by: Cursor" not in ln]

if lines:
    subject = lines[0]
    subject = re.sub(r"^Phase \d+[a-zA-Z]*:\s*", "", subject)
    subject = re.sub(r"^feat\(phase-\d+\):\s*", "feat: ", subject, flags=re.I)
    subject = re.sub(r"^Execute audit phases \d+[–-]\d+:\s*", "", subject)
    subject = re.sub(
        r"^Complete audit phases \d+[–-]\d+:\s*",
        "Complete security and UI audit: ",
        subject,
    )
    lines[0] = subject

filtered: list[str] = []
skip_phase_body = False
for line in lines:
    if re.match(r"^Phase \d+[a-zA-Z]*:\s", line):
        skip_phase_body = True
        continue
    if skip_phase_body:
        if line.strip() == "" or line.strip().startswith("-"):
            skip_phase_body = False
            if line.strip().startswith("-"):
                filtered.append(line)
        continue
    filtered.append(line)

while filtered and not filtered[-1].strip():
    filtered.pop()

has_bullets = any(ln.strip().startswith("-") for ln in filtered[1:])
if has_bullets and len(filtered) > 1:
    trimmed: list[str] = [filtered[0]]
    seen_bullet = False
    for line in filtered[1:]:
        if line.strip().startswith("-"):
            seen_bullet = True
            trimmed.append(line)
        elif seen_bullet:
            trimmed.append(line)
        elif line.strip() == "":
            trimmed.append(line)
    filtered = trimmed

out = "\n".join(filtered)
if out and not out.endswith("\n"):
    out += "\n"
sys.stdout.write(out)
