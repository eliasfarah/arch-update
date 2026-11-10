#!/usr/bin/python3
"""Safely check repository and AUR updates without changing pacman's real sync DB."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


UPDATE_LINE = re.compile(r"^(\S+)\s+(\S+)\s+->\s+(\S+)(?:\s+\[[^\]]+\])?$")
KNOWN_REPOSITORIES = {"core": 0, "extra": 1, "multilib": 2}


def run(command, env, timeout=300):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)


def parse_updates(output, group, source):
    updates = []
    for line in output.splitlines():
        match = UPDATE_LINE.match(line.strip())
        if match:
            name, old_version, new_version = match.groups()
            updates.append({
                "name": name,
                "oldVersion": old_version,
                "newVersion": new_version,
                "group": group,
                "source": source,
            })
    return updates


def pacman_db_path(pacman_conf):
    result = subprocess.run([pacman_conf, "DBPath"], capture_output=True, text=True, timeout=15)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError((result.stderr or "Não consegui localizar a base local do pacman.").strip())
    return Path(result.stdout.strip()).resolve()


def check_updates(force=False):
    pacman = shutil.which("pacman")
    pacman_conf = shutil.which("pacman-conf")
    yay = shutil.which("yay")
    fakeroot = shutil.which("fakeroot")
    if not pacman or not pacman_conf or not yay:
        raise RuntimeError("Preciso encontrar pacman, pacman-conf e yay para consultar atualizações.")
    if os.geteuid() != 0 and not fakeroot:
        raise RuntimeError("O fakeroot é necessário para consultar atualizações com segurança.")

    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "arch-update-center"
    cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(cache_root, 0o700)
    database_path = cache_root / "checkupdates-db"
    database_path.mkdir(mode=0o700, exist_ok=True)
    system_database = pacman_db_path(pacman_conf)
    system_local = system_database / "local"
    if not system_local.is_dir():
        raise RuntimeError("A base local do pacman não está disponível.")

    local_link = database_path / "local"
    if local_link.is_symlink():
        if local_link.resolve() != system_local.resolve():
            local_link.unlink()
            local_link.symlink_to(system_local, target_is_directory=True)
    elif local_link.exists():
        raise RuntimeError("A base temporária de consulta contém uma pasta local inesperada.")
    else:
        local_link.symlink_to(system_local, target_is_directory=True)

    env = os.environ.copy()
    env.update({"LC_ALL": "C", "NO_COLOR": "1", "TERM": "dumb", "PAGER": "cat"})
    lock_path = cache_root / "checkupdates.lock"
    with lock_path.open("a", encoding="utf-8") as checker_lock:
        fcntl.flock(checker_lock.fileno(), fcntl.LOCK_EX)
        system_lock = system_database / "db.lck"
        if system_lock.exists():
            raise RuntimeError("O pacman já está atualizando o sistema. Tente consultar novamente ao terminar.")

        # Keep the temporary sync database separate from /var/lib/pacman so
        # previewing updates cannot leave the system in a partial-upgrade state.
        stale_lock = database_path / "db.lck"
        if stale_lock.exists():
            stale_lock.unlink()
        sync_flag = "-Syy" if force else "-Sy"
        sync_command = [pacman, sync_flag, "--dbpath", str(database_path), "--logfile", "/dev/null", "--noconfirm"]
        if os.geteuid() != 0:
            sync_command = [fakeroot, *sync_command]
        synced = run(sync_command, env)
        if synced.returncode != 0:
            detail = (synced.stderr or synced.stdout).strip()
            raise RuntimeError(detail or "Não consegui sincronizar uma base temporária de pacotes.")
        if system_lock.exists():
            raise RuntimeError("Uma atualização do pacman começou durante a consulta. Tente novamente ao terminar.")

        repo_result = run([pacman, "-Qu", "--dbpath", str(database_path)], env, timeout=90)
        if repo_result.returncode not in (0, 1):
            detail = (repo_result.stderr or repo_result.stdout).strip()
            raise RuntimeError(detail or "Não consegui listar atualizações dos repositórios.")

        sync_result = run([pacman, "-Sl", "--dbpath", str(database_path)], env, timeout=120)
        if sync_result.returncode != 0:
            detail = (sync_result.stderr or sync_result.stdout).strip()
            raise RuntimeError(detail or "Não consegui identificar os repositórios dos pacotes.")

        repository_by_package = {}
        for line in sync_result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                repository, package_name = parts[0], parts[1]
                previous = repository_by_package.get(package_name)
                if previous is None or KNOWN_REPOSITORIES.get(repository, 99) < KNOWN_REPOSITORIES.get(previous, 99):
                    repository_by_package[package_name] = repository

        updates = []
        for line in repo_result.stdout.splitlines():
            match = UPDATE_LINE.match(line.strip())
            if not match:
                continue
            name, old_version, new_version = match.groups()
            repository = repository_by_package.get(name, "other")
            group = repository if repository in KNOWN_REPOSITORIES else "other"
            updates.append({
                "name": name,
                "oldVersion": old_version,
                "newVersion": new_version,
                "group": group,
                "source": repository.capitalize() if group != "other" else repository,
            })

        aur_result = run([yay, "-Qua"], env, timeout=180)
        if aur_result.returncode not in (0, 1) or aur_result.stderr.strip():
            detail = (aur_result.stderr or aur_result.stdout).strip()
            raise RuntimeError(detail or "Não consegui consultar atualizações do AUR.")
        updates.extend(parse_updates(aur_result.stdout, "aur", "AUR"))

    group_order = {"core": 0, "extra": 1, "multilib": 2, "aur": 3, "other": 4}
    updates.sort(key=lambda item: (group_order[item["group"]], item["name"].casefold()))
    return updates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="force refresh the temporary repository databases")
    args = parser.parse_args()
    try:
        updates = check_updates(force=args.force)
        print(json.dumps({"updates": updates}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"updates": [], "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
