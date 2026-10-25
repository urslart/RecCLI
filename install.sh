#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
bin_home="${XDG_BIN_HOME:-${HOME}/.local/bin}"
install_dir="${data_home}/reccli"
venv_dir="${install_dir}/venv"
launcher="${bin_home}/reccli"

if [[ ! -f "${project_dir}/pyproject.toml" ]]; then
    printf 'Could not find pyproject.toml in %s\n' "$project_dir" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3 is required. Install Python 3 and its venv support using your distro package manager.\n' >&2
    exit 1
fi

if [[ -e "$launcher" || -L "$launcher" ]]; then
    resolved_launcher="$(readlink -f -- "$launcher" 2>/dev/null || true)"
    if [[ "$resolved_launcher" != "${venv_dir}/bin/reccli" ]]; then
        printf 'A different reccli command already exists at %s\n' "$launcher" >&2
        printf 'Remove or uninstall that installation first, then rerun this script.\n' >&2
        exit 1
    fi
fi

mkdir -p "$install_dir" "$bin_home"
if [[ ! -x "${venv_dir}/bin/python" ]]; then
    python3 -m venv "$venv_dir" || {
        printf 'Could not create a Python virtual environment. Install your distro package for Python venv support, then retry.\n' >&2
        exit 1
    }
fi

"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install --editable "$project_dir"

ln -sfn -- "${venv_dir}/bin/reccli" "$launcher"

printf '\nInstalled the reccli command at %s\n' "$launcher"

missing=()
for tool in ffmpeg; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [[ -n "${WAYLAND_DISPLAY:-}" ]] && ! command -v wf-recorder >/dev/null 2>&1; then
    missing+=("wf-recorder (Wayland screen capture)")
fi
if ! command -v pactl >/dev/null 2>&1 || ! command -v parec >/dev/null 2>&1; then
    missing+=("pactl and parec (Linux system audio capture)")
fi
if ! "${venv_dir}/bin/python" -c 'import sounddevice' >/dev/null 2>&1; then
    missing+=("PortAudio runtime library (required by Python sounddevice)")
fi
if ((${#missing[@]})); then
    printf 'Install these system tools with your distro package manager for the related recording features:\n'
    printf '  - %s\n' "${missing[@]}"
fi

case ":${PATH}:" in
    *":${bin_home}:"*) printf '\nYou can now run: reccli\n' ;;
    *)
        printf '\nAdd %s to your PATH before running reccli.\n' "$bin_home"
        printf 'For fish, run: fish_add_path %q\n' "$bin_home"
        printf 'For bash/zsh, add this to your shell startup file: export PATH=%q:"$PATH"\n' "$bin_home"
        ;;
esac
