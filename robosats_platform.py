"""Platform-specific locking, settings storage, and GnuPG discovery."""
from pathlib import Path
import base64
import errno
import json
import os
import shutil
import sys


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
