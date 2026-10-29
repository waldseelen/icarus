#!/usr/bin/env python3
"""Build a binary Debian (.deb) package without requiring dpkg-deb or debhelper."""

import io
import os
import tarfile
from pathlib import Path

VERSION = "1.0.0"
PKG = "icarus"


def make_tar_gz(
    members: list[tuple[str, bytes, int]],
    links: list[tuple[str, str]] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data, mode in members:
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            ti.mode = mode
            ti.uid = 0
            ti.gid = 0
            ti.uname = "root"
            ti.gname = "root"
            tar.addfile(ti, io.BytesIO(data))
        if links:
            for link_name, target in links:
                ti = tarfile.TarInfo(name=link_name)
                ti.type = tarfile.SYMTYPE
                ti.linkname = target
                ti.mode = 0o777
                ti.uid = 0
                ti.gid = 0
                tar.addfile(ti)
    return buf.getvalue()


def write_ar(entries: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in entries:
        hdr = (
            f"{name:<16}"
            f"{'0':<12}"
            f"{'0':<6}"
            f"{'0':<6}"
            f"{'100644':<8}"
            f"{len(data):<10}`\n"
        ).encode("ascii")
        out.write(hdr)
        out.write(data)
        if len(data) % 2 != 0:
            out.write(b"\n")
    return out.getvalue()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    dist_dir = root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    # 1. debian-binary
    deb_binary = b"2.0\n"

    # 2. control.tar.gz
    pkg_control = f"""Package: {PKG}
Version: {VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: Bugra <user@local>
Depends: python3 (>= 3.9)
Provides: icarusctl
Description: Cross-distro driver and GUI/CLI utility for Gamepower Icarus
 Universal Linux userspace driver, desktop GUI, and CLI utility for configuring
 the Gamepower Icarus (Sinowealth 258a:0027) gaming mouse via /dev/hidraw.
 Includes full DPI control, RGB lighting effects, button remapping, TEA-decrypted
 Windows .BKM backup profile import, and declarative JSON configuration.
"""
    control_tar = make_tar_gz([("./control", pkg_control.encode("utf-8"), 0o644)])

    # 3. data.tar.gz
    data_members: list[tuple[str, bytes, int]] = []
    links: list[tuple[str, str]] = []

    # Standalone script in /usr/bin/icarus
    bin_script = (root / "dist" / "icarus").read_bytes()
    data_members.append(("./usr/bin/icarus", bin_script, 0o755))

    # Symlink /usr/bin/icarusctl -> icarus
    links.append(("./usr/bin/icarusctl", "icarus"))

    # Udev rule
    udev_rule = (root / "packaging" / "udev" / "70-gamepower-icarus.rules").read_bytes()
    data_members.append(("./lib/udev/rules.d/70-gamepower-icarus.rules", udev_rule, 0o644))

    # Desktop entry & Icon
    desktop_file = (root / "packaging" / "desktop" / "icarus.desktop").read_bytes()
    data_members.append(("./usr/share/applications/icarus.desktop", desktop_file, 0o644))

    icon_file = (root / "icarus" / "web" / "assets" / "icon.png").read_bytes()
    data_members.append(("./usr/share/pixmaps/icarus.png", icon_file, 0o644))

    # Documentation
    readme = (root / "README.md").read_bytes()
    data_members.append((f"./usr/share/doc/{PKG}/README.md", readme, 0o644))

    data_tar = make_tar_gz(data_members, links=links)

    # 4. Assemble .deb
    deb_bytes = write_ar([
        ("debian-binary", deb_binary),
        ("control.tar.gz", control_tar),
        ("data.tar.gz", data_tar),
    ])

    out_file = dist_dir / f"{PKG}_{VERSION}_all.deb"
    out_file.write_bytes(deb_bytes)
    print(f"Created Debian package: {out_file} ({len(deb_bytes)} bytes)")


if __name__ == "__main__":
    main()
