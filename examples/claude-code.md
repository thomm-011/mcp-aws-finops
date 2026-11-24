# Claude Code

Zero-install (fetches from GitHub, no PyPI release needed yet):

```bash
claude mcp add aws-finops -- uvx --from git+https://github.com/thomm-011/mcp-aws-finops mcp-aws-finops --demo
```

Or from a local checkout:

```bash
claude mcp add aws-finops -- uv run --directory /path/to/mcp-aws-finops mcp-aws-finops --demo
```

Verify with `claude mcp list` and then ask Claude something like:

> Which service drove the cost spike on 2025-08-25?
