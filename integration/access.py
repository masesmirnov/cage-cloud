import os
from pathlib import Path

from infra.common import service_catalog, sha256, write, write_json

from .deploy import HOME, HOST, UNIT, account, systemctl

MARKER = Path("/etc/infra/claude-access-owned.json")
TOKEN = Path("/etc/infra/claude-access/token")
DROPIN = HOME / ".config/systemd/user" / (UNIT + ".d") / "infra-proxy.conf"


def configure(secret, owner, enabled=True):
    if not (HOST / "ready").exists():
        raise ValueError("cage-cloud: Cage ещё не установлен, единый вход включится после deploy")
    user = account()
    changed = False
    if enabled:
        TOKEN.parent.mkdir(mode=0o750, exist_ok=True)
        os.chown(TOKEN.parent, 0, user.pw_gid)
        changed |= write(TOKEN, secret["oidc_bridges"]["claude"] + "\n", 0o640)
        os.chown(TOKEN, 0, user.pw_gid)
        origin = "https://" + service_catalog()["claude"]["domain"]
        changed |= write(DROPIN, "[Service]\nEnvironment=CAGE_PUBLIC_ORIGIN=" + origin + "\nEnvironment=CAGE_PROXY_TOKEN_FILE=" + str(TOKEN) + "\n", 0o644)
        for path in [DROPIN.parent.parent.parent, DROPIN.parent.parent, DROPIN.parent, DROPIN]:
            os.chown(path, user.pw_uid, user.pw_gid)
    else:
        for path in [DROPIN, TOKEN]:
            if path.exists():
                path.unlink()
                changed = True
    write_json(MARKER, {"files": {str(path): sha256(path) for path in [DROPIN, TOKEN] if path.exists()}})
    if changed:
        systemctl(user, "daemon-reload")
        systemctl(user, "restart", UNIT)
