# 📋 剪贴板朗读

macOS 菜单栏应用：复制文字后，点击菜单栏「朗读剪贴板」，通过 MiniMax 生成语音并自动播放。

## 功能

- 读取当前剪贴板文字
- 调用 MiniMax `t2a_v2` 生成 MP3
- 使用系统 `afplay` 自动播放
- 支持设置 MiniMax API Key、模型、声音下拉选择、语速、朗读模式
- 支持自动增强：可用语言模型按句子判断语气、语速和音调；未配置语气模型时自动使用本地规则
- 支持停止播放、开机自启、打开缓存目录和错误日志
- 每次朗读会保存一份 JSON 记录和一份音频缓存，文件名一一对应

## 朗读模式

菜单栏「设置」->「朗读模式」可切换：

- `原文朗读`：不改写剪贴板文字
- `自动增强`：优先使用语气模型判断每句话的朗读语气、语速和音调，并插入 MiniMax 停顿和情绪标记；语气模型不可用时回退本地规则
- `温柔`、`坚定`、`新闻播报`、`悬疑`：强制使用指定风格

如果原文已经包含 `<#0.5#>`、`(laughs)`、`(sighs)`、`(breath)` 等标记，应用会尊重原文，不重复增强。

## 语气模型

菜单栏「设置」->「语气模型」可配置用于判断句子语气的 OpenAI-compatible Chat Completions 接口：

- `设置 API Key`：保存语气模型 API Key；也支持环境变量 `TONE_LLM_API_KEY`、`DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`
- `设置模型`：默认 `deepseek-v4-flash`
- `设置接口地址`：默认 `https://api.deepseek.com/chat/completions`

语气模型会结合整段上下文，给每句话标注 `plain`、`gentle`、`suspense`、`sad`、`news`、`energetic` 这几类语气，并给每句话建议 `speed` 和 `pitch`。它不改写原文；朗读记录里会保存语气来源、模型名、每句语气和每句声音参数建议，不保存语气模型 API Key。

MiniMax 当前请求的语速和音调是整段级别参数，所以应用会把每句话的 `speed` 和 `pitch` 建议汇总成一次实际 TTS 参数。音量始终使用菜单里保存的用户设置，不由语气模型决定。

## 声音选择

菜单栏「设置」->「声音 Voice ID」可直接选择常用 MiniMax 声音，例如青涩男声、精英男声、少女女声、新闻播音员等。

如果需要使用 MiniMax 控制台里的其他 `voice_id`，选择「自定义 Voice ID…」手动填入即可。

## 右键朗读所选文本

打包后的 App 会注册 macOS 服务「朗读所选文本」。安装并启动 App 后，可在支持 Services 的文本区域中：

1. 选中一段文字
2. 右击
3. 选择「服务」->「朗读所选文本」

如果菜单里暂时看不到该服务，先启动一次「剪贴板朗读」，或到「系统设置」->「键盘」->「键盘快捷键」->「服务」里确认「朗读所选文本」已启用。

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
| `~/Library/Application Support/ClipboardReader/Records/` | 朗读记录 JSON：包含原始文字、增强文本、语气标注、模型、voice_id、语速、音量、音调等复现参数 |
| `~/Library/Application Support/ClipboardReader/Audio/` | 生成的 MP3 音频缓存 |
| `~/Library/Logs/ClipboardReader/error.log` | 错误日志 |

## 技术路线

`复制文字 -> 菜单栏「朗读剪贴板」-> MiniMax T2A HTTP API -> 写入 MP3 -> afplay 播放`
