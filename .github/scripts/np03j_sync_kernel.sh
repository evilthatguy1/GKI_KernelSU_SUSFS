#!/usr/bin/env bash
set -euo pipefail
cd "$GITHUB_WORKSPACE/kernel"
repo init -u https://android.googlesource.com/kernel/manifest \
  -b "$MANIFEST_COMMIT" --depth=1 --no-clone-bundle
test "$(git -C .repo/manifests rev-parse HEAD)" = "$MANIFEST_COMMIT"
cp "$GITHUB_WORKSPACE/.github/config/np03j-6.1.177-manifest.xml" .repo/manifests/default.xml
repo sync --no-manifest-update --no-tags --no-clone-bundle -c -j4 --fail-fast
repo manifest -r -o "$GITHUB_WORKSPACE/build-info/resolved-manifest.xml"
python3 "$GITHUB_WORKSPACE/.github/scripts/np03j_recipe.py" check-kernel
python3 - <<'PY'
import os,pathlib,subprocess,xml.etree.ElementTree as E
root=pathlib.Path(os.environ['GITHUB_WORKSPACE'])
for p in E.parse(root/'.github/config/np03j-6.1.177-manifest.xml').findall('project'):
 actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root/'kernel'/p.get('path'),text=True).strip()
 assert actual==p.get('revision'),p.get('path')
print('ALL_AOSP_PROJECT_REVISIONS=PASS')
PY
