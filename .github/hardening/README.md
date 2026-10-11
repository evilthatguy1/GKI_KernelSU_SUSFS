# NP03J manager H2

The installed repackaged manager remained recognizable by its exposed application
class, launcher class and `libksud.so` payload. This recipe renames those fields
and their Kotlin, JNI, recovery extraction and userspace launch references. It
also replaces every localized app label, migrates userspace package defaults,
and renames the bridge and optional ADB transport libraries.

The source stays pinned to pershoot/KernelSU-Next
`8e5145bd65852590cb180e09f2a6a1519a728ec5`, driver 33348. Release APK auditing
checks the actual manifest, DEX, embedded recovery script, native payload names,
package, ABI, version, localized labels and signing certificate. The exposed
fields are compared with the catalog from Duck Detector revision
`40c8a9a3dbb807b82415c4b2bc2ee67ddb29a50a`, matching the supplied report. This
static audit does not replace an on-device scan or guarantee universal hiding.

The previous build deleted its generated private signing key. A new certificate
therefore requires a matching kernel. The kernel recipe retains the same pinned
6.1.177 sources, 4 KiB pages, KMI generation, module version checks and enabled
SUSFS/NoMount/BBG/Unicode features. Its exact manager package accepts only the
new certificate and the previous certificate:
`0x3d3:217977588d1dd09269ba277a65aa403d646c34dc86d28b35fdce944eecb2e852`.
Keeping the old certificate allows the existing manager to work during the
transition and permits rollback. Signature checks remain enabled.

The newly generated PKCS12 key and password are packaged only inside an OpenSSL
CMS AES-256-GCM encrypted artifact, `manager-signing-backup.cms`. The public
recovery certificate is committed; its private key is held separately. No
unencrypted private key or password is uploaded. Recover and retain the signing
backup privately for future updates; do not upload recovered keys to a public
repository. A fresh workflow run generates another certificate, so its manager
and kernel artifacts must always be used as a matching pair.

This workflow builds artifacts only. It does not flash the tablet, change the
original ROM archive, or modify hardware attestation. Replacing an APK with a
different certificate requires removing the existing APK after booting the
matching kernel. Preserve the old APK and flashed boot image for rollback.
