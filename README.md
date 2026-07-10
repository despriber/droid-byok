# droid-byok

[English](README.md) | [简体中文](README.zh-CN.md)

Manage **Factory Droid BYOK** (Bring Your Own Key) from the terminal.

If you use [Factory Droid](https://docs.factory.ai/) with your own API keys, OpenAI-compatible relays, Anthropic endpoints, or third-party model gateways, you eventually end up editing `~/.factory/settings.json` by hand. That works once. It gets messy when you juggle multiple providers, switch default models, and try not to break `customModels` references.

`droid-byok` is a full-screen TUI plus a small CLI for that job:

- keep multiple BYOK **provider profiles**
- pull models from an upstream `/models` catalog
- write them into Droid's live `customModels`
- switch the default model without trashing the rest of your config
- probe endpoints when something feels slow or dead

Inspired by tools like `cc-switch`, but aimed at Droid's BYOK layout.

## Why this exists

Factory's BYOK flow is powerful, but multi-provider day-to-day work is still mostly JSON surgery:

| Pain | What droid-byok does |
| --- | --- |
| Multiple API keys / base URLs | Store them as named provider profiles |
| Adding models one by one | Fetch the upstream model list and pick what you want |
| Switching defaults | One keypress / one command |
| Broken model refs after edits | Repair session + mission model references |
| "Is this endpoint even up?" | Concurrent speedtest / health probe |
| Fear of nuking settings | Auto-backup `settings.json` before writes |

Useful search terms if you landed here from Google or GitHub: **Factory Droid**, **Droid BYOK**, **bring your own key**, **customModels**, **settings.json**, **OpenAI-compatible provider**, **Anthropic BYOK**, **LLM gateway**, **model switcher TUI**.

## Features

- Full-screen truecolor TUI (Textual) that still works in smaller terminals
- CLI for scripts and quick one-liners
- Provider CRUD: add / edit / delete / activate
- Import your current live `settings.json` as a provider profile
- Fetch upstream models (`/models`, including common `/v1/models` variants)
- Search / filter providers and fetched models
- Set Droid session default model, and sync mission-related model fields when present
- Preserve stable `custom:*` model IDs when possible
- Concurrent endpoint probing with status + latency
- Atomic writes + timestamped backups
- API keys can be plain values or `${ENV_VAR}` references

## Requirements

- Factory Droid installed and using `~/.factory/settings.json`
- A UTF-8 terminal
- For the Python install path: Python 3.10+
- Standalone binaries do **not** require Python

## Install

### One-liner (Linux / macOS binary)

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | bash
```

Pin a release:

```bash
curl -fsSL https://raw.githubusercontent.com/despriber/droid-byok/main/install.sh | \
  DROID_BYOK_VERSION=v0.3.2 bash
```

The script picks OS/arch, downloads the GitHub Release asset, checks SHA-256, and installs to `~/.local/bin` by default (`DROID_BYOK_INSTALL_DIR` overrides that).

### pipx / Python package

```bash
# from a clone
pipx install .

# or straight from GitHub
pipx install git+https://github.com/despriber/droid-byok.git
```

Dev checkout:

```bash
python3 -m pip install -r requirements.txt
./droid-byok
```

Wheel from Releases:

```bash
pipx install droid_byok-0.3.2-py3-none-any.whl
```

## Quick start

```bash
# open the TUI (default)
droid-byok

# or non-interactive
droid-byok provider add \
  --id openrouter \
  --name openrouter \
  --base-url https://openrouter.ai/api/v1 \
  --api-key "$OPENROUTER_API_KEY" \
  --model anthropic/claude-sonnet-4 \
  --apply

droid-byok use openrouter
droid-byok models list
```

Typical first session in the TUI:

1. `a` add a provider (base URL + API key)
2. `f` fetch upstream models and select what to keep
3. `Enter` / `u` set it as Droid's default
4. restart or reopen Droid and the model should show up

## CLI

```bash
droid-byok                        # TUI
droid-byok interactive            # same
droid-byok tui                    # same

droid-byok provider list
droid-byok provider current
droid-byok provider show <id>
droid-byok provider add --id ... --base-url ... --api-key ... --model ...
droid-byok provider delete <id>
droid-byok provider default <id> [--model <name>]
droid-byok provider switch <id>   # alias of default
droid-byok provider import-live   # snapshot live settings into a profile
droid-byok provider speedtest [id]

droid-byok use <id> [--model <name>]
droid-byok models list
droid-byok models show
droid-byok models default <id|name|displayName>
droid-byok help
droid-byok -V
```

Supported provider types when writing into Droid settings:

- `generic-chat-completion-api` (default, OpenAI-compatible)
- `openai`
- `anthropic`

## TUI keys

| Key | Action |
| --- | --- |
| `↑` `↓` / `j` `k` | Move |
| `Enter` / `u` | Set provider as default |
| `a` | Add provider |
| `e` | Edit |
| `d` | Delete |
| `i` | Import live settings |
| `f` | Fetch upstream models |
| `m` | Inspect live `customModels` |
| `t` | Speedtest |
| `/` | Filter |
| `r` | Refresh |
| `?` | Help |
| `q` | Quit |

## How it maps to Droid

| Path | Role |
| --- | --- |
| `~/.factory/settings.json` | Live Droid config (`customModels`, session default, mission models) |
| `~/.factory/droid-byok/providers.json` | Your provider profile store |
| `~/.factory/droid-byok/backups/` | Pre-write backups of `settings.json` |

Override with env vars:

- `FACTORY_HOME`
- `DROID_SETTINGS`
- `DROID_BYOK_STORE`
- `DROID_BYOK_BACKUP_DIR`

`droid-byok` does not replace Droid. It only manages BYOK provider/model config that Droid already understands.

## Security notes

Provider files and settings can hold API keys.

- never commit `~/.factory/**`
- never attach real `providers.json` / `settings.json` to issues or releases
- prefer `${ENV_VAR}` for keys when you can
- this repo only ships an empty `providers.example.json`

Writes are atomic (`*.tmp` then replace) and files are created mode `0600` where applicable.

## Build & release

```bash
python3 -m pip install build
python3 -m build   # wheel + sdist in dist/
```

Pushing a `v*` tag runs GitHub Actions, which builds Python packages and Linux/macOS x86_64/arm64 binaries and uploads them to Releases:

```bash
git tag v0.3.2
git push origin v0.3.2
```

## Related links

- Repo: https://github.com/despriber/droid-byok
- Factory docs: https://docs.factory.ai/
- Factory BYOK overview: https://docs.factory.ai/cli/byok/overview

## License

MIT
