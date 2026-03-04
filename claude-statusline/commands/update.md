---
description: Update claude-statusline plugin and statusLine path
allowed-tools: Bash(jq:*), Bash(ls:*), Bash(sort:*), Bash(tail:*), Bash(mv:*), Read
---

# Claude Statusline Update

Update the statusLine path in settings to point to the latest cached plugin version.

**Prerequisite:** The user must first update the marketplace from within their Claude session by running:
```
/plugin marketplace update claude-statusline-marketplace
```
If the latest cached version hasn't changed, remind the user to run that command first, then re-run `/claude-statusline:update`.

## Steps

1. Look for the plugin cache directory at `~/.claude/plugins/cache/claude-statusline-marketplace/claude-statusline/`. List version subdirectories and pick the latest (`ls | sort -V | tail -1`).

2. If no cache directory exists, fall back to resolving the path relative to this command file (same as setup).

3. Verify the `statusline-command.py` script exists at the resolved path.

4. Read `~/.claude/settings.json`. Use `jq` to update only `statusLine.command` to point to the new path:
   ```
   uv run --script <new-absolute-path>/statusline-command.py
   ```
   Back up the file to `~/.claude/settings.json.bak` before writing.

5. Tell the user the old and new paths, and confirm: "Status line path updated! The change takes effect immediately."

## Important

- Preserve all other settings — only update `statusLine.command`.
- The path MUST be absolute.
