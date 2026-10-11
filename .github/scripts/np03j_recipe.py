#!/usr/bin/env python3
"""Pinned NP03J build preparation and artifact verification. Never flashes a device."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / ".github/config/np03j-next-6.1.177.json"
LOCK = json.loads(LOCK_PATH.read_text())
WORK = Path(os.environ.get("GITHUB_WORKSPACE", ROOT))
INFO = WORK / "build-info"


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def checked_clone(url, sha, destination):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError(f"Invalid immutable revision: {sha}")
    subprocess.run(["git", "clone", "--no-checkout", url, str(destination)], check=True)
    subprocess.run(["git", "fetch", "origin", sha], cwd=destination, check=True)
    subprocess.run(["git", "checkout", "--detach", sha], cwd=destination, check=True)
    assert run("git", "rev-parse", "HEAD", cwd=destination) == sha


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one occurrence in {path}: {old}")
    path.write_text(text.replace(old, new, 1))


def emit(path_variable, values):
    path = os.environ.get(path_variable)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                assert "\n" not in str(value)
                handle.write(f"{key}={value}\n")


def export_lock():
    for key, value in LOCK.items():
        if key.endswith("_commit"):
            assert re.fullmatch(r"[0-9a-f]{40}", value), key
    manifest = ET.parse(ROOT / ".github/config/np03j-6.1.177-manifest.xml")
    for project in manifest.findall("project"):
        assert re.fullmatch(r"[0-9a-f]{40}", project.get("revision", ""))
    assert manifest.find("project[@path='common']").get("revision") == LOCK["kernel_common_commit"]
    assert LOCK["features"] == ["SUSFS", "NoMount", "BBG", "Unicode"]
    assert LOCK["kernel_version"] == "6.1.177" and LOCK["page_size"] == "4k"
    assert LOCK["branding"] == "" and not LOCK["allow_version_mismatch"]
    emit("GITHUB_ENV", {k.upper(): v for k, v in LOCK.items() if isinstance(v, (str, int))})
    INFO.mkdir(exist_ok=True)
    shutil.copy2(LOCK_PATH, INFO / "source-lock.json")
    shutil.copy2(ROOT / ".github/config/np03j-6.1.177-manifest.xml", INFO / "pinned-manifest.xml")
    print("SOURCE_LOCK=PASS")


def check_kernel():
    common = WORK / "kernel/common"
    assert run("git", "rev-parse", "HEAD", cwd=common) == LOCK["kernel_common_commit"]
    text = (common / "Makefile").read_text()
    for key, value in (("VERSION", 6), ("PATCHLEVEL", 1), ("SUBLEVEL", 177)):
        assert re.search(rf"^{key}\s*=\s*{value}\s*$", text, re.M), key
    assert re.search(r"^KMI_GENERATION=11$", (common / "build.config.common").read_text(), re.M)
    print("KERNEL_6.1.177_KMI11=PASS")


def prepare_manager():
    source = WORK / "manager-source"
    assert run("git", "rev-parse", "HEAD", cwd=source) == LOCK["root_commit"]
    manager = source / "manager"
    old, new = "com.rifsxd.ksunext", LOCK["manager_package"]
    extensions = {".kt", ".kts", ".java", ".xml", ".c", ".cpp", ".h", ".pro", ".properties", ".toml"}
    changed = 0
    for path in manager.rglob("*"):
        if not path.is_file() or path.suffix not in extensions:
            continue
        text = path.read_text()
        for before, after in ((old, new), (old.replace(".", "/"), new.replace(".", "/")),
                              (old.replace(".", "_"), new.replace(".", "_"))):
            text = text.replace(before, after)
        if text != path.read_text():
            path.write_text(text)
            changed += 1
    assert changed > 20
    app = manager / "app/build.gradle.kts"
    replace_once(app, "    alias(libs.plugins.lsplugin.apksign)\n", "")
    text = app.read_text()
    text, count = re.subn(r"\napksign \{.*?\n\}\n", "\n", text, flags=re.S)
    assert count == 1
    app.write_text(text)
    replace_once(app, "    defaultConfig {\n", f'    defaultConfig {{\n        applicationId = "{new}"\n')
    gradle = manager / "build.gradle.kts"
    replace_once(gradle, 'abiFilters("arm64-v8a", "x86_64", "riscv64")', 'abiFilters("arm64-v8a")')
    replace_once(gradle, 'listOf("arm64-v8a", "x86_64", "riscv64")', 'listOf("arm64-v8a")')
    replace_once(gradle, "val managerVersionCode by extra(getVersionCode())", f'val managerVersionCode by extra({LOCK["driver_version"]})')
    replace_once(gradle, "val managerVersionName by extra(getVersionName())", f'val managerVersionName by extra("{LOCK["manager_version"]}")')
    replace_once(gradle, 'rootProject.extra.set("managerVersionCode", getVersionCode())', f'rootProject.extra.set("managerVersionCode", {LOCK["driver_version"]})')
    replace_once(gradle, 'rootProject.extra.set("managerVersionName", getVersionName())', f'rootProject.extra.set("managerVersionName", "{LOCK["manager_version"]}")')
    strings = manager / "app/src/main/res/values/strings.xml"
    replace_once(strings, '>KernelSU-Next</string>', '>Device Control</string>')
    build_rs = source / "userspace/ksud/build.rs"
    text = build_rs.read_text()
    fixed = ('fn get_git_version() -> Result<(u32, String), std::io::Error> {\n'
             f'    Ok(({LOCK["driver_version"]}, "{LOCK["manager_version"]}".to_string()))\n' + '}\n\n')
    text, count = re.subn(r"fn get_git_version\(\).*?(?=fn configure_bindgen\()", fixed, text, flags=re.S)
    assert count == 1
    build_rs.write_text(text)
    print(f"MANAGER_PACKAGE={new}\nMANAGER_SOURCE_PATCH=PASS")


def prepare_root():
    directory = WORK / "kernel/KernelSU-Next"
    checked_clone("https://github.com/" + LOCK["root_repo"] + ".git", LOCK["root_commit"], directory)
    common = WORK / "kernel/common"
    link = common / "drivers/kernelsu"
    assert not link.exists() and not link.is_symlink()
    link.symlink_to(os.path.relpath(directory / "kernel", link.parent))
    with (common / "drivers/Makefile").open("a") as handle:
        handle.write("\nobj-$(CONFIG_KSU) += kernelsu/\n")
    with (common / "drivers/Kconfig").open("a") as handle:
        handle.write('\nsource "drivers/kernelsu/Kconfig"\n')
    signature = os.environ["MANAGER_SIGNATURE"]
    assert re.fullmatch(r"0x[0-9a-f]+:[0-9a-f]{64}", signature)
    kbuild = directory / "kernel/Kbuild"
    text = kbuild.read_text()
    replacements = {
        "KSU_GIT_VERSION :=": f'KSU_GIT_VERSION := {LOCK["driver_version"] - 30000}',
        "KSU_GIT_TAG :=": f'KSU_GIT_TAG := {LOCK["manager_version"]}',
        "KSU_VERSION_FALLBACK :=": f'KSU_VERSION_FALLBACK := {LOCK["driver_version"]}',
        "KSU_VERSION_TAG_FALLBACK :=": f'KSU_VERSION_TAG_FALLBACK := {LOCK["manager_version"]}',
        "KSU_NEXT_MANAGER_LIST :=": f"KSU_NEXT_MANAGER_LIST := {signature}",
    }
    for prefix, replacement in replacements.items():
        text, count = re.subn(r"^" + re.escape(prefix) + r".*$", replacement, text, flags=re.M)
        assert count == 1, prefix
    text = f'KSU_MANAGER_PACKAGE := {LOCK["manager_package"]}\n' + text
    text = text.replace('$(error "KernelSU requires either CONFIG_KPROBES=y or CONFIG_KSU_SUSFS=y")',
                        '$(warning "KernelSU config unavailable during clean; validated before build")')
    kbuild.write_text(text)
    (INFO / "manager-trust.json").write_text(json.dumps({"package": LOCK["manager_package"],
        "signature": signature, "driver_version": LOCK["driver_version"]}, indent=2) + "\n")
    emit("GITHUB_ENV", {"ROOT_IMPLEMENTATION": "next", "ROOT_MANAGER": "NP03J custom Next Manager",
        "ROOT_VERSION": LOCK["manager_version"], "ROOT_COMMIT": LOCK["root_commit"],
        "KSU_VERSION": LOCK["driver_version"]})
    print("ROOT_AND_MANAGER_TRUST=PASS")


def prepare_susfs():
    directory = WORK / "susfs4ksu"
    checked_clone(LOCK["susfs_repo"], LOCK["susfs_commit"], directory)
    emit("GITHUB_ENV", {"SUSFS_COMMIT": LOCK["susfs_commit"]})
    print("SUSFS_PIN=PASS")


def prepare_bbg():
    directory = WORK / "kernel/Baseband-guard"
    checked_clone("https://github.com/vc-teahouse/Baseband-guard.git", LOCK["bbg_commit"], directory)
    subprocess.run(["bash", str(directory / "setup.sh"), LOCK["bbg_commit"]], cwd=WORK / "kernel", check=True)
    assert run("git", "rev-parse", "HEAD", cwd=directory) == LOCK["bbg_commit"]
    kconfig = WORK / "kernel/common/security/Kconfig"
    text = kconfig.read_text()
    start = text.index("config LSM\n")
    end = text.index('source "security/Kconfig.hardening"', start)
    block, count = re.subn(r'(default "[^"\n]*)"', r'\1,baseband_guard"', text[start:end])
    assert count == 5
    text = text[:start] + block + text[end:]
    kconfig.write_text(text)
    emit("GITHUB_ENV", {"BBG_COMMIT": LOCK["bbg_commit"]})
    print("BBG_PIN=PASS")


def verify_sources():
    for directory, key in (("kernel_patches", "kernel_patches_commit"), ("AnyKernel3", "anykernel3_commit"),
                            ("kernel/KernelSU-Next", "root_commit"), ("susfs4ksu", "susfs_commit"),
                            ("kernel/common/NoMount", "nomount_commit"), ("kernel/Baseband-guard", "bbg_commit")):
        assert run("git", "rev-parse", "HEAD", cwd=WORK / directory) == LOCK[key], directory
    rejects = list((WORK / "kernel/common").rglob("*.rej"))
    assert not rejects, rejects
    kbuild = (WORK / "kernel/KernelSU-Next/kernel/Kbuild").read_text()
    assert f'KSU_NEXT_MANAGER_LIST := {os.environ["MANAGER_SIGNATURE"]}' in kbuild
    assert f'KSU_MANAGER_PACKAGE := {LOCK["manager_package"]}' in kbuild
    assert "force check_version" not in (WORK / "kernel/common/kernel/module/version.c").read_text()
    (INFO / "kernel-patch.diff").write_text(run("git", "diff", "--binary", cwd=WORK / "kernel/common") + "\n")
    print("PINNED_SOURCES_AND_PATCH_REJECTS=PASS")


def package():
    common = WORK / "kernel/common"
    image = WORK / "AnyKernel3/Image"
    assert image.is_file() and image.stat().st_size > 10_000_000
    configs = list((WORK / "kernel/bazel-bin/common").glob("**/.config"))
    configs += list(Path("/home/runner/out").glob("**/.config"))
    assert configs, "Generated .config was not found"
    config = configs[0].read_text()
    wanted = ["KSU", "KSU_SUSFS", "NOMOUNT", "BBG", "ARM64_4K_PAGES", "MODVERSIONS", "SECURITY_SELINUX"]
    wanted += ["KSU_SUSFS_" + x for x in ("SUS_PATH", "SUS_MOUNT", "SUS_KSTAT", "SPOOF_UNAME",
               "HIDE_KSU_SUSFS_SYMBOLS", "SPOOF_CMDLINE_OR_BOOTCONFIG", "OPEN_REDIRECT", "SUS_MAP")]
    lsm = re.search(r'^CONFIG_LSM="([^"\n]+)"$', config, re.M)
    assert lsm and "baseband_guard" in lsm.group(1).split(","), "BBG missing from active LSMs"
    for symbol in wanted:
        assert f"CONFIG_{symbol}=y\n" in config, symbol
    for symbol in ("ARM64_16K_PAGES", "ARM64_64K_PAGES", "KSU_DEBUG", "KSU_SUSFS_ENABLE_LOG", "BBG_BLOCK_BOOT", "BBG_BLOCK_RECOVERY"):
        assert f"CONFIG_{symbol}=y\n" not in config, symbol
    banners = re.findall(rb"Linux version ([^\x00\n]+)", image.read_bytes())
    assert banners and banners[0].startswith(b"6.1.177-android14-11"), banners[:1]
    assert b"Wild" not in banners[0] and b"dirty" not in banners[0], banners[0]
    INFO.mkdir(exist_ok=True)
    shutil.copy2(configs[0], INFO / "kernel.config")
    (INFO / "kernel-banner.txt").write_bytes(banners[0] + b"\n")
    (INFO / "patch-verification.txt").write_text("PATCH_REJECTS=0\nCONFIG=PASS\nVERSION=PASS\nDEVICE_TESTED=NO\n")
    output = WORK / "deliverables"
    output.mkdir(exist_ok=True)
    with zipfile.ZipFile(output / "NP03J-6.1.177-android14-11-Next-AnyKernel3.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((WORK / "AnyKernel3").rglob("*")):
            relative = path.relative_to(WORK / "AnyKernel3")
            if path.is_file() and ".git" not in relative.parts and ".github" not in relative.parts:
                archive.write(path, relative)
    for path in output.glob("*.zip"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    (INFO / "patched-kernel-commit.txt").write_text(run("git", "rev-parse", "HEAD", cwd=common) + "\n")
    print("GENERATED_CONFIG_KERNEL_VERSION_AND_PACKAGE=PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export-lock", "check-kernel", "prepare-manager", "prepare-root",
                                         "prepare-susfs", "prepare-bbg", "verify-sources", "package"))
    command = parser.parse_args().command.replace("-", "_")
    globals()[command]()


if __name__ == "__main__":
    main()
