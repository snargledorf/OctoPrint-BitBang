"""The plugin's contract with the bundled bitbang binary.

The Go proxy is the listener -- it owns the data channel, the signaling,
and the PIN; the Python adapter only feeds it video. So the plugin's
real dependency is an argv built in _plugin.py against a CLI that lives
in another repository, on its own release cycle. Nothing else notices
when a flag there is renamed, and the failure lands on a Pi at startup.

Skipped unless BITBANG_BIN points at a binary, so a plain `pytest` still
works without a Go toolchain. CI builds bitbang-cli main and sets it.
"""

import os
import re
import subprocess

import pytest

BIN = os.environ.get('BITBANG_BIN')
pytestmark = pytest.mark.skipif(not BIN, reason='BITBANG_BIN not set')

# Every flag _supervise_go passes. Keep in step with the argv there.
PROXY_FLAGS = [
    '-program',
    '-target',
    '-v',
    '-video-fd',
    '-forward-client-ip',
    '-pin',
]


def _help(*args):
    r = subprocess.run([BIN, *args, '--help'], capture_output=True, text=True, timeout=30)
    return r.stdout + r.stderr


def test_the_binary_runs():
    r = subprocess.run([BIN, 'version'], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f'`bitbang version` failed: {r.stderr}'
    assert re.search(r'\d+\.\d+', r.stdout + r.stderr), 'no version in the output'


@pytest.mark.parametrize('flag', PROXY_FLAGS)
def test_serve_proxy_still_accepts(flag):
    """A renamed flag is a startup crash on every Pi, and the only place
    the two repos are joined is this argv."""
    text = _help('serve', 'proxy')
    assert flag in text, f'`serve proxy` no longer documents {flag}:\n{text}'


def test_the_full_argv_is_accepted():
    """Flags present in help is not the same as the combination parsing.
    -help exits before serving, so this is a parse check, not a run."""
    r = subprocess.run(
        [BIN, 'serve', 'proxy',
         '-program', 'octoprint',
         '-target', 'localhost:5000',
         '-v', '-video-fd', '3', '-forward-client-ip',
         '-pin', '1234',
         '-help'],
        capture_output=True, text=True, timeout=30,
    )
    combined = r.stdout + r.stderr
    for bad in ('flag provided but not defined', 'unknown subcommand'):
        assert bad not in combined, f'{bad}:\n{combined}'
