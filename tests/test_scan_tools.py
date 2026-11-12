"""M6-T3: the vulnerability gate's own logic (tools/scan_report.py, tools/image_packages.py) (R3)."""
import io
import json
import tarfile
from pathlib import Path

import pytest

from tools import image_packages, scan_report as sr

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("vector,score", [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", 5.5),
    ("CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N", 3.1),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
    ("CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N", 6.4),
])
def test_cvss3_base_scores(vector, score):
    assert sr.cvss3_score(vector) == score


def test_ratings_and_unreadable_vectors():
    assert [sr.rating(s) for s in (0.0, 3.9, 4.0, 6.9, 7.0, 8.9, 9.0, None)] == [
        "NONE", "LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH", "CRITICAL", "UNKNOWN"]
    assert sr.cvss3_score("CVSS:3.1/AV:N") is None


@pytest.mark.parametrize("a,b,sign", [
    ("1.0", "1.0", 0), ("1.0", "1.1", -1), ("1:1.0", "2.0", 1), ("1.0~rc1", "1.0", -1),
    ("1:1.3.dfsg+really1.3.1-1", "1:1.3.dfsg+really1.3.1-1+deb13u1", -1), ("2.36-9+deb12u10", "2.36-9+deb12u9", 1),
    ("1.0a", "1.0", 1), ("1.0-1", "1.0-1", 0), ("10", "9", 1), ("1.02", "1.2", 0),
])
def test_dpkg_version_order(a, b, sign):
    result = sr.dpkg_compare(a, b)
    assert (result > 0) - (result < 0) == sign


def deb_vuln(vid, release_entries, cvss=None):
    v = {"id": vid, "aliases": [], "affected": release_entries}
    if cvss:
        v["severity"] = [{"type": "CVSS_V3", "score": cvss}]
    return v


def entry(release, fixed=None, urgency="not yet assigned"):
    events = [{"introduced": "0"}] + ([{"fixed": fixed}] if fixed else [])
    return {"package": {"ecosystem": f"Debian:{release}", "name": "zlib"}, "ranges": [{"type": "ECOSYSTEM", "events": events}],
            "ecosystem_specific": {"urgency": urgency}}


HIGH = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"  # 7.5


def results(package, *vulns):
    return {"results": [{"packages": [{"package": package, "vulnerabilities": list(vulns)}]}]}


ZLIB = {"name": "zlib", "version": "1:1.3-1", "ecosystem": "Debian"}


def test_debian_advisories_use_only_the_image_release():
    other_release = deb_vuln("DEBIAN-CVE-1", [entry(12, fixed="1:1.3-2")], HIGH)
    fixed_here = deb_vuln("DEBIAN-CVE-2", [entry(12), entry(13, fixed="1:1.3-2")], HIGH)
    unfixed = deb_vuln("DEBIAN-CVE-3", [entry(13)], HIGH)
    already = deb_vuln("DEBIAN-CVE-4", [entry(13, fixed="1:1.2-1")], HIGH)
    rows = sr.evaluate([results(ZLIB, other_release, fixed_here, unfixed, already)], "13", set())
    assert {(r["id"], r["status"], r["severity"]) for r in rows} == {
        ("DEBIAN-CVE-2", "affected", "HIGH"), ("DEBIAN-CVE-3", "unfixed", "HIGH")}
    assert [r["id"] for r in sr.failing(rows)] == ["DEBIAN-CVE-2"]


def test_severity_sources_in_order():
    gh = {"id": "GHSA-x", "database_specific": {"severity": "MODERATE"}, "severity": [{"type": "CVSS_V3", "score": HIGH}]}
    assert sr.severity(gh) == "MEDIUM"  # GitHub's reviewed rating wins
    assert sr.severity({"id": "X", "severity": [{"type": "CVSS_V3", "score": HIGH}]}) == "HIGH"
    assert sr.severity({"id": "X"}, {"ecosystem_specific": {"urgency": "high"}}) == "HIGH"
    assert sr.severity({"id": "X", "severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N"}]}) == "UNKNOWN"


def test_pypi_needs_a_fix_to_fail_and_ignore_file_applies(tmp_path):
    pkg = {"name": "django", "version": "5.2.0", "ecosystem": "PyPI"}
    fixable = {"id": "GHSA-a", "aliases": ["CVE-2026-1"], "database_specific": {"severity": "HIGH"},
               "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "5.2.1"}]}]}]}
    no_fix = {"id": "GHSA-b", "aliases": [], "database_specific": {"severity": "CRITICAL"},
              "affected": [{"ranges": [{"events": [{"introduced": "0"}]}]}]}
    rows = sr.evaluate([results(pkg, fixable, no_fix)], "13", set())
    assert [r["id"] for r in sr.failing(rows)] == ["GHSA-a"]
    ignore = tmp_path / "ignore.txt"
    ignore.write_text("# reviewed\nCVE-2026-1  # does not apply: reason, reviewer, date\n", encoding="utf-8")
    assert sr.failing(sr.evaluate([results(pkg, fixable)], "13", sr.read_ignore(ignore))) == []


def test_aliases_are_reported_once():
    pkg = {"name": "pip", "version": "25.0", "ecosystem": "PyPI"}
    a = {"id": "GHSA-a", "aliases": ["CVE-1", "PYSEC-1"], "database_specific": {"severity": "HIGH"},
         "affected": [{"ranges": [{"events": [{"fixed": "25.3"}]}]}]}
    b = {"id": "PYSEC-1", "aliases": ["CVE-1", "GHSA-a"], "affected": [{"ranges": [{"events": [{"fixed": "25.3"}]}]}]}
    assert len(sr.evaluate([results(pkg, a, b)], "13", set())) == 1


def test_main_exit_codes(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(results(ZLIB, deb_vuln("DEBIAN-CVE-2", [entry(13, fixed="1:1.3-2")], HIGH))))
    assert sr.main(["--debian-release", "13", str(bad)]) == 1
    assert "FAIL HIGH: zlib" in capsys.readouterr().out
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"results": []}))
    assert sr.main([str(good)]) == 0


def _layer(files, whiteouts=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name in whiteouts:
            tar.addfile(tarfile.TarInfo(name), io.BytesIO(b""))
    return buf.getvalue()


def test_image_packages_reads_layers_in_order_with_whiteouts(tmp_path):
    site = "usr/local/lib/python3.12/site-packages"
    layers = [
        _layer({"etc/os-release": b'VERSION_ID="13"\n', "var/lib/dpkg/status": b"Package: old\n",
                f"{site}/gone-1.0.dist-info/METADATA": b"Name: gone\nVersion: 1.0\n"}),
        _layer({"var/lib/dpkg/status": b"Package: zlib1g\nVersion: 1\n\nPackage: libc6\n",
                f"{site}/Django-5.2.19.dist-info/METADATA": b"Name: Django\nVersion: 5.2.19\n"},
               whiteouts=[f"{site}/.wh.gone-1.0.dist-info"]),
    ]
    image = tmp_path / "img.tar"
    with tarfile.open(image, "w") as outer:
        for i, data in enumerate(layers):
            info = tarfile.TarInfo(f"{i}/layer.tar")
            info.size = len(data)
            outer.addfile(info, io.BytesIO(data))
        manifest = json.dumps([{"Layers": ["0/layer.tar", "1/layer.tar"]}]).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        outer.addfile(info, io.BytesIO(manifest))
    out = tmp_path / "out"
    out.mkdir()
    assert image_packages.main(["x", str(image), str(out)]) == 0
    assert (out / "dpkg-status").read_text().count("Package: ") == 2
    assert (out / "python-packages.txt").read_text() == "Django==5.2.19\n"
    assert (out / "debian-release").read_text() == "13\n"


def test_scan_uses_only_alpine_stable_and_no_docker_socket():
    texts = {p: (ROOT / p).read_text(encoding="utf-8") for p in
             ("scripts/scan.sh", "scripts/scan.ps1", ".github/workflows/ci.yml")}
    for path, text in texts.items():
        assert "docker.sock" not in text, path
        assert "edge" not in text and "testing" not in text.replace("tests", ""), path
    assert "alpine:3.20" in texts["scripts/scan.ps1"] and "apk add --no-cache osv-scanner" in texts["scripts/scan.sh"]
    assert "/in/web.tar:ro" in texts["scripts/scan.ps1"] and ":/repo:ro" in texts["scripts/scan.ps1"]
    assert (ROOT / "scan-ignore.txt").is_file()
