#!/bin/bash
# build_dmg.sh — 构建 Todo 提醒器 DMG 并移动到 releases 目录
# 用法: ./build_dmg.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python"
APP_NAME="Todo提醒器"

VERSION=$(grep '__version__' "$SCRIPT_DIR/app_version.py" | head -1 | sed 's/.*= "//;s/".*//')
DMG_NAME="TodoReminder-v${VERSION}.dmg"

echo "📦 构建 $APP_NAME v$VERSION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

ARCH=$($PYTHON -c 'import platform; print(platform.machine())')
if [ "$ARCH" != "arm64" ]; then
    echo "❌ Python 架构为 $ARCH，必须是 arm64"
    exit 1
fi
echo "✅ Python 架构: $ARCH"

BUILD_DIR=$(mktemp -d "/tmp/todoreminder_build_XXXXXX")
echo "📂 构建目录: $BUILD_DIR"

cleanup() {
    echo "🧹 清理临时目录..."
    rm -rf "$BUILD_DIR"
    hdiutil detach /tmp/todoreminder_mount -force 2>/dev/null || true
    rm -f /tmp/todoreminder_template.dmg
}
trap cleanup EXIT

echo "📋 复制项目文件..."
cp "$SCRIPT_DIR/todo_reminder.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/app_version.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/setup.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/pyproject.toml" "$BUILD_DIR/"
cp "$SCRIPT_DIR/icon.icns" "$BUILD_DIR/"

cd "$BUILD_DIR"

echo "🔨 构建 .app（py2app）..."
$PYTHON setup.py py2app 2>&1 | tail -5

if [ ! -d "$BUILD_DIR/dist/$APP_NAME.app" ]; then
    echo "❌ .app 构建失败"
    exit 1
fi
echo "✅ .app 构建成功"

echo "💿 创建 DMG..."
hdiutil create -size 200m -fs HFS+ -type UDIF -volname "$APP_NAME" /tmp/todoreminder_template.dmg
hdiutil attach -nobrowse -mountpoint /tmp/todoreminder_mount /tmp/todoreminder_template.dmg

echo "📦 打包 .app 到 DMG..."
ditto "$BUILD_DIR/dist/$APP_NAME.app" "/tmp/todoreminder_mount/$APP_NAME.app"
ln -sf /Applications "/tmp/todoreminder_mount/Applications"
cp "$BUILD_DIR/icon.icns" "/tmp/todoreminder_mount/.VolumeIcon.icns" 2>/dev/null || true
/usr/bin/SetFile -a C "/tmp/todoreminder_mount"

hdiutil detach /tmp/todoreminder_mount
echo "🗜️  压缩 DMG..."
hdiutil convert /tmp/todoreminder_template.dmg -format UDZO -ov -o "$BUILD_DIR/$APP_NAME.dmg"
rm -f /tmp/todoreminder_template.dmg

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
