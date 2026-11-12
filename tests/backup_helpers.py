"""Test helpers: a local rclone remote wrapped in crypt, built at run time (no network, nothing committed)."""
import secrets
import subprocess


def obscure(value):
    return subprocess.run(["rclone", "obscure", value], capture_output=True, text=True, check=True).stdout.strip()


def crypt_remote(tmp_path):
    """(config path, remote name, folder holding the encrypted bytes). Password and salt are random per test."""
    store = tmp_path / "remote-bytes"
    store.mkdir()
    lines = [
        "[store]", "type = local", "",
        "[vault]", "type = " + "crypt", f"remote = store:{store}",
        "password = " + obscure(secrets.token_hex(24)), "password2 = " + obscure(secrets.token_hex(24)), "",
    ]
    config = tmp_path / "test-rclone.conf"
    config.write_text("\n".join(lines), encoding="utf-8")
    return config, "vault:", store
