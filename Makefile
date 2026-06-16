SHELL   := /bin/bash
PYTHON  ?= python3
NAME    := 剪贴板朗读
VERSION := $(shell grep '__version__' app_version.py | head -1 | sed "s/.*= \"//;s/\".*//")
.DEFAULT_GOAL := help

.PHONY: help install run app dmg clean test

help: ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖
	$(PYTHON) -m pip install rumps py2app

run: ## 开发模式运行菜单栏应用
	$(PYTHON) clipboard_reader.py

test: ## 运行单元测试
	$(PYTHON) -m unittest discover -s tests

app: clean ## 构建 .app
	$(PYTHON) setup.py py2app
	@echo "✅ 构建完成: dist/$(NAME).app"

dmg: app ## 构建 DMG 安装包
	@echo "创建 DMG..."
	hdiutil create -size 120m -fs HFS+ -type UDIF -volname "$(NAME)" /tmp/clipboard_reader_template.dmg
	hdiutil attach -nobrowse -mountpoint /tmp/clipboard_reader_mount /tmp/clipboard_reader_template.dmg
	ditto "dist/$(NAME).app" "/tmp/clipboard_reader_mount/$(NAME).app"
	ln -sf /Applications "/tmp/clipboard_reader_mount/Applications"
	hdiutil detach "/tmp/clipboard_reader_mount"
	rm -rf /tmp/clipboard_reader_mount
	hdiutil convert /tmp/clipboard_reader_template.dmg -format UDZO -ov -o "$(NAME).dmg"
	rm -f /tmp/clipboard_reader_template.dmg
	@mkdir -p releases
	@mv "$(NAME).dmg" "releases/ClipboardReader-v$(VERSION).dmg"
	@echo "✅ 已生成: releases/ClipboardReader-v$(VERSION).dmg"

clean: ## 清理构建产物
	rm -rf build dist *.egg-info __pycache__ tests/__pycache__
	@echo "✅ 清理完成"
