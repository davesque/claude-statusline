---
description: Configure claude-statusline as your status line
allowed-tools: Bash(jq:*), Bash(cat:*), Bash(which:*), Bash(ls:*), Bash(mv:*), Read
---

# Claude Statusline Setup

Configure the claude-statusline plugin as your Claude Code status line.

## Steps

1. Find the absolute path to `statusline-command.py` by resolving it relative to this command file. The script lives alongside the `commands/` directory in the plugin root.

2. Verify `uv` is installed (`which uv`). If not, tell the user to install it from https://docs.astral.sh/uv/ and stop.

3. Read `~/.claude/settings.json` (create it if it doesn't exist). Use `jq` to set the `statusLine` key:
   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "uv run --script <absolute-path-to-statusline-command.py>"
     }
   }
   ```
   Make sure to preserve all other existing settings. Back up the file to `~/.claude/settings.json.bak` before writing.

4. Tell the user: "Status line configured! You should see it appear immediately."

## Important

- The script path MUST be absolute so it works from any working directory.
- Use `uv run --script` so PEP 723 inline dependencies are resolved automatically.
- Do NOT overwrite other keys in settings.json — merge the `statusLine` key only.
