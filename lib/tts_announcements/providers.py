"""Optional native CLI installation delegated to linux_codex_claude_code_setup."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .terminal import choose_option

PROVIDERS = {'codex': 'codex_cli', 'claude': 'claude_code'}
DEFAULT_REPOSITORY = 'https://github.com/mikaeltorni/linux_codex_claude_code_setup.git'


def find_runtime(home, kind):
    """Find a native CLI without mistaking a settings directory for installation.

    Parameters: home - target user's home; kind - native CLI name.
    Returns: executable path, or None when absent.
    """
    print(f'home={home}, kind={kind}', file=sys.stderr)
    local = home / '.local/bin' / kind
    result = str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which(kind)
    print(result, file=sys.stderr)
    return result


def parse_selection(value):
    """Convert one raw selector into a mode and native provider names.

    Parameters: value - comma-separated provider names or ask/missing/none.
    Returns: mode and normalized provider tuple.
    """
    print(f'value={value}', file=sys.stderr)
    words = tuple(part.strip().lower() for part in value.split(','))
    if words in (('ask',), ('missing',), ('none',)):
        result = (words[0], ())
    elif words and all(word in PROVIDERS for word in words):
        result = ('explicit', tuple(dict.fromkeys(words)))
    else:
        raise argparse.ArgumentTypeError('choose codex, claude, codex,claude, missing, or none')
    print(result, file=sys.stderr)
    return result


def require_terminal():
    """Require a real terminal for an interactive installation decision.

    Parameters: none.
    Returns: None.
    """
    print('parameters=none', file=sys.stderr)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Interactive CLI selection needs a terminal; use --install-harnesses missing or explicit names.')
    print(None, file=sys.stderr)


def require_tool(name):
    """Require a bootstrap tool without running sudo or installing system packages.

    Parameters: name - executable needed for cloning the provider owner.
    Returns: None.
    """
    print(f'name={name}', file=sys.stderr)
    if shutil.which(name) is None:
        raise ValueError(f'Missing {name}. Sudo-required step: sudo apt-get install -y git ca-certificates curl build-essential nodejs npm')
    print(None, file=sys.stderr)


def require_installer(checkout):
    """Accept only a checkout containing the delegated public installer.

    Parameters: checkout - existing provider repository directory.
    Returns: installer path.
    """
    print(f'checkout={checkout}', file=sys.stderr)
    result = checkout / 'install.sh'
    if not result.is_file():
        raise ValueError(f'Provider checkout has no install.sh: {checkout}; existing files were preserved.')
    print(result, file=sys.stderr)
    return result


def resolve_owner(home):
    """Reuse an explicit/sibling checkout or clone the public owner without credentials.

    Parameters: home - target user's home.
    Returns: provider install.sh path.
    """
    print(f'home={home}', file=sys.stderr)
    configured = os.environ.get('TTS_CLI_SETUP_DIR')
    checkout = Path(configured).expanduser() if configured else home / 'projects/linux_codex_claude_code_setup'
    sibling = Path(__file__).resolve().parents[3] / 'linux_codex_claude_code_setup'
    if not configured and (sibling / 'install.sh').is_file():
        checkout = sibling
    if not checkout.exists():
        require_tool('git')
        checkout.parent.mkdir(parents=True, exist_ok=True)
        repository = os.environ.get('TTS_CLI_SETUP_REPOSITORY', DEFAULT_REPOSITORY)
        print(f'Cloning native CLI installer into {checkout}', flush=True)
        subprocess.run(['git', 'clone', '--depth', '1', '--', repository, str(checkout)],
                       env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}, check=True, timeout=300)
    result = require_installer(checkout)
    print(result, file=sys.stderr)
    return result


def choose_providers(home, mode, requested):
    """Resolve optional installation choices before running the provider installer.

    Parameters: home - target home; mode - parsed selection mode; requested - explicit provider tuple.
    Returns: selected provider tuple, or None when cancelled.
    """
    print(f'home={home}, mode={mode}, requested={requested}', file=sys.stderr)
    result = requested
    if mode in ('missing', 'ask'):
        missing = tuple(kind for kind in PROVIDERS if find_runtime(home, kind) is None)
        if mode == 'ask' and missing:
            require_terminal()
            selected = []
            for kind in missing:
                decision = choose_option(f'Install {kind} (not found)', 'skip', ('skip', 'install'))
                if decision is None:
                    print(None, file=sys.stderr)
                    return None
                if decision == 'install':
                    selected.append(kind)
            result = tuple(selected)
        else:
            result = missing
    print(result, file=sys.stderr)
    return result


def require_installed(home, providers):
    """Verify that the delegated owner actually installed working native commands.

    Parameters: home - target home; providers - selected native command names.
    Returns: None.
    """
    print(f'home={home}, providers={providers}', file=sys.stderr)
    for kind in providers:
        command = find_runtime(home, kind)
        if command is None:
            raise ValueError(f'Provider installer completed but {kind} is not executable.')
        subprocess.run([command, '--version'], check=True, timeout=60)
    print(None, file=sys.stderr)


def install_providers(home, selection, source):
    """Install selected native CLIs through their owner and verify their public versions.

    Parameters: home - target home; selection - parsed mode/provider tuple; source - Codex npm/fork source.
    Returns: zero after success, or 130 when selection is cancelled.
    """
    print(f'home={home}, selection={selection}, source={source}', file=sys.stderr)
    mode, requested = selection
    providers = choose_providers(home, mode, requested)
    if providers is None:
        print('CLI installation cancelled; no provider was installed.')
        print(130, file=sys.stderr)
        return 130
    if providers:
        installer = resolve_owner(home)
        arguments = ['bash', str(installer), '--barebones', '--select',
                     ','.join(PROVIDERS[kind] for kind in providers),
                     '--codex-source', source, '--home', str(home)]
        environment = {**os.environ, 'HOME': str(home),
                       'PATH': str(home / '.local/bin') + os.pathsep + os.environ.get('PATH', ''),
                       'GIT_TERMINAL_PROMPT': '0'}
        subprocess.run(arguments, env=environment, check=True, timeout=7200)
        require_installed(home, providers)
    print(0, file=sys.stderr)
    return 0


def parse_arguments(argv):
    """Parse provider syntax and convert selectors before routing operations.

    Parameters: argv - optional raw command-line tokens.
    Returns: normalized target, provider selection, source and optional detection selector.
    """
    print(f'argv={argv}', file=sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--selection', type=parse_selection, default='none')
    parser.add_argument('--source', choices=('npm', 'fork'), default=os.environ.get('TTS_CODEX_SOURCE', 'npm'))
    parser.add_argument('--detect', choices=tuple(PROVIDERS))
    result = parser.parse_args(argv)
    print(result, file=sys.stderr)
    return result


def main(argv=None):
    """Route native CLI discovery or optional provisioning without handling raw tokens twice.

    Parameters: argv - optional raw command-line tokens.
    Returns: operation status, usage failure, or the delegated installer's nonzero status.
    """
    print(f'argv={argv}', file=sys.stderr)
    args = parse_arguments(argv)
    try:
        if args.detect:
            result = 0 if find_runtime(args.home, args.detect) else 1
        else:
            result = install_providers(args.home, args.selection, args.source)
    except subprocess.CalledProcessError as error:
        print(f'Native CLI installation failed with status {error.returncode}', file=sys.stderr)
        result = error.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'Native CLI installation failed: {error}', file=sys.stderr)
        result = 1
    print(result, file=sys.stderr)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
