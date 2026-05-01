# Releasing

This document describes how `xpoz-cli` is built, released, and distributed to package managers. The release pipeline is fully GitHub-Actions-driven; cutting a release is a single `git push` once the one-time setup below is done.

## TL;DR

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

Three workflows run automatically:

1. `ci.yml` — validates the source distribution can be built and the entry point works.
2. `release.yml` — builds 4 PyInstaller binaries, creates a GitHub Release with them attached.
3. `publish.yml` — fans out to PyPI, Homebrew tap, and winget (each independently gated by a repo variable).

## Workflows

All workflows live under `.github/workflows/`.

### `ci.yml` — validation

| Property | Value |
|---|---|
| Triggers | `pull_request`, `push` to `main`, push of `v*` tags |
| Runner | `ubuntu-latest` |
| What it does | Builds wheel + sdist from `pyproject.toml` (with `SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0` so untagged branches build deterministically), installs the wheel into a clean venv, runs `xpoz-cli --help` and `xpoz-cli twitter --help` to confirm the entry point + SDK import work. Also lints all workflow YAML files. |

This catches a broken `pyproject.toml` on the PR that introduces it, and re-runs on tag push so a release that bypassed normal review still gets validated alongside the binary build.

### `release.yml` — binaries + GitHub Release

| Property | Value |
|---|---|
| Triggers | Push of `v*` tags, or `workflow_dispatch` with a `tag` input |
| Runners | Matrix: `ubuntu-latest` (Linux amd64), `ubuntu-24.04-arm` (Linux arm64), `macos-14` (macOS arm64), `windows-latest` (Windows amd64) |
| What it does | For each platform, installs Python 3.14 + `xpoz` + PyInstaller, builds a single-file binary (`pyinstaller --onefile --strip`), smoke-tests `--help`, uploads as a workflow artifact. A `release` job then downloads all four artifacts and creates a GitHub Release with them attached. |

The Linux runners use `manylinux_2_28` containers and a separately-installed `python-build-standalone` distribution (via `uv`), because the default manylinux Python is built without `--enable-shared` and PyInstaller needs `libpython.so`.

Output asset names:

- `xpoz-cli-linux-amd64`
- `xpoz-cli-linux-arm64`
- `xpoz-cli-macos-arm64`
- `xpoz-cli-windows-amd64.exe`

macOS Intel is intentionally not shipped as a prebuilt binary — users on that platform install from source via `pip install xpoz-cli`.

### `publish.yml` — package managers

| Property | Value |
|---|---|
| Triggers | `release: published` (fires the moment `release.yml` finishes), or `workflow_dispatch` with an existing tag |
| Jobs | `meta` (resolves tag/version), then in parallel: `publish-pypi`, `publish-homebrew`, `publish-winget` |

Each publish job is gated by a repository variable (`vars.ENABLE_*_PUBLISH`). A job is **skipped** unless its variable is set to `true`. This lets you enable each destination independently as the one-time setup is completed.

| Job | Gate variable | What it does |
|---|---|---|
| `publish-pypi` | `ENABLE_PYPI_PUBLISH` | Checks out the tag, builds wheel + sdist (`setuptools-scm` reads the tag), verifies the built version matches the tag, uploads via PyPI trusted publishing (no API token). |
| `publish-homebrew` | `ENABLE_HOMEBREW_PUBLISH` | Downloads the three release assets, computes SHA256s, renders `Formula/xpoz-cli.rb`, pushes it to the tap repo. |
| `publish-winget` | `ENABLE_WINGET_PUBLISH` | Downloads Microsoft's `wingetcreate.exe`, runs `update Xpoz.XpozCli` pointed at the windows release URL, opens a PR to `microsoft/winget-pkgs`. |

## Trigger sequence

```
git push origin vX.Y.Z
        |
        +------> ci.yml          (parallel: wheel build + entry-point test)
        |
        +------> release.yml     (parallel: 4 PyInstaller binaries -> GitHub Release)
                       |
                       v
                   release: published
                       |
                       v
                  publish.yml
                       |
              +--------+--------+
              |        |        |
              v        v        v
            PyPI   Homebrew  winget
        (gated by  (gated by (gated by
         var)       var)      var)
```

## One-time setup

You can ship today with just `release.yml` (the original GitHub Releases flow). Each package-manager destination needs the following before its `publish.yml` job will work:

### PyPI (trusted publishing)

1. Go to <https://pypi.org/manage/account/publishing/>.
2. Click **Add a new pending publisher** (use this form even if the project doesn't exist yet — it'll be created on first upload).
3. Fill in:
   - PyPI Project Name: `xpoz-cli`
   - Owner: `XPOZpublic`
   - Repository name: `xpoz-cli`
   - Workflow name: `publish.yml`
   - Environment name: leave blank
4. In this repo's settings → Variables → Actions, add `ENABLE_PYPI_PUBLISH=true`.

No API token is needed. Trusted publishing works via OIDC; the `publish-pypi` job declares `permissions: id-token: write` so GitHub mints a short-lived token PyPI can verify.

### Homebrew tap

1. Create a new repo `XPOZpublic/homebrew-xpoz`. The repo name **must** start with `homebrew-` for `brew tap` to find it. The part after `homebrew-` is what users will tap (so users will run `brew tap XPOZpublic/xpoz`).
2. Generate a fine-grained Personal Access Token scoped only to `XPOZpublic/homebrew-xpoz` with **Contents: Read and write**.
3. In this repo's settings → Secrets → Actions, add `HOMEBREW_TAP_TOKEN` with that PAT.
4. In Variables → Actions, add `ENABLE_HOMEBREW_PUBLISH=true`.

End users then install via:

```bash
brew tap XPOZpublic/xpoz
brew install xpoz-cli
```

The workflow regenerates the formula from scratch on every release (no template file is checked in), so the tap repo only needs to be initialized as an empty repo.

### winget

The first version of `Xpoz.XpozCli` must be submitted manually — `wingetcreate update` only works for packages that already exist in `microsoft/winget-pkgs`.

1. On a Windows machine, install `wingetcreate`:
   ```powershell
   winget install Microsoft.WingetCreate
   ```
2. After cutting your first GitHub Release, run interactively against the windows binary:
   ```powershell
   wingetcreate new https://github.com/XPOZpublic/xpoz-cli/releases/download/v0.1.0/xpoz-cli-windows-amd64.exe
   ```
   Use `Xpoz.XpozCli` as the Package Identifier when prompted. The tool opens a PR to `microsoft/winget-pkgs`; wait for it to be reviewed and merged.
3. Generate a classic Personal Access Token with `public_repo` scope (the tool needs to fork `microsoft/winget-pkgs` under your account).
4. In this repo's settings → Secrets → Actions, add `WINGET_TOKEN` with that PAT.
5. In Variables → Actions, add `ENABLE_WINGET_PUBLISH=true`.

After the initial PR is merged, the `publish-winget` job will open update PRs automatically on every release.

## Cutting a release

1. Confirm `main` is green (CI passing).
2. Pick the next semver version (e.g., `v0.2.0`). Versions are derived from git tags via `setuptools-scm`; there is no version constant in the source to bump.
3. Tag and push:
   ```bash
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```
4. Watch the runs in the **Actions** tab:
   - `ci` should go green
   - `build-release` should go green and create a GitHub Release
   - `publish` should fire after the release is created; the gated jobs run for whichever destinations you've enabled

## Re-running a publish

If a publish job fails (bad token, transient network error, etc.), you don't need to cut a new tag. Go to **Actions → publish → Run workflow** and supply the existing tag (e.g., `v0.2.0`). The same gating applies, so only enabled destinations re-run.

The `meta` job uses `inputs.tag` for `workflow_dispatch` and `github.event.release.tag_name` for `release: published`, so both paths produce the same `tag` and `version` outputs downstream.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `publish-pypi` fails with "no trusted publisher configured" | Trusted publisher not added on pypi.org, or its `Workflow name` field doesn't match `publish.yml`. |
| `publish-pypi` fails with "Built version (X) does not match tag (Y)" | The tag pushed isn't a `vX.Y.Z` semver tag, or `setuptools-scm` couldn't read tags (`fetch-depth: 0` is set, so this should be rare). |
| `publish-homebrew` fails on `git push` | `HOMEBREW_TAP_TOKEN` is missing, expired, or doesn't have `Contents: Read and write` on the tap repo. |
| `publish-homebrew` fails fetching release assets | `release.yml` produced fewer than three Linux/macOS binaries, or the tag's GitHub Release doesn't exist yet. The job triggers on `release: published`, so this should only happen on `workflow_dispatch` runs against tags whose release was deleted. |
| `publish-winget` fails with "Package identifier not found" | The first manual `wingetcreate new` submission hasn't been merged into `microsoft/winget-pkgs` yet. |
| `publish-winget` fails with auth error | `WINGET_TOKEN` is missing or doesn't have `public_repo` scope. |
| `ci.yml` build succeeds locally but fails on a tag push | Likely a `setuptools-scm` issue: locally you used `SETUPTOOLS_SCM_PRETEND_VERSION`, in CI it relies on git tags. Confirm `fetch-depth: 0` is still in the checkout step. |
| Release tag pushed but no GitHub Release appears | One of the matrix builds failed. Check `release.yml`'s build job for the failed platform. |

## Architecture notes

- The wheel is **pure Python with no native code** (the only third-party runtime dependency is `xpoz` itself). The same `xpoz_cli-X.Y.Z-py3-none-any.whl` works on Mac/Linux/Windows for any Python ≥3.11. We don't ship platform-specific wheels.
- The PyInstaller binaries and the wheel are independently buildable and useful: the binary is what package managers like Homebrew distribute (zero Python dependency for end users), the wheel is what `pip install xpoz-cli` delivers (requires Python).
- `publish.yml` rebuilds the wheel from the tag rather than reusing an artifact from `release.yml`, because `release.yml`'s artifact retention is 7 days and a `workflow_dispatch` republish 8+ days later would otherwise fail. Rebuilding is deterministic for pure-Python packages.
