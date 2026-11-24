# Releasing mcp-aws-finops

## One-time setup: PyPI Trusted Publisher

`release.yml` publishes to PyPI with
[Trusted Publishing (OIDC)](https://docs.pypi.org/trusted-publishers/) —
no API token or secret is stored in the repo. Before the **first**
release, the repo owner must register the publisher on pypi.org:

1. Sign in to [pypi.org](https://pypi.org) (create an account if you
   don't have one yet).
2. Go to **Your account → Publishing** (or, for a brand-new project
   name, [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/)
   to pre-register before the first upload).
3. Add a new pending publisher:
   - **PyPI project name:** `mcp-aws-finops`
   - **Owner:** `thomm-011`
   - **Repository name:** `mcp-aws-finops`
   - **Workflow filename:** `release.yml`
   - **Environment name:** `pypi`
4. Save. No token is generated or needed — PyPI will trust OIDC tokens
   minted by the `release.yml` workflow running in that GitHub
   environment.
5. In the GitHub repo, create an environment named `pypi` (Settings →
   Environments → New environment) if it doesn't already exist from
   step 4's side effects. Optionally add required reviewers for extra
   safety on real releases.

Until this is done, the `publish-pypi` job in `release.yml` will fail
(OIDC exchange rejected) — but it's `continue-on-error: true`, so the
Docker image build/push and the GitHub Release still complete
normally. Re-running the workflow (or just the `publish-pypi` job)
after registering the publisher will succeed without any other change.

## Cutting a release

1. Update `CHANGELOG.md`: move the `[Unreleased]` section to a new
   `## [X.Y.Z] - YYYY-MM-DD` heading (or add one) with the actual
   changes.
2. Bump the version in `src/mcp_aws_finops/__init__.py`
   (`__version__ = "X.Y.Z"`) — this is the single source of truth;
   `pyproject.toml` reads it dynamically via `tool.hatch.version`.
3. Commit: `git commit -am "chore(release): vX.Y.Z"`.
4. Sanity-check locally before tagging:
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run mypy src
   uv run pytest --cov
   uv build
   uvx twine check dist/*
   ```
5. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```
6. Watch the **Release** workflow in GitHub Actions. It will:
   - build the sdist/wheel and verify the tag matches the package
     version (fails loudly if they drift);
   - attempt the PyPI publish (see setup above — safe to fail until
     the Trusted Publisher is registered, the rest still runs);
   - build and push a multi-arch (amd64/arm64) image to
     `ghcr.io/thomm-011/mcp-aws-finops:X.Y.Z` and `:latest`;
   - create a GitHub Release with the matching `CHANGELOG.md` section
     as notes and the `dist/` files attached.
7. Verify:
   ```bash
   docker run -i --rm ghcr.io/thomm-011/mcp-aws-finops:X.Y.Z --version
   # once PyPI publish has succeeded at least once:
   uvx mcp-aws-finops --version
   ```

## Notes

- Never hand-edit `uv.lock`; run `uv lock` if dependencies changed.
- The tag is the only trigger for `release.yml` — pushing to `main`
  alone does not publish anything.
- If a release needs to be redone (e.g. PyPI publish failed before the
  publisher was registered), re-run the failed job from the Actions UI
  — artifacts from `build` are reused, nothing needs to be re-tagged.
