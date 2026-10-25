#!/usr/bin/env bash
# clean_webOS bootstrap: executes the multilingual Python assistant.
# No root access on the PC is necessary. The script never invokes rpm-ostree.
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo 'Run as your normal desktop user, not as root / sudo.' >&2
  exit 2
fi

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$HERE/clean_webos.py" ]]; then
  echo 'clean_webos.py is missing. Extract the complete repository, then re-run.' >&2
  exit 2
fi

need=()
for bin in python3 ssh scp; do
  if ! command -v "$bin" >/dev/null 2>&1; then need+=("$bin"); fi
done

if (( ${#need[@]} == 0 )); then
  exec python3 "$HERE/clean_webos.py" "$@"
fi

printf 'Missing prerequisites: %s\n' "${need[*]}"
printf '%s\n' 'Missing dependencies can be installed in an isolated container or with your OS package manager.'
if [[ ! -t 0 ]]; then
  echo 'Interactive confirmation required. Install Python 3 and OpenSSH.' >&2
  exit 2
fi

case "$(uname -s)" in
  Linux)
    if command -v rpm-ostree >/dev/null 2>&1 && command -v toolbox >/dev/null 2>&1; then
      printf '%s\n' 'Fedora Atomic/Bazzite detected. No packages will be installed on the host.'
      printf 'Create/use the clean-webos-toolbox container and install prerequisites THERE? [y/N] '
      read -r answer
      case "${answer,,}" in
        y|yes|o|oui)
          if ! toolbox list --containers 2>/dev/null | grep -Eq '(^|[[:space:]])clean-webos-toolbox([[:space:]]|$)'; then
            toolbox create --container clean-webos-toolbox
          fi
          # Only the container uses dnf; no root shell on the host.
          toolbox run --container clean-webos-toolbox sh -c 'sudo dnf install -y python3 openssh-clients'
          if ! toolbox run --container clean-webos-toolbox test -r "$HERE/clean_webos.py"; then
            echo 'Your source folder is not mounted inside Toolbx. Move it into your normal home directory.' >&2
            exit 2
          fi
          exec toolbox run --container clean-webos-toolbox python3 "$HERE/clean_webos.py" "$@"
          ;;
      esac
    elif command -v apt-get >/dev/null 2>&1; then
      printf 'Install Python 3 and OpenSSH with apt using sudo? [y/N] '
      read -r answer
      case "${answer,,}" in
        y|yes|o|oui)
          sudo apt-get update
          sudo apt-get install -y python3 openssh-client
          exec python3 "$HERE/clean_webos.py" "$@"
          ;;
      esac
    elif command -v dnf >/dev/null 2>&1 && ! command -v rpm-ostree >/dev/null 2>&1; then
      printf 'Install Python 3 and OpenSSH using dnf on this non-Atomic host? [y/N] '
      read -r answer
      case "${answer,,}" in
        y|yes|o|oui)
          sudo dnf install -y python3 openssh-clients
          exec python3 "$HERE/clean_webos.py" "$@"
          ;;
      esac
    fi
    ;;
  Darwin)
    if command -v brew >/dev/null 2>&1; then
      printf 'Install Python 3 with Homebrew? [y/N] '
      read -r answer
      case "${answer,,}" in
        y|yes|o|oui)
          brew install python
          exec python3 "$HERE/clean_webos.py" "$@"
          ;;
      esac
    fi
    ;;
esac

echo 'Cancelled. No system packages were installed.' >&2
exit 2
