# 📋 剪贴板朗读

macOS 菜单栏应用：复制文字后，点击菜单栏「朗读剪贴板」，通过 MiniMax 生成语音并自动播放。

## 功能

- 读取当前剪贴板文字
- 调用 MiniMax `t2a_v2` 生成 MP3
- 使用系统 `afplay` 自动播放
- 支持设置 MiniMax API Key、模型、Voice ID、语速、朗读模式
- 支持本地自动增强：发送前自动插入停顿和情绪标记，不需要额外模型 API
- 支持停止播放、开机自启、打开音频缓存和错误日志

## 朗读模式

菜单栏「设置」->「朗读模式」可切换：

- `原文朗读`：不改写剪贴板文字
- `自动增强`：根据文本内容自动选择语气并插入 MiniMax 标记
- `温柔`、`坚定`、`新闻播报`、`悬疑`：强制使用指定风格

如果原文已经包含 `<#0.5#>`、`(laughs)`、`(sighs)`、`(breath)` 等标记，应用会尊重原文，不重复增强。

## 运行

```bash
make install
make run
```

首次点击「朗读剪贴板」时会提示填写 MiniMax API Key。也可以提前设置环境变量：

```bash
export MINIMAX_API_KEY="你的 API Key"
make run
```

## 打包

```bash
make app
make dmg
```

## 文件位置

| 文件 | 作用 |
|------|------|
| `~/Library/Application Support/ClipboardReader/config.json` | 本地配置 |
| `~/Library/Application Support/ClipboardReader/Audio/` | 生成的 MP3 缓存 |
| `~/Library/Logs/ClipboardReader/error.log` | 错误日志 |

## 技术路线

`复制文字 -> 菜单栏「朗读剪贴板」-> MiniMax T2A HTTP API -> 写入 MP3 -> afplay 播放`
