"""
setup.py - py2app 打包配置
用法: python3 setup.py py2app
"""

from setuptools import setup

from app_version import __version__


APP = ["clipboard_reader.py"]
DATA_FILES = []
VERSION = __version__
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "剪贴板朗读",
        "CFBundleDisplayName": "📋 剪贴板朗读",
        "CFBundleIdentifier": "com.clipboardreader.app",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleExecutable": "clipboard_reader",
        "CFBundleDevelopmentRegion": "zh_CN",
        "NSHumanReadableCopyright": "Copyright © 2026. All rights reserved.",
        "LSUIElement": True,
        "NSAppleEventsUsageDescription": "用于读取剪贴板文字并朗读。",
        "NSServices": [
            {
                "NSMenuItem": {
                    "default": "朗读所选文本",
                },
                "NSMessage": "readSelection",
                "NSPortName": "剪贴板朗读",
                "NSSendTypes": ["NSStringPboardType"],
                "NSReturnTypes": [],
            },
        ],
    },
    "packages": ["rumps"],
    "includes": ["ctypes", "AppKit", "Foundation", "objc"],
    "dylib_excludes": [],
}

setup(
    version=VERSION,
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
