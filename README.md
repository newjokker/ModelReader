# 📋 剪贴板朗读

macOS 菜单栏应用：复制文字后，点击菜单栏「朗读剪贴板」，通过 MiniMax 生成语音并自动播放。

## 功能

- 读取当前剪贴板文字
- 调用 MiniMax `t2a_v2` 生成 MP3
- 使用系统 `afplay` 自动播放
- 支持设置 MiniMax API Key、模型、Voice ID、语速
- 支持停止播放、开机自启、打开音频缓存和错误日志

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
