---
description: Configure status line settings (figures, bar width, overall width)
allowed-tools: Bash(jq:*), Bash(cat:*), Read, Write
---

# Configure Status Line

Read and update the status line configuration at `~/.claude/statusline.json`.

## Config schema

```json
{
  "figures": ["model", "cwd", "git", "duration", "total", "burn", "last", "avg"],
  "min_bar_width": 30,
  "max_width": null
}
```

- **figures**: Ordered list of which metric figures to display. Valid keys: `model`, `cwd`, `git`, `duration`, `total`, `burn`, `last`, `avg`. Order determines display order; omitting a key hides that figure.
- **min_bar_width**: Minimum width in characters for the progress bars (default: 30, minimum: 10).
- **max_width**: Overall status line width override in characters. `null` means content-driven (auto).

## Steps

1. Read the current config from `~/.claude/statusline.json`. If it doesn't exist, show the defaults above and note that no custom config exists yet.

2. Show the user the current configuration.

3. Ask the user what they'd like to change. They may describe changes in natural language (e.g., "hide the git figure", "put duration first", "make the bars wider").

4. Translate the user's request into the appropriate JSON changes. Only include keys that differ from defaults — if all values match defaults, delete the config file instead.

5. Write the updated JSON to `~/.claude/statusline.json`. Use `jq` for formatting:
   ```bash
   echo '<json>' | jq . > ~/.claude/statusline.json
   ```

6. Confirm: "Configuration updated! Changes take effect on the next status line refresh."

## Important

- Only write keys the user has customized. If the user resets everything to defaults, remove the file.
- Validate figure keys against the valid set before writing.
- `min_bar_width` must be at least 10.
- Changes take effect immediately — no restart needed.
