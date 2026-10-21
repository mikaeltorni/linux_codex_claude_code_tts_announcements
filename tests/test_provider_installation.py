"""Public TTS installer contracts for optional native Codex/Claude provisioning."""

import os
from pathlib import Path
import subprocess

from test_voice_installation import FRAMEWORK, ROOT, run_manual


def prepare_owner(home, owner):
    """Create a controlled provider owner whose CLI writes only isolated fixtures.

    Parameters: home - isolated user home; owner - fixture owner checkout.
    Returns: None.
    """
    print(f'home={home}, owner={owner}')
    home.mkdir(parents=True, exist_ok=True)
    owner.mkdir(parents=True)
    (owner / 'install.sh').write_text('''#!/bin/bash
set -eu
printf '%s\\n' "$@" > "$HOME/provider-call"
if [ "${TTS_TEST_OWNER_STATUS:-0}" != 0 ]; then exit "$TTS_TEST_OWNER_STATUS"; fi
selection=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = --select ]; then selection="$2"; shift; fi
  shift
done
mkdir -p "$HOME/.local/bin"
case ",$selection," in
  *,codex_cli,*) printf '#!/bin/bash\\nprintf "codex fixture 1.0\\\\n"\\n' > "$HOME/.local/bin/codex"; chmod +x "$HOME/.local/bin/codex" ;;
esac
case ",$selection," in
  *,claude_code,*) printf '#!/bin/bash\\nprintf "claude fixture 1.0\\\\n"\\n' > "$HOME/.local/bin/claude"; chmod +x "$HOME/.local/bin/claude" ;;
esac
''')
    print(None)


def run_installer(home, owner, selection, status='0'):
    """Call the public unattended provider installer in an isolated home.

    Parameters: home - isolated user home; owner - controlled provider owner; selection - raw provider selector; status - fixture owner exit status.
    Returns: completed installer process.
    """
    print(f'home={home}, owner={owner}, selection={selection}, status={status}')
    env = {'HOME': str(home), 'TTS_TARGET_HOME': str(home), 'PATH': '/usr/bin:/bin',
           'ISC_FUNCTIONS_DIR': str(FRAMEWORK), 'TTS_SKIP_SYSTEMD': '1',
           'ATTS_INSTALL_GPU_RUNTIME': '0', 'TTS_LOG_DIR': str(home/'logs'),
           'TTS_INSTALL_SPEECH_RUNTIME': '0',
           'TTS_CLI_SETUP_DIR': str(owner), 'TTS_TEST_OWNER_STATUS': status}
    result = subprocess.run(['bash', str(ROOT/'install.sh'), '--install-harnesses', selection],
                            env=env, text=True, capture_output=True, timeout=20)
    print((result.returncode, result.stdout, result.stderr))
    return result


def test_explicit_both_installs_owner_then_configures_detected_harnesses(tmp_path):
    """Install both native CLIs in one delegated call and wire their default voices.

    Parameters: tmp_path - isolated checkout/home root.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home, owner = tmp_path/'home', tmp_path/'owner'
    prepare_owner(home, owner)
    result = run_installer(home, owner, 'codex,claude')
    assert result.returncode == 0, result.stdout + result.stderr
    arguments = (home/'provider-call').read_text().splitlines()
    assert arguments == ['--barebones', '--select', 'codex_cli,claude_code', '--codex-source', 'npm', '--home', str(home)]
    assert os.access(home/'.local/bin/codex', os.X_OK)
    assert os.access(home/'.local/bin/claude', os.X_OK)
    assert 'ATTS_CODEX_VOICE=af_bella' in (home/'.codex/hooks.json').read_text()
    assert 'ATTS_CLAUDE_VOICE=af_sky' in (home/'.claude/settings.json').read_text()
    assert not (home/'.config/agent-tts/voices.json').exists()
    print(None)


def test_missing_checks_native_binaries_not_just_config_homes(tmp_path):
    """Skip an installed Codex and install Claude despite an existing config home.

    Parameters: tmp_path - isolated checkout/home root.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home, owner = tmp_path/'home', tmp_path/'owner'
    prepare_owner(home, owner)
    (home/'.local/bin').mkdir(parents=True)
    existing = home/'.local/bin/codex'
    existing.write_text('#!/bin/bash\nprintf "existing codex\\n"\n')
    existing.chmod(0o755)
    (home/'.claude').mkdir()
    before = existing.read_bytes()
    result = run_installer(home, owner, 'missing')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home/'provider-call').read_text().splitlines()[2] == 'claude_code'
    assert existing.read_bytes() == before
    print(None)


def test_invalid_selection_and_owner_failure_do_not_enable_hooks(tmp_path):
    """Reject malformed provider choices before effects and propagate owner errors.

    Parameters: tmp_path - isolated checkout/home root.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home, owner = tmp_path/'home', tmp_path/'owner'
    prepare_owner(home, owner)
    for value in ('unknown', '', 'codex,', 'codex,unknown'):
        result = run_installer(home, owner, value)
        assert result.returncode != 0, value
        assert not (home/'provider-call').exists(), value
        assert not (home/'.config/agent-tts/harness-hooks.enabled').exists(), value
    result = run_installer(home, owner, 'codex,claude', status='9')
    assert result.returncode == 9, result.stdout + result.stderr
    assert not (home/'.config/agent-tts/harness-hooks.enabled').exists()
    print(None)


def test_manual_offers_missing_clis_before_voice_selection(tmp_path):
    """Install both missing CLIs from the terminal and select their voices.

    Parameters: tmp_path - isolated provider checkout and target home.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home, owner = tmp_path/'home', tmp_path/'owner'
    prepare_owner(home, owner)
    output = run_manual(home, [b'\x1b[B\n', b'\x1b[B\n', b'\n', b'\n'],
                        providers='ask', owner=owner)
    assert 'Install codex (not found)' in output
    assert 'Install claude (not found)' in output
    assert output.index('Install claude') < output.index('Voice for codex')
    assert (home/'provider-call').read_text().splitlines()[2] == 'codex_cli,claude_code'
    assert 'ATTS_CODEX_VOICE=af_bella' in (home/'.codex/hooks.json').read_text()
    assert 'ATTS_CLAUDE_VOICE=af_sky' in (home/'.claude/settings.json').read_text()
    print(None)


def test_manual_skip_and_cancel_preserve_native_installation(tmp_path):
    """Keep native installation optional and cancel before configuration changes.

    Parameters: tmp_path - isolated provider checkout and target homes.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    for label, keys in (('skip', [b'\n', b'\n']),
                        ('cancel', [b'\x1b[B\n', b'q'])):
        home, owner = tmp_path/label/'home', tmp_path/label/'owner'
        prepare_owner(home, owner)
        output = run_manual(home, keys, providers='ask', owner=owner)
        assert 'Install codex (not found)' in output, label
        assert not (home/'provider-call').exists(), label
        assert not (home/'.codex').exists(), label
        assert not (home/'.claude').exists(), label
        assert not (home/'.config/agent-tts/voices.json').exists(), label
        assert not (home/'.config/agent-tts/harness-hooks.enabled').exists(), label
    print(None)


def test_individual_and_no_provider_choices(tmp_path):
    """Accept either provider alone and skip delegation for an explicit opt-out.

    Parameters: tmp_path - isolated provider checkout and target homes.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    for selection, component in (('codex', 'codex_cli'), ('claude', 'claude_code'), ('none', None)):
        home, owner = tmp_path/selection/'home', tmp_path/selection/'owner'
        prepare_owner(home, owner)
        result = run_installer(home, owner, selection)
        assert result.returncode == 0, (selection, result.stdout, result.stderr)
        if component is None:
            assert not (home/'provider-call').exists()
        else:
            assert (home/'provider-call').read_text().splitlines()[2] == component
        for kind in ('codex', 'claude'):
            assert os.access(home/'.local/bin'/kind, os.X_OK) == (kind == selection), selection
    print(None)
