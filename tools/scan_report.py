# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vulnerability gate over osv-scanner JSON (M6 R3). Python standard library only.

osv-scanner 1.6 (Alpine 3.20) reports every advisory that mentions a package, without a severity
filter and without checking the Debian release. This script decides what fails the gate:

- Debian packages: only the advisory's entry for the image's release (Debian:<N>) counts. No entry
  = not affected; no fixed version = unfixed (reported, never fails, like `--ignore-unfixed`);
  installed version >= fixed version = already fixed (dpkg version order).
- PyPI packages: osv already matched the installed version; a fix must exist to fail.
- Severity: GitHub's reviewed severity, else the CVSS v3 base score, else Debian's urgency, else
  UNKNOWN (reported, not failing).
- Fails (exit 1) on HIGH or CRITICAL that has a fix and is not in the reviewed ignore file.

Usage: python3 scan_report.py --debian-release 13 --ignore scan-ignore.txt result.json [...]
"""
import argparse
import json
import math
import re
import sys

FAIL = {"HIGH", "CRITICAL"}
GITHUB = {"LOW": "LOW", "MODERATE": "MEDIUM", "MEDIUM": "MEDIUM", "HIGH": "HIGH", "CRITICAL": "CRITICAL"}
URGENCY = {"unimportant": "LOW", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}

# --- CVSS v3.x base score --------------------------------------------------------------------

_W = {"AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}, "AC": {"L": 0.77, "H": 0.44},
      "UI": {"N": 0.85, "R": 0.62}, "CIA": {"H": 0.56, "L": 0.22, "N": 0.0}}


def _roundup(x):
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss3_score(vector):
    """Base score of a CVSS:3.0/3.1 vector string, or None if it cannot be read."""
    try:
        m = dict(part.split(":", 1) for part in vector.split("/")[1:])
        changed = m["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[m["PR"]]
        iss = 1 - (1 - _W["CIA"][m["C"]]) * (1 - _W["CIA"][m["I"]]) * (1 - _W["CIA"][m["A"]])
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
        exploit = 8.22 * _W["AV"][m["AV"]] * _W["AC"][m["AC"]] * pr * _W["UI"][m["UI"]]
    except (KeyError, ValueError):
        return None
    if impact <= 0:
        return 0.0
    return _roundup(min((1.08 if changed else 1) * (impact + exploit), 10))


def rating(score):
    if score is None:
        return "UNKNOWN"
    return "NONE" if score == 0 else "LOW" if score < 4 else "MEDIUM" if score < 7 else "HIGH" if score < 9 else "CRITICAL"


# --- dpkg version order ----------------------------------------------------------------------

def _order(c):
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    return ord(c) + 256


def _verrevcmp(a, b):
    i = j = 0
    while i < len(a) or j < len(b):
        diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _order(a[i]) if i < len(a) and not a[i].isdigit() else 0
            bc = _order(b[j]) if j < len(b) and not b[j].isdigit() else 0
            if ac != bc:
                return ac - bc
            i, j = i + 1, j + 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not diff:
                diff = ord(a[i]) - ord(b[j])
            i, j = i + 1, j + 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if diff:
            return diff
    return 0


def _split(v):
    epoch, _, rest = v.rpartition(":") if ":" in v else ("0", "", v)
    upstream, _, revision = rest.rpartition("-") if "-" in rest else (rest, "", "0")
    return int(epoch or 0), upstream, revision


def dpkg_compare(a, b):
    """<0, 0, >0 like `dpkg --compare-versions`."""
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return ea - eb
    return _verrevcmp(ua, ub) or _verrevcmp(ra, rb)


# --- the gate --------------------------------------------------------------------------------

def severity(vuln, entry=None):
    gh = (vuln.get("database_specific") or {}).get("severity")
    if isinstance(gh, str) and gh.upper() in GITHUB:
        return GITHUB[gh.upper()]
    for s in vuln.get("severity", []):
        if s.get("type") == "CVSS_V3":
            return rating(cvss3_score(s.get("score", "")))
    urgency = ((entry or {}).get("ecosystem_specific") or {}).get("urgency", "")
    return URGENCY.get(urgency.split()[0] if urgency else "", "UNKNOWN")


def _fixed(entry):
    return [e["fixed"] for r in entry.get("ranges", []) for e in r.get("events", []) if "fixed" in e]


def assess(package, vuln, debian_release):
    """(status, severity, fixed_version): status is affected, unfixed or not_affected."""
    if package["ecosystem"].startswith("Debian"):
        entries = [a for a in vuln.get("affected", []) if a.get("package", {}).get("ecosystem") == f"Debian:{debian_release}"]
        if not entries:
            return "not_affected", None, None
        entry = entries[0]
        fixed = _fixed(entry)
        if not fixed:
            return "unfixed", severity(vuln, entry), None
        if dpkg_compare(package["version"], fixed[0]) >= 0:
            return "not_affected", None, fixed[0]
        return "affected", severity(vuln, entry), fixed[0]
    fixed = [f for a in vuln.get("affected", []) for f in _fixed(a)]
    return ("affected" if fixed else "unfixed"), severity(vuln), (fixed[0] if fixed else None)


def read_ignore(path):
    """IDs (any alias) from the reviewed ignore file: one per line, '#' comments."""
    ids = set()
    if path:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                token = line.split("#", 1)[0].strip()
                if token:
                    ids.add(token)
    return ids


def evaluate(results, debian_release, ignored):
    """Rows {id, aliases, package, version, ecosystem, status, severity, fixed, ignored}, one per
    advisory group (aliases merged)."""
    rows, seen = [], set()
    for result in results:
        for pkg in result.get("results", []):
            for p in pkg.get("packages", []):
                package = p["package"]
                for vuln in p.get("vulnerabilities", []):
                    names = {vuln["id"], *vuln.get("aliases", [])}
                    key = (package["name"], package["version"], min(n for n in names if n.startswith("CVE-")) if
                           any(n.startswith("CVE-") for n in names) else vuln["id"])
                    status, sev, fixed = assess(package, vuln, debian_release)
                    if status == "not_affected" or key in seen:
                        continue
                    seen.add(key)
                    rows.append({"id": vuln["id"], "aliases": sorted(names), "package": package["name"],
                                 "version": package["version"], "ecosystem": package["ecosystem"],
                                 "status": status, "severity": sev, "fixed": fixed,
                                 "ignored": bool(names & ignored)})
    return rows


def failing(rows):
    return [r for r in rows if r["status"] == "affected" and r["severity"] in FAIL and not r["ignored"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("results", nargs="+")
    ap.add_argument("--debian-release", default="13")
    ap.add_argument("--ignore")
    args = ap.parse_args(argv)
    results = []
    for path in args.results:
        with open(path, encoding="utf-8") as fh:
            results.append(json.load(fh))
    rows = evaluate(results, args.debian_release, read_ignore(args.ignore))
    counts = {}
    for r in rows:
        counts[(r["status"], r["severity"])] = counts.get((r["status"], r["severity"]), 0) + 1
    for (status, sev), n in sorted(counts.items(), key=str):
        print(f"{status:9} {sev:8} {n}")
    bad = failing(rows)
    for r in sorted(bad, key=lambda r: (r["package"], r["id"])):
        print(f"FAIL {r['severity']}: {r['package']} {r['version']} ({r['ecosystem']}) {r['id']} fixed in {r['fixed']}")
    for r in sorted((r for r in rows if r["ignored"] and r["status"] == "affected"), key=lambda r: r["id"]):
        print(f"ignored (reviewed): {r['package']} {r['id']}")
    print("Scan gate:", "FAIL" if bad else "PASS", f"({len(bad)} fixable HIGH/CRITICAL)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
