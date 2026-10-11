#!/usr/bin/env python3
"""Remove exposed manager identifiers and audit the resulting APK. Does not flash."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

PACKAGE = 'io.vqmxaz.tnprke.lhcsud'
APP = 'ControlSession'
ACTIVITY = 'ControlPanel'
PAYLOAD = 'libdevicecore.so'
JNI = 'devicebridge'
ADB = 'libdevicetransport.so'
ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ['GITHUB_WORKSPACE']) / 'manager-source'
EXTENSIONS = {'.kt', '.kts', '.java', '.aidl', '.xml', '.c', '.cc', '.cpp', '.h', '.pro', '.sh', '.txt'}


def prepare():
    manager = SOURCE / 'manager'
    for path in manager.rglob('*'):
        if path.is_file() and path.suffix in EXTENSIONS:
            before = path.read_text()
            text = re.sub(r'\bKernelSUApplication\b', APP, before)
            text = re.sub(r'\bMainActivity\b', ACTIVITY, text)
            text = text.replace('libksud.so', PAYLOAD).replace('libadbroot.so', ADB)
            if path.name == 'strings.xml':
                text = re.sub(r'(<string\s+name="app_name"[^>]*>)[^<]*(</string>)', r'\g<1>Device Control\2', text)
            if path.name == 'CMakeLists.txt':
                text = re.sub(r'\bkernelsu\b', JNI, text)
                text = re.sub(r'\badbroot\b(?=\s)', 'devicetransport', text)
            if path.name == 'Natives.kt':
                text = text.replace('System.loadLibrary("kernelsu")', f'System.loadLibrary("{JNI}")')
            if text != before:
                path.write_text(text)
    java = manager / 'app/src/main/java/com/rifsxd/ksunext'
    (java / 'KernelSUApplication.kt').rename(java / (APP + '.kt'))
    (java / 'ui/MainActivity.kt').rename(java / 'ui' / (ACTIVITY + '.kt'))
    # Include shell extraction paths in recovery's embedded update-binary.
    script = manager / 'scripts/update_binary.sh'
    text = script.read_text().replace('libksud.so', PAYLOAD)
    script.write_text(text)
    # Fix userspace defaults and explicit late-load launch target as well as the APK namespace.
    for path in (SOURCE / 'userspace/ksud/src').rglob('*.rs'):
        before = path.read_text()
        text = before.replace('com.rifsxd.ksunext', PACKAGE)
        text = re.sub(r'\bMainActivity\b', ACTIVITY, text)
        if text != before:
            path.write_text(text)
    manifest = ET.parse(manager / 'app/src/main/AndroidManifest.xml')
    ns = '{http://schemas.android.com/apk/res/android}'
    application = manifest.find('application')
    assert application.get(ns + 'name') == '.' + APP
    assert application.find('activity').get(ns + 'name') == '.ui.' + ACTIVITY
    assert all(a.get(ns + 'targetActivity') == '.ui.' + ACTIVITY for a in application.findall('activity-alias'))
    assert not any('zygotePreloadName' in k for k in application.attrib)
    for path in manager.rglob('*'):
        if path.is_file() and path.suffix in EXTENSIONS:
            text = path.read_text()
            assert not re.search(r'\b(KernelSUApplication|MainActivity)\b', text), path
            assert 'libksud.so' not in text, path
    assert f'System.loadLibrary("{JNI}")' in (manager / 'app/src/main/java/com/rifsxd/ksunext/Natives.kt').read_text()
    cmake = (manager / 'app/src/main/cpp/CMakeLists.txt').read_text()
    assert f'add_library({JNI}' in cmake
    assert 'add_library(devicetransport SHARED adbroot.cc)' in cmake
    print('MANAGER_CLASSES_NATIVE_NAMES_AND_CALL_SITES=PASS')


def audit(apk, aapt):
    apk = Path(apk)
    folder = apk.parent
    badging = subprocess.check_output([aapt, 'dump', 'badging', str(apk)], text=True)
    xmltree = subprocess.check_output([aapt, 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], text=True)
    assert f"package: name='{PACKAGE}'" in badging
    assert "versionCode='33348'" in badging
    assert "application-label:'Device Control'" in badging
    labels = re.findall(r"^application-label[^:]*:'([^']*)'", badging, flags=re.M)
    assert labels and all(label == 'Device Control' for label in labels), labels
    launcher = re.search(r"launchable-activity: name='([^']+)'", badging).group(1)
    assert launcher == PACKAGE + '.ui.' + ACTIVITY, launcher
    assert PACKAGE + '.' + APP in xmltree or '".' + APP + '"' in xmltree
    assert 'zygotePreloadName' not in xmltree
    for token in ('KernelSUApplication', 'MainActivity', 'com.rifsxd.ksunext', 'com/rifsxd/ksunext'):
        assert token not in xmltree, token
    forbidden_libraries = {'libksud.so', 'libkernelsu.so', 'libadbroot.so', 'libapd.so', 'libmagisk.so'}
    with zipfile.ZipFile(apk) as archive:
        assert archive.testzip() is None
        libraries = {Path(p).name for p in archive.namelist() if p.startswith('lib/')}
        assert not libraries & forbidden_libraries, libraries
        required = {PAYLOAD, 'lib' + JNI + '.so', ADB}
        assert required <= libraries, libraries
        for name in archive.namelist():
            if name.startswith('lib/'):
                assert name.startswith('lib/arm64-v8a/'), name
            if re.fullmatch(r'classes\d*\.dex', name):
                data = archive.read(name)
                for token in (b'KernelSUApplication', b'com/rifsxd/ksunext', b'com.rifsxd.ksunext', b'libksud.so'):
                    assert token not in data, (name, token)
        update = archive.read('META-INF/com/google/android/update-binary')
        assert PAYLOAD.encode() in update and b'libksud.so' not in update
        daemon = archive.read('lib/arm64-v8a/' + PAYLOAD)
        assert daemon[:4] == b'\x7fELF'
    # Match the independent fields exposed through PackageManager/LauncherApps and nativeLibraryDir.
    # This is a static check against the exact report's catalog, not an on-device verdict.
    catalog = json.loads((ROOT / '.github/hardening/catalog.json').read_text())
    cert = (folder / 'manager-cert.der').read_bytes()
    digest = hashlib.sha256(cert).hexdigest()
    for signature in catalog['signatures']:
        assert PACKAGE not in signature['package_names']
        assert digest not in signature['certificates']
        assert not libraries & set(signature['native_payloads'])
        for name in (PACKAGE + '.' + APP, launcher):
            assert not any(name == p or name.startswith(p + '.') for p in signature['code_namespaces'])
        assert not any((PACKAGE + '.' + APP).endswith(p) for p in signature['application_suffixes'])
        assert not any(launcher.endswith(p) for p in signature['launcher_suffixes'])
        assert not any('Device Control'.startswith(p) for p in signature['label_prefixes'])
    report = {'source_commit': os.environ['ROOT_COMMIT'], 'detector_commit': catalog['commit'],
              'package': PACKAGE, 'application_class': PACKAGE + '.' + APP, 'launcher_class': launcher,
              'native_payloads': sorted(libraries), 'certificate_sha256': digest,
              'known_catalog_anchors': [], 'static_apk_audit': 'PASS', 'device_tested': False}
    (folder / 'manager-fingerprint-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    (folder / 'manifest-audit.txt').write_text(xmltree)
    print('MANAGER_APK_AND_EXPOSED_CATALOG_ANCHORS=PASS')


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare()
    elif sys.argv[1] == 'audit' and len(sys.argv) == 4:
        audit(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit('usage: manager.py prepare | audit APK AAPT')
