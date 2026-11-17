import gzip
import hashlib
import os
import pwd
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

from infra.common import run, sha256, write

RELEASE = "https://github.com/masesmirnov/Claude-Cage/releases/download/v0.1.8-en.4/"
KIT = "cloud-linux-amd64.tar"
FILES = {
    KIT: "c96fa1f5e69fc03e692b325bf57f394b3020deeeae65e57e70e3070f579caf18",
    "lifecycle.sh": "5f65633b443f5fdfc455e1d06333ed953a47e5f319a389de4ec81180c4f2a13a",
}
USER = "cage"
HOME = Path("/home/cage")
CONFIG = HOME / ".claude-cage/config.json"
HOST = CONFIG.parent / "cloud-host"
UNIT = "cage-cloud-" + hashlib.sha256(str(CONFIG).encode()).hexdigest()[:16] + ".service"
CACHE = Path("/var/cache/infra/cage-cloud")
SUBORDINATE = "231072-296607"
APPARMOR = Path("/etc/apparmor.d/cage-rootlesskit")
GUEST = ["deploy/cloud/Dockerfile.guest", "deploy/cloud/restore-apt-sources.sh", "internal/cage/apt-bootstrap.sh"]


def account():
    try:
        return pwd.getpwnam(USER)
    except KeyError:
        run(["useradd", "--create-home", "--home-dir", HOME, "--shell", "/usr/sbin/nologin", USER], capture=True)
        return pwd.getpwnam(USER)


def environment(user):
    runtime = "/run/user/" + str(user.pw_uid)
    return ["env", "-i", "HOME=" + str(HOME), "USER=" + USER, "LOGNAME=" + USER, "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "XDG_RUNTIME_DIR=" + runtime, "DBUS_SESSION_BUS_ADDRESS=unix:path=" + runtime + "/bus"]


def systemctl(user, *args):
    run(["runuser", "-u", USER, "--", *environment(user), "systemctl", "--user", *args], capture=True, cwd=HOME)


def download(name, expected):
    target = CACHE / name
    if not target.exists() or sha256(target) != expected:
        CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
        partial = target.with_name(name + ".part")
        with urllib.request.urlopen(RELEASE + name, timeout=300) as response, partial.open("wb") as stream:
            while chunk := response.read(1 << 20):
                stream.write(chunk)
        if sha256(partial) != expected:
            partial.unlink()
            raise ValueError("cage-cloud: SHA-256 " + name + " не совпадает с закреплённым")
        partial.replace(target)
    return target


def script(user, binary, kind):
    return run(["runuser", "-u", USER, "--", *environment(user), "CLAUDE_CAGE_CONFIG=" + str(HOST / "probe/config.json"), binary, "container-install-script", kind],
               capture=True, cwd=HOME).stdout


def update(user, kit):
    with tarfile.open(kit) as archive:
        files = {member.name.removeprefix("./"): archive.extractfile(member).read() for member in archive if member.isfile()}
    contexts = list((HOST / "build").glob("build.*/context"))
    changed = not contexts or any((context / Path(name).name).read_bytes() != files[name] for context in contexts for name in GUEST)
    engine = UNIT.removesuffix(".service") + "-engine"
    for target, source in ((UNIT, "cage-server.service"), (engine + ".service", "cage-container-engine.service")):
        text = files[source].decode()
        for old, new in (("%h/.claude-cage/container-engine", str(HOST / "engine")), ("%h/.claude-cage/config.json", str(CONFIG)),
                         ("%h/.local/lib/cage", str(HOST / "bin")), ("cage-container-engine", engine)):
            text = text.replace(old, new)
        changed |= text != (HOME / ".config/systemd/user" / target).read_text()
    probe = HOST / "bin/cage.new"
    write(probe, gzip.decompress(files["cage.gz"]), 0o700)
    os.chown(probe, user.pw_uid, user.pw_gid)
    for kind in ["tools", "services"]:
        changed |= script(user, HOST / "bin/cage", kind) != script(user, probe, kind)
    if changed:
        probe.unlink()
        raise ValueError("cage-cloud: новый релиз меняет образ гостя или юниты служб, обновление этим компонентом не поддерживается")
    systemctl(user, "stop", UNIT)
    probe.replace(HOST / "bin/cage")
    for path, data, mode in ((HOST / "bin/mihomo", gzip.decompress(files["mihomo.gz"]), 0o700), (HOST / "kit-id", FILES[KIT], 0o600)):
        write(path, data, mode)
        os.chown(path, user.pw_uid, user.pw_gid)


def configure():
    user = account()
    for path in ["/etc/subuid", "/etc/subgid"]:
        if not any(line.startswith(USER + ":") for line in Path(path).read_text().splitlines()):
            run(["usermod", "--add-subuids" if path.endswith("uid") else "--add-subgids", SUBORDINATE, USER], capture=True)
    profile = (
        "abi <abi/5.0>,\ninclude <tunables/global>\n\n"
        "profile cage-rootlesskit " + str(HOST / "engine/tools/rootlesskit") + " flags=(unconfined) {\n  userns,\n}\n"
    )
    if write(APPARMOR, profile, 0o644):
        run(["apparmor_parser", "-r", APPARMOR], capture=True)
    run(["loginctl", "enable-linger", USER], capture=True)
    bus = Path("/run/user/" + str(user.pw_uid) + "/bus")
    for _ in range(60):
        if bus.exists():
            break
        time.sleep(1)
    else:
        raise ValueError("cage-cloud: systemd user session для cage не запустилась")
    kit, lifecycle = (download(name, expected) for name, expected in FILES.items())
    marker = HOST / "kit-id"
    if (HOST / "ready").exists():
        if marker.read_text() != FILES[KIT]:
            update(user, kit)
        systemctl(user, "start", UNIT)
        print("cage-cloud: Cage " + FILES[KIT][:12] + " уже установлен", flush=True)
        return
    with kit.open("rb") as payload:
        command = ["runuser", "-u", USER, "--", *environment(user), "bash", "-c", lifecycle.read_text(), "cage-cloud", "install", "cage", str(CONFIG), FILES[KIT]]
        result = subprocess.run(command, stdin=payload, cwd=HOME)
    if result.returncode:
        raise ValueError("cage-cloud: установка Cage завершилась с кодом " + str(result.returncode) + ", журнал в " + str(HOST))
    print("cage-cloud: Cage " + FILES[KIT][:12] + " установлен", flush=True)
