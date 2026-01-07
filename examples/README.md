# Examples

Example scripts demonstrating how to use the `claude-sessions` library.

## Scripts

### export_all_to_markdown.py

Export all Claude Code conversations to human-readable Markdown files, organized by project.

**Usage:**

```bash
# Export all sessions to ./claude_exports
python export_all_to_markdown.py

# Export to a custom directory
python export_all_to_markdown.py -o ~/my_exports

# Export only sessions from a specific project
python export_all_to_markdown.py -p myproject

# Exclude tool calls and sub-agent conversations
python export_all_to_markdown.py --no-tools --no-agents
```

**Options:**

| Option | Description |
|--------|-------------|
| `-o, --output-dir` | Output directory (default: `./claude_exports`) |
| `-p, --project` | Filter to projects containing this string |
| `--no-tools` | Exclude tool calls from output |
| `--no-agents` | Exclude sub-agent conversations |
| `-m, --include-metadata` | Include working directory and git branch per message |

**Output structure:**

```
claude_exports/
  -home-user-project-one/
    2025-01-05_a1b2c3d4_help-me-fix-the-login-bug.md
    2025-01-06_b2c3d4e5_add-dark-mode-to-settings.md
  -home-user-project-two/
    2025-01-07_c3d4e5f6_refactor-the-api-client.md
```

Filenames are generated from the first user message in each conversation, converted to kebab-case and truncated to ~40 characters. The date and a session ID prefix ensure uniqueness and sortability.
