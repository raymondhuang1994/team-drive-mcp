"""Read-only source boundary and guarded private state on POSIX and Windows.

Windows handles use OPEN_EXISTING and GENERIC_READ for source files. Directory
handles deny delete sharing so an approved directory chain cannot be rebound
while the corresponding read or enumeration is in progress. Reparse points,
remote/device paths, and multiply linked source files are deliberately excluded.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import sys
import threading
from pathlib import Path, PurePosixPath
from .errors import DriveError

_DB_OPEN_LOCK = threading.Lock()


def _live_fds():
    result = set()
    for value in os.listdir("/dev/fd"):
        if value.isdigit():
            try:
                os.fstat(int(value))
                result.add(value)
            except OSError:
                pass
    return result


def online_only(info):
    return bool(getattr(info, "st_flags", 0) & getattr(stat, "UF_DATALESS", 0x40000000)) or bool(getattr(info, "st_file_attributes", 0) & (0x1000 | 0x40000 | 0x400000))


def relative_parts(relative):
    if not isinstance(relative, str) or not relative or len(relative) > 4096 or "\\" in relative or "\0" in relative:
        raise DriveError("INVALID_PATH", "Use a relative file path within the approved root.")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DriveError("INVALID_PATH", "Absolute paths and parent traversal are forbidden.")
    if os.name == "nt":
        for part in path.parts:
            _windows_component(part)
    return path.parts


def _windows_component(part):
    if not part or any(c in part for c in '<>:"|?*') or part[-1:] in (".", " ") or any(ord(c) < 32 for c in part) or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
        raise DriveError("INVALID_PATH", "Device names, alternate streams, and ambiguous Windows paths are forbidden.")


def _identity(path):
    try:
        info = path.stat()
        return info.st_dev, info.st_ino
    except FileNotFoundError:
        return None


def contains_physical(parent, child):
    """Compare actual ancestors, including case/Unicode aliases on APFS/NTFS."""
    expected = _identity(parent)
    if expected is None:
        return parent == child or parent in child.parents
    return any(_identity(candidate) == expected for candidate in (child,) + tuple(child.parents))


def overlaps(a, b):
    return contains_physical(a, b) or contains_physical(b, a)


def _make_posix_state(path, source_identity):
    """Create each state component relative to its already opened parent."""
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) == source_identity:
                raise DriveError("UNSAFE_STATE", "State creation cannot enter the approved source directory.")
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=fd)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) == source_identity:
            raise DriveError("UNSAFE_STATE", "State cannot be the approved source directory.")
        return fd
    except Exception as exc:
        os.close(fd)
        if isinstance(exc, DriveError):
            raise
        raise DriveError("UNSAFE_STATE", "The state directory cannot be created without following a redirected path.")


class PosixSource:
    def __init__(self, root):
        if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "fwalk"):
            raise DriveError("UNSUPPORTED_PLATFORM", "Safe directory-relative file access is unavailable.")
        self.fd = None
        raw = Path(root).expanduser()
        try:
            if raw.is_symlink():
                raise DriveError("UNSAFE_ROOT", "The source root cannot be a symbolic link.")
            self.root = raw.resolve(strict=True)
            info = self.root.stat()
            if not stat.S_ISDIR(info.st_mode):
                raise DriveError("INVALID_ROOT", "The source root must be an existing directory.")
            self.identity = (info.st_dev, info.st_ino)
            self.fd = os.open(str(self.root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            pinned = os.fstat(self.fd)
            if (pinned.st_dev, pinned.st_ino) != self.identity:
                raise DriveError("SOURCE_ROOT_CHANGED", "The source directory changed during initialization.")
        except Exception as exc:
            self.close()
            if isinstance(exc, DriveError):
                raise
            raise DriveError("INVALID_ROOT", "The source root is missing or inaccessible.")

    def check_root(self):
        try:
            info = os.stat(self.root, follow_symlinks=False)
            valid = self.fd is not None and stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == self.identity
        except OSError:
            valid = False
        if not valid:
            raise DriveError("SOURCE_ROOT_CHANGED", "The approved source directory is missing or has been rebound.", False, "Restore the approved directory or configure a new source root and state directory.")

    def open_read(self, relative):
        self.check_root()
        parts = relative_parts(relative)
        parent_fd = os.dup(self.fd)
        source_fd = None
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise DriveError("UNSAFE_FILE", "Only ordinary files with one hard link are supported.")
            if online_only(before):
                raise DriveError("ONLINE_ONLY", "Online-only files are not hydrated automatically.")
            source_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            info = os.fstat(source_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise DriveError("UNSAFE_FILE", "Only ordinary files with one hard link are supported.")
            if online_only(info):
                raise DriveError("ONLINE_ONLY", "Online-only files are not hydrated automatically.")
            return source_fd, info
        except Exception as exc:
            if source_fd is not None:
                os.close(source_fd)
            if isinstance(exc, DriveError):
                raise
            raise DriveError("SOURCE_UNAVAILABLE", "The source is missing, inaccessible, or traverses a symbolic link.", True, "Refresh and check the approved folder.")
        finally:
            os.close(parent_fd)

    def walk(self, errors):
        self.check_root()
        for folder, dirs, files, folder_fd in os.fwalk(".", dir_fd=self.fd, follow_symlinks=False, onerror=lambda _: errors.append(True)):
            self.check_root()
            blocked_dirs = []
            for name in dirs:
                try:
                    info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or online_only(info):
                        blocked_dirs.append(name)
                except OSError:
                    errors.append(True)
                    blocked_dirs.append(name)
            dirs[:] = [name for name in dirs if name not in blocked_dirs]
            for name in files + blocked_dirs:
                try:
                    info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
                except OSError:
                    errors.append(True)
                    continue
                relative = (PurePosixPath(folder) / name).as_posix()
                online = online_only(info)
                blocked = not online and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                yield relative, info, blocked, online

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes
    from types import SimpleNamespace

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _INVALID = ctypes.c_void_p(-1).value
    _READ = 0x80000000
    _WRITE = 0x40000000
    _SHARE_READ_WRITE = 0x1 | 0x2  # Never FILE_SHARE_DELETE for pinned objects.
    _OPEN_EXISTING = 3
    _OPEN_ALWAYS = 4
    _OPEN_REPARSE = 0x00200000
    _BACKUP = 0x02000000
    _REPARSE = 0x400
    _DIRECTORY = 0x10

    class _FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    _kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel.GetDriveTypeW.restype = wintypes.UINT
    class _AttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    _kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _kernel.ReadFile.restype = wintypes.BOOL
    _kernel.GetFileType.argtypes = [wintypes.HANDLE]
    _kernel.GetFileType.restype = wintypes.DWORD

    def _extended(path):
        return "\\\\?\\" + str(path)

    def _canonical(path):
        value = str(path)
        if value.startswith("\\\\?\\"):
            value = value[4:]
        return os.path.normcase(os.path.normpath(value))

    def _file_info(handle):
        result = _FileInfo()
        if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(result)):
            raise OSError("Cannot inspect an opened file.")
        attribute_tag = _AttributeTagInfo()
        if result.attributes & _REPARSE and not _kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attribute_tag), ctypes.sizeof(attribute_tag)):
            raise OSError("Cannot inspect a reparse point.")
        def ns(value):
            return (((value.dwHighDateTime << 32) | value.dwLowDateTime) - 116444736000000000) * 100
        return SimpleNamespace(st_mode=stat.S_IFDIR if result.attributes & _DIRECTORY else stat.S_IFREG,
                               st_dev=result.volume, st_ino=(result.index_high << 32) | result.index_low,
                               st_size=(result.size_high << 32) | result.size_low,
                               st_mtime_ns=ns(result.write), st_ctime_ns=ns(result.creation),
                               st_nlink=result.links, st_file_attributes=result.attributes, st_reparse_tag=attribute_tag.tag)

    def _final_path(handle):
        required = _kernel.GetFinalPathNameByHandleW(handle, None, 0, 0)
        if not required:
            raise OSError("Cannot resolve an opened file.")
        buffer = ctypes.create_unicode_buffer(required + 1)
        copied = _kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not copied or copied >= len(buffer):
            raise OSError("Cannot resolve an opened file.")
        return _canonical(buffer.value)

    def _handle(path, directory=False, write=False, create=False, exclusive=False):
        access = _READ | (_WRITE if write else 0)
        # Pin directory metadata as well as its name: disallow write sharing so
        # SetReparsePoint cannot redirect an already approved directory in place.
        sharing = 0 if exclusive else 0x1 if directory else _SHARE_READ_WRITE
        value = _kernel.CreateFileW(_extended(path), access, sharing,
                                    None, _OPEN_ALWAYS if create else _OPEN_EXISTING,
                                    _OPEN_REPARSE | (_BACKUP if directory else 0), None)
        if value == _INVALID:
            raise OSError(ctypes.get_last_error(), "Cannot open an approved local object.")
        return value

    def _cloud(info):
        # Cloud tags have provider-specific bits in positions 12 through 15.
        return online_only(info) or bool(info.st_file_attributes & _REPARSE and getattr(info, "st_reparse_tag", 0) & 0xFFFF0FFF == 0x9000001A)

    def _valid_windows_path(raw):
        value = os.path.abspath(os.path.expanduser(str(raw)))
        if not re.match(r"^[A-Za-z]:\\", value) or str(raw).startswith(("\\\\", "\\?", "\\.")):
            raise DriveError("UNSUPPORTED_ROOT_LOCATION", "Use an ordinary folder on a fixed local Windows drive; network and device paths are unsupported.")
        path = Path(value)
        if _kernel.GetDriveTypeW(path.anchor) != 3:
            raise DriveError("UNSUPPORTED_ROOT_LOCATION", "Only fixed local Windows drives are supported.")
        for part in path.parts[1:]:
            _windows_component(part)
        return path

    class _WindowsDirectories:
        def __init__(self, path, create=False, code="UNSAFE_ROOT"):
            self.path = _valid_windows_path(path)
            self.handles = []
            self.identities = []
            self.code = code
            try:
                current = Path(self.path.anchor)
                for part in (None,) + self.path.parts[1:]:
                    if part is not None:
                        current = current / part
                        if create:
                            try:
                                current.mkdir(mode=0o700)
                            except FileExistsError:
                                pass
                    handle = _handle(current, directory=True)
                    self.handles.append(handle)
                    info = _file_info(handle)
                    if not stat.S_ISDIR(info.st_mode) or info.st_file_attributes & _REPARSE or _final_path(handle) != _canonical(current):
                        raise DriveError(code, "Directory links, junctions, reparse points, and redirected paths are forbidden.")
                    self.identities.append((current, info.st_dev, info.st_ino))
            except Exception as exc:
                self.close()
                if isinstance(exc, DriveError):
                    raise
                raise DriveError(code, "The directory is missing, inaccessible, or cannot be pinned safely.")

        def check(self):
            if not self.handles:
                raise DriveError(self.code, "The guarded directory is no longer open.")
            for handle, (path, device, inode) in zip(self.handles, self.identities):
                info = _file_info(handle)
                if (info.st_dev, info.st_ino) != (device, inode) or info.st_file_attributes & _REPARSE or _final_path(handle) != _canonical(path):
                    raise DriveError(self.code, "The guarded directory identity has changed.")

        def close(self):
            for handle in reversed(self.handles):
                _kernel.CloseHandle(handle)
            self.handles = []

    class WindowsSource:
        def __init__(self, root):
            self.guard = _WindowsDirectories(root)
            self.root = self.guard.path
            self.identity = self.guard.identities[-1][1:]

        def check_root(self):
            try:
                self.guard.check()
            except (DriveError, OSError):
                raise DriveError("SOURCE_ROOT_CHANGED", "The approved source directory identity changed.")

        def open_read(self, relative):
            self.check_root()
            parts = relative_parts(relative)
            path = self.root.joinpath(*parts)
            guard = _WindowsDirectories(path.parent, code="SOURCE_UNAVAILABLE")
            handle = None
            try:
                handle = _handle(path)
                info = _file_info(handle)
                if _final_path(handle) != _canonical(path) or _kernel.GetFileType(handle) != 1:
                    raise DriveError("UNSAFE_FILE", "The source is redirected or is not a local disk file.")
                if info.st_file_attributes & _REPARSE:
                    if _cloud(info):
                        raise DriveError("ONLINE_ONLY", "Cloud reparse files are not read; copy approved content into an ordinary local folder.")
                    raise DriveError("UNSAFE_FILE", "Source links and reparse points are not read.")
                if online_only(info):
                    raise DriveError("ONLINE_ONLY", "Online-only files are not hydrated automatically.")
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise DriveError("UNSAFE_FILE", "Only ordinary files with one hard link are supported.")
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                handle = None  # The C runtime now owns the handle.
                return fd, os.fstat(fd)
            except OSError:
                raise DriveError("SOURCE_UNAVAILABLE", "The source is missing, occupied, or inaccessible.", True, "Close applications with exclusive file locks and refresh.")
            finally:
                if handle is not None:
                    _kernel.CloseHandle(handle)
                guard.close()

        def walk(self, errors):
            self.check_root()
            def visit(folder, prefix):
                try:
                    guard = _WindowsDirectories(folder, code="SOURCE_UNAVAILABLE")
                except DriveError:
                    errors.append(True)
                    return
                try:
                    self.check_root()
                    with os.scandir(folder) as entries:
                        names = [entry.name for entry in entries]
                    for name in names:
                        try:
                            _windows_component(name)
                            path = folder / name
                            relative = (PurePosixPath(prefix) / name).as_posix()
                            info = os.stat(path, follow_symlinks=False)
                            attributes = getattr(info, "st_file_attributes", 0)
                            reparse = bool(attributes & _REPARSE)
                            online = online_only(info) or (reparse and getattr(info, "st_reparse_tag", 0) & 0xFFFF0FFF == 0x9000001A)
                            if stat.S_ISDIR(info.st_mode) and not reparse and not online:
                                yield from visit(path, relative)
                            else:
                                blocked = not online and (reparse or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                                yield relative, info, blocked, online
                        except (OSError, DriveError):
                            errors.append(True)
                except OSError:
                    errors.append(True)
                finally:
                    guard.close()
            yield from visit(self.root, "")

        def close(self):
            self.guard.close()


class StateAccess:
    """Guard state paths; never let source paths double as disposable storage."""
    def __init__(self, path, source, installation):
        self.fd = None
        self.lock_fd = None
        self.guard = None
        self.db_handle = None
        self.private_db_fd = None
        raw = Path(path).expanduser()
        if raw.is_symlink():
            raise DriveError("UNSAFE_STATE", "The state directory cannot be a symbolic link.")
        self.path = _valid_windows_path(raw) if os.name == "nt" else raw.resolve()
        if overlaps(self.path, source.root):
            raise DriveError("UNSAFE_STATE", "Source and state directories must not contain each other.")
        install = Path(installation).resolve()
        if contains_physical(source.root, install):
            raise DriveError("UNSAFE_ROOT", "The source directory cannot contain the installed application.")
        if contains_physical(self.path, install):
            raise DriveError("UNSAFE_STATE", "The state directory cannot contain the installed application.")
        if os.name == "nt":
            self.guard = _WindowsDirectories(self.path, create=True, code="UNSAFE_STATE")
            self.identity = self.guard.identities[-1][1:]
        else:
            self.fd = _make_posix_state(self.path, source.identity)
            info = os.fstat(self.fd)
            self.identity = (info.st_dev, info.st_ino)
        try:
            self.check()
        except Exception:
            self.close()
            raise

    def check(self):
        try:
            if self.guard:
                self.guard.check()
            else:
                info = os.stat(self.path, follow_symlinks=False)
                if self.fd is None or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self.identity:
                    raise OSError()
            for name in ("index.sqlite", "index.sqlite-wal", "index.sqlite-shm", "index.sqlite-journal", ".worker.lock"):
                path = self.path / name
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise DriveError("UNSAFE_STATE", "State files must be ordinary files with one hard link.")
        except OSError:
            raise DriveError("STATE_CHANGED", "The state directory is missing or has been rebound.")

    def lock(self):
        self.check()
        path = self.path / ".worker.lock"
        if os.name == "nt":
            try:
                handle = _handle(path, write=True, create=True, exclusive=True)
                info = _file_info(handle)
                if info.st_file_attributes & _REPARSE or info.st_nlink != 1:
                    _kernel.CloseHandle(handle)
                    raise DriveError("UNSAFE_STATE", "The state lock is redirected or multiply linked.")
                self.lock_fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
            except OSError:
                raise DriveError("STATE_IN_USE", "Another worker is using this state directory.", True, "Reuse the existing worker or use a separate state directory.")
        else:
            import fcntl
            self.lock_fd = os.open(".worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            try:
                info = os.fstat(self.lock_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise DriveError("UNSAFE_STATE", "The state lock is unsafe.")
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception:
                os.close(self.lock_fd)
                self.lock_fd = None
                raise DriveError("STATE_IN_USE", "Another worker is using this state directory.", True, "Reuse the existing worker or use a separate state directory.")

    @contextlib.contextmanager
    def directory(self, name, create=False):
        self.check()
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise DriveError("UNSAFE_STATE", "Invalid private state subdirectory.")
        path = self.path / name
        guard = None
        directory_fd = None
        try:
            if os.name == "nt":
                guard = _WindowsDirectories(path, create=create, code="UNSAFE_STATE")
            else:
                if create:
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=self.fd)
                    except FileExistsError:
                        pass
                directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                if path.resolve() != path:
                    raise DriveError("UNSAFE_STATE", "A private state subdirectory is redirected.")
            self.check()
            yield path
            self.check()
            if directory_fd is not None:
                before = os.fstat(directory_fd)
                after = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                if not stat.S_ISDIR(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise DriveError("UNSAFE_STATE", "A private state subdirectory changed during the operation.")
        except OSError:
            raise DriveError("UNSAFE_STATE", "A private state subdirectory is missing, redirected, or inaccessible.")
        finally:
            if guard:
                guard.close()
            if directory_fd is not None:
                os.close(directory_fd)

    def connect_database(self):
        """Open one verified database descriptor, then use an in-memory journal.

        No WAL/journal sidecars may be followed or created after approval. The
        index is disposable: an interrupted disk write may require a rebuild.
        """
        import sqlite3
        self.check()
        path = self.path / "index.sqlite"
        connection = None
        if os.name == "nt":
            handle = _handle(path, write=True, create=True)
            try:
                info = _file_info(handle)
                if info.st_file_attributes & (_REPARSE | _DIRECTORY) or info.st_nlink != 1 or _final_path(handle) != _canonical(path):
                    raise DriveError("UNSAFE_STATE", "The index database must be an ordinary private file.")
                self.db_handle = handle
                buffer = ctypes.create_string_buffer(20)
                read = wintypes.DWORD()
                if not _kernel.ReadFile(handle, buffer, 20, ctypes.byref(read), None):
                    raise DriveError("UNSAFE_STATE", "The pinned index header cannot be read safely.")
                header = buffer.raw[:read.value]
            except Exception:
                _kernel.CloseHandle(handle)
                self.db_handle = None
                raise
        else:
            self.private_db_fd = os.open("index.sqlite", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.fd)
            info = os.fstat(self.private_db_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise DriveError("UNSAFE_STATE", "The index database must be an ordinary private file.")
            header = os.pread(self.private_db_fd, 20, 0)
        if len(header) >= 20 and header[:16] == b"SQLite format 3\0" and (header[18] == 2 or header[19] == 2):
            raise DriveError("STATE_REBUILD_REQUIRED", "This older WAL index requires a new state directory for the safer storage format.")
        # Refuse recovery through old or externally supplied sidecar paths.
        if any((self.path / name).exists() for name in ("index.sqlite-wal", "index.sqlite-shm", "index.sqlite-journal")):
            raise DriveError("STATE_REBUILD_REQUIRED", "Existing SQLite sidecars require a new state directory.")
        try:
            with _DB_OPEN_LOCK:
                before_fds = _live_fds() if os.name == "posix" else set()
                connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=15, check_same_thread=False)
                if os.name == "posix":
                    import fcntl
                    verified = False
                    for value in _live_fds() - before_fds:
                        if not value.isdigit():
                            continue
                        try:
                            opened = os.fstat(int(value))
                            writable = fcntl.fcntl(int(value), fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
                        except OSError:
                            continue
                        if stat.S_ISREG(opened.st_mode) and writable:
                            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                                raise DriveError("UNSAFE_STATE", "SQLite opened a redirected database file.")
                            verified = True
                    if not verified:
                        raise DriveError("UNSAFE_STATE", "The opened SQLite descriptor could not be verified safely.")
            self.check()
            connection.execute("PRAGMA locking_mode=EXCLUSIVE")
            connection.execute("PRAGMA journal_mode=MEMORY")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA temp_store=MEMORY")
            return connection
        except Exception:
            if connection is not None:
                connection.close()
            raise

    @contextlib.contextmanager
    def new_private(self, path, binary=False):
        parent, name = self._private_location(path)
        parent_fd = None
        fd = None
        with self.directory(parent):
            try:
                if os.name == "nt":
                    # The directory is pinned against replacement and reparse changes.
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
                else:
                    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                with os.fdopen(fd, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as output:
                    fd = None
                    yield output
            finally:
                if fd is not None:
                    os.close(fd)
                if parent_fd is not None:
                    os.close(parent_fd)

    def _private_location(self, path):
        self.check()
        try:
            parts = Path(path).relative_to(self.path).parts
        except ValueError:
            raise DriveError("UNSAFE_STATE", "Private output must remain inside the state directory.")
        if len(parts) != 2 or any(part in (".", "..") for part in parts):
            raise DriveError("UNSAFE_STATE", "Unexpected private output location.")
        return parts

    @contextlib.contextmanager
    def open_private(self, path, mode):
        parent, name = self._private_location(path)
        if mode not in ("r", "w"):
            raise DriveError("UNSAFE_STATE", "Unsupported private file access mode.")
        fd = None
        parent_fd = None
        with self.directory(parent):
            try:
                if os.name == "nt":
                    handle = _handle(path, write=mode == "w")
                    info = _file_info(handle)
                    if info.st_file_attributes & (_REPARSE | _DIRECTORY) or info.st_nlink != 1 or _final_path(handle) != _canonical(path):
                        _kernel.CloseHandle(handle)
                        raise DriveError("UNSAFE_STATE", "A private parser file has been redirected.")
                    fd = msvcrt.open_osfhandle(handle, (os.O_RDWR if mode == "w" else os.O_RDONLY) | os.O_BINARY)
                else:
                    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                    fd = os.open(name, (os.O_RDWR if mode == "w" else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise DriveError("UNSAFE_STATE", "A private parser file has been redirected.")
                if mode == "w":
                    os.ftruncate(fd, 0)
                with os.fdopen(fd, mode, encoding="utf-8") as output:
                    fd = None
                    yield output
            finally:
                if fd is not None:
                    os.close(fd)
                if parent_fd is not None:
                    os.close(parent_fd)

    def unlink_private(self, path):
        parent, name = self._private_location(path)
        with self.directory(parent):
            if os.name == "nt":
                Path(path).unlink(missing_ok=True)
            else:
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                try:
                    try:
                        os.unlink(name, dir_fd=fd)
                    except FileNotFoundError:
                        pass
                finally:
                    os.close(fd)

    def remove_empty_directory(self, name):
        self.check()
        if not name.startswith("job-temp-") or "/" in name or "\\" in name:
            raise DriveError("UNSAFE_STATE", "Unexpected temporary directory name.")
        try:
            if os.name == "nt":
                os.rmdir(self.path / name)
            else:
                os.rmdir(name, dir_fd=self.fd)
        except OSError:
            # Never recurse into a directory with unexpected content.
            pass

    def close(self):
        if self.private_db_fd is not None:
            os.close(self.private_db_fd)
            self.private_db_fd = None
        if self.db_handle is not None:
            _kernel.CloseHandle(self.db_handle)
            self.db_handle = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
        if self.guard:
            self.guard.close()
            self.guard = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


SourceAccess = WindowsSource if os.name == "nt" else PosixSource


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-root", required=True)
    args = parser.parse_args()
    source = None
    try:
        source = SourceAccess(args.validate_root)
        source.check_root()
        print(json.dumps({"ok": True, "platform": sys.platform, "read_only_sources": True}))
    except DriveError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error": {"code": "UNSAFE_ROOT", "message": "The directory could not be validated safely."}}))
        return 1
    finally:
        if source:
            source.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
