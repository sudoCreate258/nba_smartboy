# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the package lists out of a `docker save` tar without running the image (M6 R3).

Writes, into OUT_DIR: `dpkg-status` (Debian's package database), `python-packages.txt`
(name==version of every installed distribution) and `debian-release` (VERSION_ID). Layers are
applied in order, honouring whiteouts, but only the few files needed are ever read; nothing is
extracted to disk. Python standard library only.

Usage: python3 image_packages.py IMAGE.tar OUT_DIR
"""
import io
import json
import posixpath
import re
import sys
import tarfile

DPKG = "var/lib/dpkg/status"
OS_RELEASE = ("etc/os-release", "usr/lib/os-release")
DIST_INFO = re.compile(r"^(?:usr/local/)?lib/python3[^/]*/(?:site|dist)-packages/[^/]+\.dist-info/METADATA$")


def _wanted(name):
    return name == DPKG or name in OS_RELEASE or bool(DIST_INFO.match(name))


def read_image(path):
    """{path in the image: bytes} for the wanted files, as the final image sees them."""
    files = {}
    with tarfile.open(path) as outer:
        manifest = json.load(outer.extractfile("manifest.json"))
        for layer_name in manifest[0]["Layers"]:
            data = outer.extractfile(layer_name).read()
            with tarfile.open(fileobj=io.BytesIO(data)) as layer:
                for m in layer:
                    name = posixpath.normpath(m.name.lstrip("./"))
                    base = posixpath.basename(name)
                    if base.startswith(".wh."):
                        gone = posixpath.join(posixpath.dirname(name), base[4:])
                        for key in [k for k in files if k == gone or k.startswith(gone + "/")]:
                            del files[key]
                        continue
                    if m.isfile() and _wanted(name):
                        files[name] = layer.extractfile(m).read()
    return files


def packages(files):
    """(dpkg status text, python requirement lines, Debian VERSION_ID)."""
    dpkg = files.get(DPKG, b"").decode("utf-8", "replace")
    python = []
    for name, data in sorted(files.items()):
        if DIST_INFO.match(name):
            text = data.decode("utf-8", "replace")
            pkg = re.search(r"^Name: (.+)$", text, re.M)
            ver = re.search(r"^Version: (.+)$", text, re.M)
            if pkg and ver:
                python.append(f"{pkg.group(1).strip()}=={ver.group(1).strip()}")
    release = ""
    for name in OS_RELEASE:
        if name in files:
            m = re.search(r'^VERSION_ID="?([^"\n]+)"?$', files[name].decode(), re.M)
            if m:
                release = m.group(1)
                break
    return dpkg, sorted(set(python)), release


def main(argv):
    image, out = argv[1], argv[2]
    dpkg, python, release = packages(read_image(image))
    if not dpkg or not release:
        print("image_packages: no Debian package database or os-release found", file=sys.stderr)
        return 2
    with open(posixpath.join(out, "dpkg-status"), "w", encoding="utf-8") as fh:
        fh.write(dpkg)
    with open(posixpath.join(out, "python-packages.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(python) + "\n")
    with open(posixpath.join(out, "debian-release"), "w", encoding="utf-8") as fh:
        fh.write(release + "\n")
    print(f"image_packages: Debian {release}, {dpkg.count('Package: ')} deb packages, {len(python)} Python packages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
