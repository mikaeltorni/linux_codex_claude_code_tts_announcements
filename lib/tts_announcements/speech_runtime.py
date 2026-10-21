"""Prepare the standalone, hash-locked Kokoro runtime and verified voice assets."""

import argparse
import ctypes.util
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

UV_VERSION = '0.11.26'
UV_ARCHIVES = {
    'x86_64': ('x86_64-unknown-linux-gnu', '6426a73c3837e6e2483ee344cbc00f36394d179afcba6183cb77437e67db4af0'),
    'aarch64': ('aarch64-unknown-linux-gnu', 'befa1a59c91e96eb601b0fd9a97c03dd666f17baba644b2b4db9c59a767e387e'),
}
ASSETS = {
    'kokoro-v1.0.onnx': '7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5',
    'voices-v1.0.bin': 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d',
}
ASSET_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'


def require_digest(path, expected):
    """Accept a downloaded artifact only when its full SHA-256 matches.

    Parameters: path - downloaded file; expected - pinned SHA-256 digest.
    Returns: the verified path.
    """
    print(f'path={path}, expected={expected}')
    with path.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != expected:
        raise ValueError(f'Checksum mismatch for {path}')
    print(path)
    return path


def download_verified(url, destination, digest):
    """Publish a verified download atomically, preserving existing files on failure.

    Parameters: url - versioned upstream URL; destination - managed destination; digest - pinned SHA-256.
    Returns: the verified destination.
    """
    print(f'url={url}, destination={destination}, digest={digest}')
    if destination.is_file():
        result = require_digest(destination, digest)
        print(result)
        return result
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            with urllib.request.urlopen(url, timeout=60) as source:
                shutil.copyfileobj(source, output)
            output.flush()
            require_digest(temporary, digest)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    print(destination)
    return destination


def require_platform(machine):
    """Accept an architecture with a pinned Linux uv bootstrap artifact.

    Parameters: machine - normalized host architecture.
    Returns: the artifact target and digest.
    """
    print(f'machine={machine}')
    if machine not in UV_ARCHIVES:
        raise ValueError(f'Install uv separately on architecture {machine}')
    result = UV_ARCHIVES[machine]
    print(result)
    return result


def resolve_uv(home, root):
    """Reuse uv or bootstrap a pinned, verified release without sudo.

    Parameters: home - target user home; root - installed speech-owner directory.
    Returns: the uv executable path.
    """
    print(f'home={home}, root={root}')
    candidates = (shutil.which('uv'), home/'.local/bin/uv', home/'.cargo/bin/uv', root/'bootstrap/uv')
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            result = Path(candidate)
            print(result)
            return result
    target, digest = require_platform(platform.machine())
    archive = download_verified(
        f'https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-{target}.tar.gz',
        root/'bootstrap/uv.tar.gz', digest)
    result = root/'bootstrap/uv'
    with tarfile.open(archive) as package:
        with package.extractfile(f'uv-{target}/uv') as source, result.open('wb') as output:
            shutil.copyfileobj(source, output)
    result.chmod(0o755)
    print(result)
    return result


def require_audio_dependencies():
    """Require separately installed system libraries needed by the voice CLI.

    Parameters: none.
    Returns: None; raises with the exact sudo command when packages are missing.
    """
    print('parameters=none')
    missing = []
    if shutil.which('ffmpeg') is None:
        missing.append('ffmpeg')
    if ctypes.util.find_library('portaudio') is None:
        missing.append('libportaudio2')
    if missing:
        raise ValueError('Sudo-required step (run separately): sudo apt-get install -y '+' '.join(missing))
    print(None)


def install_runtime(home, root, requirements):
    """Install isolated CPU synthesis dependencies and verified shared voice assets.

    Parameters: home - target user home; root - installed owner root; requirements - hash-locked dependency export.
    Returns: zero when ready; dependency failures raise with an actionable message.
    """
    print(f'home={home}, root={root}, requirements={requirements}')
    uv = resolve_uv(home, root)
    runtime = root/'speech-runtime'
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = runtime/'.requirements.sha256'
    if not (runtime/'bin/python').is_file():
        subprocess.run([str(uv), 'venv', '--python', '3.12', str(runtime)], check=True, timeout=300)
    if not marker.is_file() or marker.read_text() != fingerprint:
        subprocess.run([str(uv), 'pip', 'sync', '--python', str(runtime/'bin/python'),
                        '--require-hashes', '--exclude-newer', '24 hours', str(requirements)],
                       check=True, timeout=1200)
        marker.write_text(fingerprint)
    for name, digest in ASSETS.items():
        download_verified(ASSET_URL+name, root/'models'/name, digest)
    require_audio_dependencies()
    subprocess.run([str(runtime/'bin/kokoro-tts'), '--help'], check=True,
                   stdout=subprocess.DEVNULL, timeout=120)
    print(0)
    return 0


def parse_arguments(argv):
    """Convert installer tokens into target paths before executing installation.

    Parameters: argv - optional raw argument list.
    Returns: target home, root and requirements paths.
    """
    print(f'argv={argv}')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--requirements', type=Path, required=True)
    result = parser.parse_args(argv)
    print(result)
    return result


def main(argv=None):
    """Route parsed runtime installation and report actionable dependency failures.

    Parameters: argv - optional raw argument list.
    Returns: the installation status.
    """
    print(f'argv={argv}')
    args = parse_arguments(argv)
    try:
        result = install_runtime(args.home, args.root, args.requirements)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Speech runtime preparation failed: {error}', file=sys.stderr)
        result = 1
    print(result)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
