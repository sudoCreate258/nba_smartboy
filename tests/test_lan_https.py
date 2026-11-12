"""M6-T5: LAN HTTPS. The owner's certificate script makes a CA and a server certificate; gunicorn serves
the app over TLS with them; pages, the service worker and the manifest load with HSTS (R5).

Runs the real script (openssl) into a temporary folder and a real gunicorn process, so it works the
same locally and in CI. The CA here is a throwaway made by the test, never the owner's.
"""
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from django.db import connection

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    out = tmp_path_factory.mktemp("certs")
    result = subprocess.run(["sh", str(ROOT / "scripts" / "lan-cert.sh"), "127.0.0.1", str(out)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "created a new local CA" in result.stdout
    return out


def test_certificate_script_output(certs):
    text = subprocess.run(["openssl", "x509", "-in", str(certs / "server" / "server.crt"), "-noout", "-text"],
                          capture_output=True, text=True, check=True).stdout
    assert "IP Address:127.0.0.1" in text and "TLS Web Server Authentication" in text and "CA:FALSE" in text
    verify = subprocess.run(["openssl", "verify", "-CAfile", str(certs / "ca" / "twin-ca.crt"),
                             str(certs / "server" / "server.crt")], capture_output=True, text=True)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    # Re-running keeps the CA (the phone keeps trusting it) and renews only the server certificate.
    ca_before = (certs / "ca" / "twin-ca.crt").read_bytes()
    again = subprocess.run(["sh", str(ROOT / "scripts" / "lan-cert.sh"), "192.168.1.20", str(certs)],
                           capture_output=True, text=True, timeout=120)
    assert "reusing the existing local CA" in again.stdout
    assert (certs / "ca" / "twin-ca.crt").read_bytes() == ca_before
    subprocess.run(["sh", str(ROOT / "scripts" / "lan-cert.sh"), "127.0.0.1", str(certs)], check=True,
                   capture_output=True, timeout=120)


@pytest.fixture
def tls_server(certs, db):
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TWIN_")}
    env.update({"TWIN_HTTPS": "1", "TWIN_HTTPS_HOST": "127.0.0.1", "TWIN_HTTPS_PORT": str(port), "DJANGO_DEBUG": "0",
                "DJANGO_SECRET_KEY": "test-only-" + "x" * 50, "POSTGRES_DB": connection.settings_dict["NAME"]})
    proc = subprocess.Popen([sys.executable, "-m", "gunicorn", "twin.wsgi:application", "--bind", f"127.0.0.1:{port}",
                             "--workers", "1", "--certfile", str(certs / "server" / "server.crt"),
                             "--keyfile", str(certs / "server" / "server.key")],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    context = ssl.create_default_context(cafile=str(certs / "ca" / "twin-ca.crt"))
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    yield f"https://127.0.0.1:{port}", context
    proc.terminate()
    proc.wait(10)


def _get(base, context, path):
    with urllib.request.urlopen(base + path, context=context, timeout=10) as resp:
        return resp.status, dict(resp.headers), resp.read()


def test_pages_service_worker_and_manifest_over_tls(tls_server):
    base, context = tls_server
    status, headers, body = _get(base, context, "/login/")
    assert status == 200 and b"Log in" in body
    assert headers["Strict-Transport-Security"].startswith("max-age=31536000")
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Secure" in headers.get("Set-Cookie", "")  # the CSRF cookie is secure-only
    status, headers, body = _get(base, context, "/sw.js")
    assert status == 200 and headers["Content-Type"].startswith("application/javascript")
    assert headers["Service-Worker-Allowed"] == "/"
    status, headers, body = _get(base, context, "/manifest.webmanifest")
    assert status == 200 and b'"display": "standalone"' in body
    status, _, _ = _get(base, context, "/static/ui/offline.js")
    assert status == 200


def test_an_untrusted_client_is_refused(tls_server):
    base, _ = tls_server
    with pytest.raises(urllib.error.URLError, match="CERTIFICATE_VERIFY_FAILED"):
        urllib.request.urlopen(base + "/login/", context=ssl.create_default_context(), timeout=10)


def test_keys_never_reach_git_or_the_image():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "certs/" in gitignore and "*.key" in gitignore
    assert "certs" in dockerignore.split() and "*.key" in dockerignore.split()
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./certs/server:/run/secrets/tls:ro" in compose and 'TWIN_HTTPS: "1"' in compose
