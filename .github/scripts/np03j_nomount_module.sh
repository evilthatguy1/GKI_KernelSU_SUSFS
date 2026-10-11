#!/usr/bin/env bash
set -euo pipefail
archive="$RUNNER_TEMP/np03j-zig.tar.xz"
curl --fail --location --retry 4 "$ZIG_URL" --output "$archive"
printf '%s  %s\n' "$ZIG_SHA256" "$archive" | sha256sum --check -
mkdir -p "$RUNNER_TEMP/np03j-zig"
tar -xJf "$archive" -C "$RUNNER_TEMP/np03j-zig" --strip-components=1
zig_bin="$RUNNER_TEMP/np03j-zig/zig"
test "$("$zig_bin" version)" = "$ZIG_VERSION"
source_dir="$GITHUB_WORKSPACE/kernel/common/NoMount"
test "$(git -C "$source_dir" rev-parse HEAD)" = "$NOMOUNT_COMMIT"
module_dir="$RUNNER_TEMP/np03j-nomount-module"
cp -a "$source_dir/module" "$module_dir"
cp "$GITHUB_WORKSPACE/.github/scripts/np03j_nomount_customize.sh" "$module_dir/customize.sh"
mkdir -p "$module_dir/bin" "$GITHUB_WORKSPACE/deliverables"
cd "$source_dir/userspace/src"
"$zig_bin" cc -target aarch64-linux -Oz -mcmodel=tiny -static -nostdlib \
  -ffreestanding -fno-unwind-tables -fno-ident -Wno-invalid-noreturn \
  -Wl,--entry=_start nm.c -o "$module_dir/bin/nm-arm64"
"$zig_bin" cc -target arm-linux -Oz -static -nostdlib -ffreestanding \
  -fno-unwind-tables -fno-ident -Wno-invalid-noreturn \
  -ffunction-sections -fdata-sections -Wl,--gc-sections -Wl,--entry=_start \
  nm.c -o "$module_dir/bin/nm-arm"
chmod 0755 "$module_dir/bin/nm-arm64" "$module_dir/bin/nm-arm"
printf '%s\n' "$NOMOUNT_COMMIT" > "$module_dir/NOMOUNT_SOURCE_COMMIT"
cd "$module_dir"
zip -qr "$GITHUB_WORKSPACE/deliverables/NP03J-NoMount-$NOMOUNT_COMMIT.zip" .
echo 'NOMOUNT_MATCHING_MODULE=PASS'
