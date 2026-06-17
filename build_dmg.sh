#!/bin/bash
# build_dmg.sh — 构建剪贴板朗读 DMG 并移动到 releases 目录
# 用法: ./build_dmg.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# PYTHON="/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python"
PYTHON="/Users/jokkerling/miniforge3/bin/python"
APP_NAME="剪贴板朗读"
export COPYFILE_DISABLE=1

VERSION=$(grep '__version__' "$SCRIPT_DIR/app_version.py" | head -1 | sed 's/.*= "//;s/".*//')
DMG_NAME="ClipboardReader-v${VERSION}.dmg"

echo "📦 构建 $APP_NAME v$VERSION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

ARCH=$($PYTHON -c 'import platform; print(platform.machine())')
if [ "$ARCH" != "arm64" ]; then
    echo "❌ Python 架构为 $ARCH，必须是 arm64"
    exit 1
fi
echo "✅ Python 架构: $ARCH"
PY_PREFIX=$($PYTHON -c 'import sys; print(sys.prefix)')
echo "🐍 Python 环境: $PY_PREFIX"

BUILD_DIR=$(mktemp -d "/tmp/clipboard_reader_build_XXXXXX")
echo "📂 构建目录: $BUILD_DIR"

cleanup() {
    echo "🧹 清理临时目录..."
    rm -rf "$BUILD_DIR"
    hdiutil detach /tmp/clipboard_reader_mount -force 2>/dev/null || true
    rm -f /tmp/clipboard_reader_template.dmg
}
trap cleanup EXIT

echo "📋 复制项目文件..."
cp "$SCRIPT_DIR/clipboard_reader.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/app_version.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/setup.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/pyproject.toml" "$BUILD_DIR/"
cp "$SCRIPT_DIR/README.md" "$BUILD_DIR/"
cp "$SCRIPT_DIR/icon.icns" "$BUILD_DIR/"

cd "$BUILD_DIR"

echo "🔨 构建 .app（py2app）..."
$PYTHON setup.py py2app 2>&1 | tee "$BUILD_DIR/py2app.log"

if [ ! -d "$BUILD_DIR/dist/$APP_NAME.app" ]; then
    echo "❌ .app 构建失败"
    echo "   期望路径: $BUILD_DIR/dist/$APP_NAME.app"
    echo "   实际 dist 内容:"
    find "$BUILD_DIR/dist" -maxdepth 1 -mindepth 1 -print 2>/dev/null || true
    echo "   py2app 日志: $BUILD_DIR/py2app.log"
    exit 1
fi
echo "✅ .app 构建成功"

APP_PATH="$BUILD_DIR/dist/$APP_NAME.app"

echo "🔧 修复 py2app 动态库和签名..."
FRAMEWORKS_DIR="$APP_PATH/Contents/Frameworks"
mkdir -p "$FRAMEWORKS_DIR"
DYLIB_LIST="$BUILD_DIR/rpath_dylibs.txt"

(
find "$APP_PATH" -type f ! -name '._*' -print0 |
    xargs -0 file |
    awk -F: '/Mach-O/ {print $1}' |
    while IFS= read -r binary; do
        otool -L "$binary" 2>/dev/null |
            awk '/@rpath\// {sub(/^.*@rpath\//, ""); print $1}'
    done
) | sort -u > "$DYLIB_LIST" || true

while IFS= read -r dylib; do
    SRC="$PY_PREFIX/lib/$dylib"
    if [ -e "$SRC" ] && [ ! -e "$FRAMEWORKS_DIR/$dylib" ]; then
        echo "   加入动态库: $dylib"
        cp -L "$SRC" "$FRAMEWORKS_DIR/$dylib"
    fi
done < "$DYLIB_LIST"

find "$APP_PATH" \( -name '._*' -o -name '.DS_Store' \) -delete
xattr -cr "$APP_PATH"
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
echo "✅ .app 签名验证通过"

echo "💿 创建 DMG..."
rm -f /tmp/clipboard_reader_template.dmg
hdiutil create -size 200m -fs HFS+ -type UDIF -volname "$APP_NAME" /tmp/clipboard_reader_template.dmg
hdiutil attach -nobrowse -mountpoint /tmp/clipboard_reader_mount /tmp/clipboard_reader_template.dmg

echo "📦 打包 .app 到 DMG..."
ditto --noextattr --norsrc "$APP_PATH" "/tmp/clipboard_reader_mount/$APP_NAME.app"
ln -sf /Applications "/tmp/clipboard_reader_mount/Applications"
cp "$BUILD_DIR/icon.icns" "/tmp/clipboard_reader_mount/.VolumeIcon.icns" 2>/dev/null || true
/usr/bin/SetFile -a C "/tmp/clipboard_reader_mount"

hdiutil detach /tmp/clipboard_reader_mount
echo "🗜️  压缩 DMG..."
hdiutil convert /tmp/clipboard_reader_template.dmg -format UDZO -ov -o "$BUILD_DIR/$APP_NAME.dmg"
rm -f /tmp/clipboard_reader_template.dmg

DMG_SIZE=$(du -h "$BUILD_DIR/$APP_NAME.dmg" | cut -f1)
echo "✅ DMG 生成成功 ($DMG_SIZE)"

mkdir -p "$SCRIPT_DIR/releases"
TARGET="$SCRIPT_DIR/releases/$DMG_NAME"

if [ -f "$TARGET" ]; then
    echo "⚠️  $DMG_NAME 已存在，覆盖..."
    rm -f "$TARGET"
fi

cp "$BUILD_DIR/$APP_NAME.dmg" "$TARGET"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 完成！DMG 已保存到: releases/$DMG_NAME"
echo ""
echo "📁 releases 目录内容："
ls -lh "$SCRIPT_DIR/releases/"
