#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
mkdir -p "$root/dist"
stage="$(mktemp -d "${TMPDIR:-/tmp}/codex-queue-app.XXXXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
app="$stage/候场.app"
contents="$app/Contents"
mkdir -p "$contents/MacOS" "$contents/Resources/queue/static" "$contents/Resources/queue/vendored"
cp launcher.py server.py adapter.py LICENSE NOTICE.md "$contents/Resources/queue/"
cp static/{index.html,style.css,app.js} "$contents/Resources/queue/static/"
cp vendored/{codex_rpc.py,LICENSE,SOURCE.md} "$contents/Resources/queue/vendored/"
cat > "$contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Queue</string>
<key>CFBundleIdentifier</key><string>local.codex-task-queue.app</string>
<key>CFBundleName</key><string>候场</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.2.2</string>
<key>CFBundleVersion</key><string>4</string>
<key>CFBundleIconFile</key><string>Queue.icns</string>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
mkdir -p "$stage/Queue.iconset"
xcrun swift macos/Icon.swift "$stage/icon.png"
for side in 16 32 128 256 512; do
    sips -z "$side" "$side" "$stage/icon.png" --out "$stage/Queue.iconset/icon_${side}x${side}.png" >/dev/null
    retina=$((side * 2))
    sips -z "$retina" "$retina" "$stage/icon.png" --out "$stage/Queue.iconset/icon_${side}x${side}@2x.png" >/dev/null
done
iconutil -c icns "$stage/Queue.iconset" -o "$contents/Resources/Queue.icns"
xcrun swiftc macos/App.swift -o "$contents/MacOS/Queue"
xattr -cr "$app"
codesign --force --sign - "$app"
codesign --verify --strict "$app"
ditto -c -k --keepParent --norsrc "$app" "$root/dist/候场-macOS.zip"
printf '%s\n' "$root/dist/候场-macOS.zip" 
