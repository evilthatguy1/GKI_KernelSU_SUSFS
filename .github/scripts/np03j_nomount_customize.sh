#!/system/bin/sh
# Installer for the matching built-in NP03J NoMount driver.
ui_print "- Installing NoMount for NP03J"
[ "$ARCH" = "arm64" ] || abort "! This build requires arm64"
[ "$KSU" = "true" ] || abort "! This build requires KernelSU"
[ -f "$MODPATH/bin/nm-arm64" ] || abort "! NoMount binary missing"
mv "$MODPATH/bin/nm-arm64" "$MODPATH/bin/nm"
set_perm "$MODPATH/bin/nm" 0 0 0755
"$MODPATH/bin/nm" version >/dev/null 2>&1 || abort "! Flash the matching NoMount kernel first"
if grep -q '^nomount ' /proc/modules; then
    abort "! This package requires the built-in NoMount driver"
fi
mkdir -p /data/adb/ksu/bin /data/adb/nomount
ln -sf /data/adb/modules/nomount/bin/nm /data/adb/ksu/bin/nm || abort "! Cannot create NoMount link"
rm -f "$MODPATH/bin/nm-arm" /data/adb/nomount/.booting
ui_print "- NoMount built-in support verified"
