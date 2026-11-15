"""Platform-specific sleep prevention, locking, settings, and GnuPG discovery."""
from contextlib import contextmanager
from pathlib import Path
import base64
import errno
import json
import os
import shutil
import subprocess
import sys


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_awake():
    """Request that the system stay awake for this session while the display can sleep."""
    if os.name == 'nt':
        import ctypes

        set_execution_state = ctypes.windll.kernel32.SetThreadExecutionState
        set_execution_state.argtypes = (ctypes.c_uint32,)
        set_execution_state.restype = ctypes.c_uint32
        previous = set_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if not previous:
            print('Windows could not prevent idle sleep. Check your power settings before leaving.',
                  file=sys.stderr, flush=True)
        try:
            yield
        finally:
            if previous:
                set_execution_state(ES_CONTINUOUS | previous)
        return

    executable = shutil.which('caffeinate')
    awake = subprocess.Popen([executable, '-i', '-w', str(os.getpid())]) if executable else None
    try:
        yield
    finally:
        if awake is not None:
            awake.terminate()
            awake.wait()


def settings_directory():
    if os.name == 'nt':
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        return local / 'RoboSatsTelegram'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'RoboSatsTelegram'
    return Path.home() / '.config' / 'robosats-telegram'


def lock_file(path):
    handle = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise BlockingIOError(errno.EAGAIN, 'This file is already locked.') from None
        raise
    return handle


def protect_settings(value):
    import win32crypt

    try:
        encrypted = win32crypt.CryptProtectData(
            json.dumps(value).encode('utf-8'), 'RoboSats Telegram Bridge', None, None, None, 1)
    except Exception:
        raise OSError('Windows could not encrypt the local settings.') from None
    return {'windows_dpapi': base64.b64encode(encrypted).decode('ascii')}


def unprotect_settings(value):
    import win32crypt

    try:
        encrypted = base64.b64decode(value['windows_dpapi'], validate=True)
        _, plaintext = win32crypt.CryptUnprotectData(encrypted, None, None, None, 1)
        return json.loads(plaintext)
    except Exception:
        raise OSError('Windows could not read the settings with the current Windows account.') from None


def gpg_tool(name):
    executable = shutil.which(name)
    if executable or os.name != 'nt':
        return executable
    for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        root = os.environ.get(variable)
        if root:
            for directory in (Path(root) / 'GnuPG' / 'bin', Path(root) / 'Programs' / 'GnuPG' / 'bin'):
                candidate = directory / f'{name}.exe'
                if candidate.is_file():
                    return str(candidate)
    return None
