# droid-byok

[English](README.md) | [简体中文](README.zh-CN.md)

`droid-byok` is a full-screen TUI and CLI for managing Factory Droid BYOK
providers, upstream models, and the default model stored in
`~/.factory/settings.json`.

## Features

- Add, edit, remove, and activate BYOK providers.
- Fetch the upstream model catalog and choose which models to add.
- Search providers and fetched models.
- Preserve and repair Droid model references when configuration changes.
- Probe provider endpoints concurrently with structured health results.
- Back up `settings.json` before writes.
- Responsive truecolor TUI for wide and compact terminals.

## Requirements

- Python 3.10 or newer
- Factory Droid
- A terminal with UTF-8 support

## Install

Install the standalone binary on Linux or macOS. This does not require Python:

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | bash
```

Install a specific release or choose another destination:

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | \
  DROID_BYOK_VERSION=v0.3.1 bash
```

The installer detects the OS and CPU architecture, downloads the matching
binary from GitHub Releases, verifies its SHA-256 checksum, and installs it to
`~/.local/bin` by default.

The Python package can alternatively be installed with `pipx`, which keeps the
application in an isolated environment:

```bash
pipx install .
droid-byok
```

For development without installation:

```bash
python3 -m pip install -r requirements.txt
./droid-byok
```

After the repository is published on GitHub, users can install it directly:

```bash
pipx install git+https://github.com/despriber/droid-byok.git
```

They can also install a wheel downloaded from GitHub Releases:

```bash
pipx install droid_byok-0.3.1-py3-none-any.whl
```

## Usage

Start the TUI:

```bash
droid-byok
```

Useful CLI commands:

```bash
droid-byok provider list
droid-byok provider current
droid-byok provider speedtest
droid-byok models list
droid-byok --help
```

TUI shortcuts include `/` to filter providers, `f` to fetch models, `u` to set
the default provider/model, `m` to inspect live models, and `?` for help.

## Data And Security

Runtime configuration is stored outside the source tree:

```text
~/.factory/settings.json
~/.factory/droid-byok/providers.json
~/.factory/droid-byok/backups/
```

These files can contain API keys. Never commit or attach them to a release.
They are excluded by `.gitignore`. The repository only includes an empty
`providers.example.json` showing the store structure.

The paths may be overridden with `FACTORY_HOME`, `DROID_SETTINGS`,
`DROID_BYOK_STORE`, and `DROID_BYOK_BACKUP_DIR`.

## Build A Release

Install the build frontend and create both a wheel and source archive:

```bash
python3 -m pip install build
python3 -m build
```

Artifacts are written to `dist/`.

## Publish On GitHub

Create an empty public repository, then run:

```bash
cd /home/despriber/droid-byok
git init -b main
git add .
git commit -m "Initial release"
git remote add origin git@github.com:despriber/droid-byok.git
git push -u origin main

git tag v0.3.1
git push origin v0.3.1
```

The included GitHub Actions workflow automatically builds and uploads release
packages whenever a `v*` tag is pushed. The commands above are therefore
enough for normal releases.

To upload the locally built packages manually with GitHub CLI instead:

```bash
gh release create v0.3.1 dist/* \
  --title "droid-byok v0.3.1" \
  --notes "Initial public release"
```

Users can then download the wheel or source archive from the repository's
Releases page. Publishing to PyPI can be added later after registering the
package name and configuring a PyPI trusted publisher or API token.

## License

MIT
