#!/usr/bin/env bash
# Block agent commits that embed Cursor co-author trailers in the message.
set -euo pipefail
input=$(cat)
command=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('command',''))")

if [[ "$command" =~ git[[:space:]]+commit ]] && [[ "$command" =~ [Cc]o-authored-by:[[:space:]]*Cursor ]]; then
  echo '{"permission":"deny","user_message":"حذف Co-authored-by: Cursor از پیام commit — در Cursor Settings > Agent > Attribution را خاموش کنید.","agent_message":"Do not add Co-authored-by: Cursor to commit messages."}'
  exit 0
fi

echo '{"permission":"allow"}'
