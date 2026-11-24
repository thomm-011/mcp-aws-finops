# Ready-to-copy agent configs

Pick your agent and copy/adapt the snippet. All of these run the bundled
synthetic demo data (`--demo`) — no AWS account or credentials needed.

| Agent | File |
|---|---|
| Claude Desktop | [`claude_desktop_config.json`](./claude_desktop_config.json) |
| Cursor | [`.cursor/mcp.json`](./.cursor/mcp.json) |
| Claude Code | [`claude-code.md`](./claude-code.md) |
| Hermes | [`hermes-config.yaml`](./hermes-config.yaml) |

For live AWS data instead of the sample dataset, see
[`aws-mode.md`](./aws-mode.md) (`--source aws`; implemented and
mock-tested, not yet validated against a live account).

## Two ways to run the server

**Zero-install (PyPI release pending), fetches straight from GitHub:**

```bash
uvx --from git+https://github.com/thomm-011/mcp-aws-finops mcp-aws-finops --demo
```

**Local checkout** (if you've already cloned the repo):

```bash
uv run --directory /path/to/mcp-aws-finops mcp-aws-finops --demo
```

Both speak MCP over stdio. Swap `--demo` for `--data /path/to/focus.parquet`
(or a directory of FOCUS CSV/Parquet files) to point at real billing data.
