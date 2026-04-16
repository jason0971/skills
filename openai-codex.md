# OpenAI Codex Plugin

Integrate and use OpenAI Codex CLI within Claude Code sessions.

## Trigger

Use this skill when the user asks to:
- Set up or install OpenAI Codex
- Run Codex on files or tasks
- Use `codex` CLI commands
- Combine Codex with Claude Code workflows

## Setup

Install OpenAI Codex CLI globally:

```bash
npm install -g @openai/codex
```

Verify installation:

```bash
codex --version
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=your_api_key_here
```

To persist the key, add it to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
echo 'export OPENAI_API_KEY=your_api_key_here' >> ~/.bashrc
```

## Usage

### Run Codex on a task

```bash
codex "refactor this function to use async/await"
```

### Run Codex on a specific file

```bash
codex --file path/to/file.py "add type hints to all functions"
```

### Interactive mode

```bash
codex
```

### Common flags

| Flag | Description |
|------|-------------|
| `--model` | Specify model (e.g., `o4-mini`, `o3`) |
| `--approval-mode` | Set approval mode: `suggest`, `auto-edit`, `full-auto` |
| `--quiet` | Suppress extra output |
| `--file` | Target a specific file |

## Claude Code Integration

When using Codex alongside Claude Code:

1. Use Claude Code for high-level planning, architecture, and review
2. Use Codex for targeted code generation or transformation tasks
3. Claude Code can orchestrate Codex via Bash tool calls

### Example: Run Codex from Claude Code

Claude Code can invoke Codex through the Bash tool:

```bash
codex --approval-mode auto-edit "add docstrings to all public functions in src/"
```

## Troubleshooting

- **Command not found**: Ensure `npm` global bin is in your `PATH` (`npm bin -g`)
- **API errors**: Verify `OPENAI_API_KEY` is set and valid
- **Permission errors**: Try `sudo npm install -g @openai/codex` or use a Node version manager (nvm)
