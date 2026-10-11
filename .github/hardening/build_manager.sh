#!/usr/bin/env bash
set -euo pipefail

source_dir="$GITHUB_WORKSPACE/manager-source"
sdk_dir="${ANDROID_HOME:?ANDROID_HOME is required}"
ndk_dir="$sdk_dir/ndk/29.0.14206865"
llvm_bin="$ndk_dir/toolchains/llvm/prebuilt/linux-x86_64/bin"
build_tools="$sdk_dir/build-tools/36.1.0"

sdkmanager --install 'platforms;android-36' 'build-tools;36.1.0' 'ndk;29.0.14206865' 'cmake;3.22.1'
sudo apt-get update -qq
sudo apt-get install -y -qq libclang-dev pkg-config
rustup toolchain install "$RUST_TOOLCHAIN" --profile minimal
rustup target add --toolchain "$RUST_TOOLCHAIN" aarch64-linux-android

export ANDROID_NDK_HOME="$ndk_dir"
export ANDROID_NDK_ROOT="$ndk_dir"
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$llvm_bin/aarch64-linux-android26-clang"
export CC_aarch64_linux_android="$llvm_bin/aarch64-linux-android26-clang"
export CXX_aarch64_linux_android="$llvm_bin/aarch64-linux-android26-clang++"
export AR_aarch64_linux_android="$llvm_bin/llvm-ar"
export BINDGEN_EXTRA_CLANG_ARGS_aarch64_linux_android="--target=aarch64-linux-android26 --sysroot=$ndk_dir/toolchains/llvm/prebuilt/linux-x86_64/sysroot -I$ndk_dir/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include/aarch64-linux-android"
export RUSTFLAGS='-C link-arg=-Wl,-z,max-page-size=16384'

cd "$source_dir/userspace/ksuinit"
cargo "+$RUST_TOOLCHAIN" build --locked --target aarch64-linux-android --release
cp target/aarch64-linux-android/release/ksuinit "$source_dir/userspace/ksud/bin/aarch64/ksuinit"
cd "$source_dir/userspace/ksud"
"$llvm_bin/clang" --target=aarch64-linux-gnu -c -nostdlib -o .lkm_image_bootstrap.o src/lkm_image_bootstrap.S
cargo "+$RUST_TOOLCHAIN" build --locked --target aarch64-linux-android --release
mkdir -p "$source_dir/manager/app/src/main/jniLibs/arm64-v8a"
cp target/aarch64-linux-android/release/ksud "$source_dir/manager/app/src/main/jniLibs/arm64-v8a/libdevicecore.so"

cd "$source_dir/manager"
chmod +x gradlew
./gradlew --no-daemon clean assembleRelease
mapfile -t apks < <(find app/build/outputs/apk/release -type f -name '*.apk' | sort)
test "${#apks[@]}" -eq 1

export NP03J_SIGN_PASS
NP03J_SIGN_PASS="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
echo "::add-mask::$NP03J_SIGN_PASS"
key_file="$RUNNER_TEMP/np03j-manager-signing.p12"
cert_file="$GITHUB_WORKSPACE/manager-deliverables/manager-cert.der"
mkdir -p "$GITHUB_WORKSPACE/manager-deliverables"
umask 077
keytool -genkeypair -keystore "$key_file" -storetype PKCS12 -alias np03j \
  -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=Device Control' \
  -storepass:env NP03J_SIGN_PASS -keypass:env NP03J_SIGN_PASS
keytool -exportcert -keystore "$key_file" -alias np03j -storepass:env NP03J_SIGN_PASS -file "$cert_file"
apk_out="$GITHUB_WORKSPACE/manager-deliverables/NP03J-Next-Manager.apk"
"$build_tools/apksigner" sign --ks "$key_file" --ks-key-alias np03j \
  --ks-pass env:NP03J_SIGN_PASS --key-pass env:NP03J_SIGN_PASS \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled false --v4-signing-enabled false \
  --out "$apk_out" "${apks[0]}"
"$build_tools/apksigner" verify --verbose --print-certs "$apk_out" > "$GITHUB_WORKSPACE/manager-deliverables/signature-verification.txt"
"$build_tools/aapt" dump badging "$apk_out" > "$GITHUB_WORKSPACE/manager-deliverables/apk-badging.txt"
export APK_OUT="$apk_out" CERT_FILE="$cert_file"
python3 - <<'PY'
import hashlib, json, os, pathlib, re
folder=pathlib.Path(os.environ['GITHUB_WORKSPACE'])/'manager-deliverables'
cert=pathlib.Path(os.environ['CERT_FILE']).read_bytes()
digest=hashlib.sha256(cert).hexdigest()
signature=f'0x{len(cert):x}:{digest}'
assert len(cert)<=1024, 'Kernel certificate buffer limit exceeded'
verification=(folder/'signature-verification.txt').read_text()
assert 'Verified using v2 scheme (APK Signature Scheme v2): true' in verification
assert re.search(r'Signer #1 certificate SHA-256 digest: '+digest, verification)
badging=(folder/'apk-badging.txt').read_text()
assert f"package: name='{os.environ['MANAGER_PACKAGE']}'" in badging
assert f"versionCode='{os.environ['DRIVER_VERSION']}'" in badging
assert "native-code: 'arm64-v8a'" in badging
data={'package':os.environ['MANAGER_PACKAGE'],'signature':signature,'driver_version':int(os.environ['DRIVER_VERSION']),
      'source_commit':os.environ['ROOT_COMMIT'],'source_repository':os.environ['ROOT_REPO'],'device_tested':False}
(folder/'manager-trust.json').write_text(json.dumps(data,indent=2)+'\n')
with open(os.environ['GITHUB_OUTPUT'],'a') as out:
 out.write('signature='+signature+'\n')
apk=pathlib.Path(os.environ['APK_OUT'])
apk.with_suffix('.apk.sha256').write_text(hashlib.sha256(apk.read_bytes()).hexdigest()+'  '+apk.name+'\n')
print('MANAGER_SIGNATURE_PACKAGE_AND_VERSION=PASS')
PY
python3 "$GITHUB_WORKSPACE/.github/hardening/manager.py" audit "$apk_out" "$build_tools/aapt"
backup_dir="$RUNNER_TEMP/np03j-signing-backup"
mkdir -m 0700 "$backup_dir"
cp "$key_file" "$backup_dir/manager-signing.p12"
printf '%s' "$NP03J_SIGN_PASS" > "$backup_dir/password.txt"
tar -cf "$RUNNER_TEMP/np03j-signing-backup.tar" -C "$backup_dir" manager-signing.p12 password.txt
openssl cms -encrypt -binary -aes-256-gcm -in "$RUNNER_TEMP/np03j-signing-backup.tar" \
  -outform DER -out "$GITHUB_WORKSPACE/manager-deliverables/manager-signing-backup.cms" \
  "$GITHUB_WORKSPACE/.github/hardening/signing-recovery.crt"
test -s "$GITHUB_WORKSPACE/manager-deliverables/manager-signing-backup.cms"
rm -rf "$backup_dir" "$RUNNER_TEMP/np03j-signing-backup.tar"
rm -f "$key_file"
unset NP03J_SIGN_PASS
echo 'ENCRYPTED_SIGNING_KEY_BACKUP=PASS' 
