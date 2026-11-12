# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write an rclone config with a local crypt remote named twin-crypt (random password and salt).

For trying the backup and restore commands without any cloud account:
    python scripts/make-test-remote.py /e2e
creates /e2e/rclone.conf and /e2e/bytes (where the encrypted bytes land). The password stays in
that config only; nothing is printed or committed.
"""
import secrets
import subprocess
import sys
from pathlib import Path

folder = Path(sys.argv[1])
(folder / "bytes").mkdir(parents=True, exist_ok=True)


def obscure(value):
    return subprocess.run(["rclone", "obscure", value], capture_output=True, text=True, check=True).stdout.strip()


(folder / "rclone.conf").write_text(
    "[store]\ntype = local\n\n[twin-crypt]\ntype = crypt\n"
    f"remote = store:{folder / 'bytes'}\npassword = {obscure(secrets.token_hex(16))}\n"
    f"password2 = {obscure(secrets.token_hex(16))}\n", encoding="utf-8")
print(f"Wrote {folder / 'rclone.conf'}")
