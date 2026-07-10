#!/usr/bin/env bash
set -euo pipefail

REPO="${DROID_BYOK_REPO:-despriber/droid-byok}"
VERSION="${DROID_BYOK_VERSION:-latest}"
INSTALL_DIR="${DROID_BYOK_INSTALL_DIR:-${HOME}/.local/bin}"

fail() {
  printf 'droid-byok installer: %s\n' "$*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

case "$(uname -s)" in
  Linux) os="linux" ;;
  Darwin) os="macos" ;;
  *) fail "unsupported operating system: $(uname -s)" ;;
esac

case "$(uname -m)" in
  x86_64 | amd64) arch="x86_64" ;;
  arm64 | aarch64) arch="arm64" ;;
  *) fail "unsupported architecture: $(uname -m)" ;;
esac

asset="droid-byok-${os}-${arch}.tar.gz"
if [[ -n "${DROID_BYOK_DOWNLOAD_BASE:-}" ]]; then
  base_url="${DROID_BYOK_DOWNLOAD_BASE%/}"
elif [[ "$VERSION" == "latest" ]]; then
  base_url="https://github.com/${REPO}/releases/latest/download"
else
  base_url="https://github.com/${REPO}/releases/download/${VERSION}"
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

curl_args=(
  -fL
  --retry "${DROID_BYOK_DOWNLOAD_RETRIES:-8}"
  --retry-delay 2
  --connect-timeout "${DROID_BYOK_CONNECT_TIMEOUT:-30}"
)
if curl --help all 2>/dev/null | grep -q -- '--retry-all-errors'; then
  curl_args+=(--retry-all-errors)
fi

printf 'Downloading checksum for %s...\n' "$asset"
curl "${curl_args[@]}" \
  "${base_url}/${asset}.sha256" -o "${tmp_dir}/${asset}.sha256"

expected="$(awk '{print $1}' "${tmp_dir}/${asset}.sha256")"
[[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || fail "release checksum is invalid"

printf 'Downloading %s...\n' "$asset"
curl "${curl_args[@]}" \
  "${base_url}/${asset}" -o "${tmp_dir}/${asset}"

if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "${tmp_dir}/${asset}" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  actual="$(shasum -a 256 "${tmp_dir}/${asset}" | awk '{print $1}')"
else
  fail "sha256sum or shasum is required"
fi
[[ "$actual" == "$expected" ]] || fail "SHA-256 verification failed"

tar -xzf "${tmp_dir}/${asset}" -C "$tmp_dir"
[[ -f "${tmp_dir}/droid-byok" ]] || fail "release archive does not contain droid-byok"

mkdir -p "$INSTALL_DIR"
install -m 755 "${tmp_dir}/droid-byok" "${INSTALL_DIR}/droid-byok"

printf 'Installed droid-byok to %s\n' "${INSTALL_DIR}/droid-byok"
"${INSTALL_DIR}/droid-byok" --version

case ":${PATH}:" in
  *":${INSTALL_DIR}:"*) ;;
  *) printf 'Add %s to PATH to run droid-byok from any shell.\n' "$INSTALL_DIR" ;;
esac
