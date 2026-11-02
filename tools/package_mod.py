"""Build a classic ZIP with explicit directories, then install via atomic rename.

Never launch BeamNG. Staging uses a non-.zip extension so a running game's file
watcher cannot mistake a partially copied file for an installable mod.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import zipfile
import datetime
from pathlib import Path


def running_game_processes():
    """Inspect processes without starting/stopping or automating any application."""
    if os.name != 'nt':
        return []
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
                    ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
                    ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
                    ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
                    ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    api = ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    api.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    api.Process32FirstW.restype=wintypes.BOOL
    api.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    api.Process32NextW.restype=wintypes.BOOL
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    api.CloseHandle.restype=wintypes.BOOL
    snapshot=api.CreateToolhelp32Snapshot(2,0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    matches=[]; observed=0
    try:
        entry=ProcessEntry(); entry.dwSize=ctypes.sizeof(entry)
        success=api.Process32FirstW(snapshot,ctypes.byref(entry))
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())
        while success:
            observed+=1
            exe=entry.szExeFile.lower()
            if exe in ('beamng.drive.x64.exe','beamng.drive.arm64.exe'):
                matches.append(dict(pid=entry.th32ProcessID,exe=entry.szExeFile))
            success=api.Process32NextW(snapshot,ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    if not observed:
        raise RuntimeError('Could not inspect running processes')
    return matches


def require_game_closed():
    running=running_game_processes()
    if running:
        raise RuntimeError('Close BeamNG before installing: a mounted ZIP may keep a stale file index. '+str(running))


def sha256(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def package_mod(level_root, archive):
    level_root, archive = Path(level_root), Path(archive)
    unpacked_root = level_root.parents[1]
    assert level_root.parent.name == 'levels', 'Unexpected map structure'
    mission_root=unpacked_root/'gameplay/missions'/level_root.name
    files = sorted([p for p in level_root.rglob('*') if p.is_file()]+
                   [p for p in mission_root.rglob('*') if p.is_file()])
    directories = {'levels/'}
    for p in files:
        relative = p.relative_to(unpacked_root)
        directories.update(parent.as_posix()+'/' for parent in relative.parents if parent.as_posix() != '.')
    staging = archive.with_suffix('.zip.building')
    with zipfile.ZipFile(staging, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=5, allowZip64=False) as z:
        for name in sorted(directories):
            entry = zipfile.ZipInfo(name, date_time=(2026,10,29,0,0,0))
            entry.create_system = 0
            entry.external_attr = 0x10  # DOS directory attribute
            entry.compress_type = zipfile.ZIP_STORED
            z.writestr(entry, b'')
        for p in files:
            # Preserve changed-file times so BeamNG can invalidate imported-shape
            # caches after an update at the same archive path.
            stamp=datetime.datetime.fromtimestamp(p.stat().st_mtime)
            entry = zipfile.ZipInfo(p.relative_to(unpacked_root).as_posix(), date_time=stamp.timetuple()[:6])
            entry.create_system = 0
            entry.external_attr = 0x20  # DOS archive attribute; no POSIX mode bits
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, p.read_bytes(), compresslevel=5)
    with zipfile.ZipFile(staging) as z:
        assert z.testzip() is None, 'ZIP failed CRC verification'
        assert len(z.infolist()) == len(files)+len(directories)
        assert len({i.filename.lower() for i in z.infolist()}) == len(z.infolist())
        assert all(i.extract_version <= 20 and i.flag_bits & 1 == 0 and not i.extra for i in z.infolist())
        for p in files:
            assert z.read(p.relative_to(unpacked_root).as_posix()) == p.read_bytes()
    os.replace(staging, archive)
    return dict(zip_bytes=archive.stat().st_size, zip_sha256=sha256(archive),
                zip_files=len(files), zip_directories=len(directories),
                packaging_revision=2, zip64=False, file_headers='DOS',
                compression='Deflate', crc_check='PASS')


def install_mod(archive, mod_directory, backup_directory):
    require_game_closed()
    archive, mod_directory = Path(archive).resolve(), Path(mod_directory).resolve()
    backup_directory = Path(backup_directory).resolve()
    if not mod_directory.is_dir():
        raise FileNotFoundError(mod_directory)
    destination = mod_directory/archive.name
    backup = None
    if destination.exists():
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup = backup_directory/(archive.stem+'_'+sha256(destination)[:16]+'.zip.bak')
        if not backup.exists():
            shutil.copyfile(destination, backup)
        assert sha256(backup) == sha256(destination), 'Backup mismatch'
    stage = destination.with_suffix('.zip.pending')
    if stage.exists():
        raise FileExistsError(f'Staging path already exists: {stage}')
    with archive.open('rb') as source, stage.open('xb') as target:
        shutil.copyfileobj(source, target, 1024*1024)
        target.flush()
        os.fsync(target.fileno())
    assert sha256(stage) == sha256(archive), 'Staged installation differs from source'
    with zipfile.ZipFile(stage) as z:
        assert z.testzip() is None, 'Staged installation CRC error'
    require_game_closed()
    # Source and destination are in the same directory: the .zip appears complete
    # in one operation, including when replacing a previous version.
    os.replace(stage, destination)
    assert sha256(destination) == sha256(archive), 'Installed archive differs from source'
    return dict(installed_path=str(destination), installed_sha256=sha256(destination),
                previous_archive_backup=str(backup) if backup else None,
                installation='game_closed_complete_file_atomic_replace',
                game_closed_at_install=True, game_launched=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--install-to', type=Path)
    args = parser.parse_args()
    base = args.source.resolve()/'_beamng_conversion'
    archive = base/'output/st_stctk_ac_port.zip'
    summary = package_mod(base/'output/unpacked/levels/st_stctk_ac_port', archive)
    if args.install_to:
        summary.update(install_mod(archive, args.install_to, base/'work/backups'))
    (base/'output/packaging_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (base/'output/SHA256.txt').write_text(summary['zip_sha256']+'  '+archive.name+'\n',encoding='ascii')
    report_path = base/'work/conversion_report.json'
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report.update({k:v for k,v in summary.items() if k.startswith('zip_') or k=='packaging_revision'})
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copyfile(report_path, base/'output/conversion_report.json')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
