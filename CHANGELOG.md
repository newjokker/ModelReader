# Changelog

## 0.1.12 - 2026-06-17

- 语气模型改为逐句给出 `speed` 和 `pitch` 建议，并在朗读记录中保存到每句话条目里。
- 实际 TTS 请求会把逐句建议汇总为整段 `speed` 和 `pitch`；`volume` 保持用户设置，不再由 AI 调整。

## 0.1.11 - 2026-06-17

- 语气模型现在会同时建议本次朗读的语速、音量和音调，并应用到实际 MiniMax TTS payload。
- AI 建议的声音参数会经过范围清洗，只影响本次朗读，不覆盖用户保存的默认设置。
- 朗读记录的 `enhancement.voice_adjustments` 会保存本次 AI 声音参数调整，方便复现。

## 0.1.10 - 2026-06-17

- 将语气模型默认接口改为 DeepSeek Chat Completions：`https://api.deepseek.com/chat/completions`。
- 将语气模型默认模型改为 `deepseek-v4-flash`，并支持通过 `DEEPSEEK_API_KEY` 读取 API Key。

## 0.1.9 - 2026-06-17

- 自动增强支持调用 OpenAI-compatible 语言模型逐句判断朗读语气，未配置或调用失败时自动回退本地规则。
- 设置菜单新增「语气模型」，可配置 API Key、模型名和 `/chat/completions` 接口地址。
- 朗读记录新增 `enhancement` 元数据，保存语气来源、语气模型信息和每句话的语气标注，不保存语气模型 API Key。

## 0.1.8 - 2026-06-17

- 自动增强改为逐句判断语气，同一段文字里可以分别识别温柔、悬疑、悲伤、新闻和坚定语气。
- 每句会按识别结果插入更合适的 MiniMax 停顿和情绪标记，例如 `(breath)`、`(gasps)`、`(sighs)`、`(laughs)`。

## 0.1.7 - 2026-06-17

- 将后台线程中的状态栏、通知、弹窗和菜单恢复操作派发到主线程，降低 macOS UI 偶发异常风险。
- 朗读失败时也会回写 `Records/<cache_id>.json`，记录失败状态、时间、错误类型和错误信息。
- 增加配置清洗：语速、音量、音调、模型、`voice_id` 和朗读模式都会在读取和构建 payload 时规范化。
- 去除记录文件中的重复 `texts.tts_text` 字段，保留完整 TTS payload 作为复现依据。
- 精简 py2app 打包排除项，减少测试/开发模块进入发布包；`build_dmg.sh` 支持 `PYTHON=...` 覆盖默认解释器。

## 0.1.6 - 2026-06-17

- 将原始文字、增强文本和可复现声音的生成参数合并到单个 `Records/<cache_id>.json` 文件。
- 记录文件包含模型、`voice_id`、语速、音量、音调、朗读模式和实际 TTS payload，方便之后复现同样的声音。
- 记录 MiniMax 返回的非音频元数据和音频缓存路径，不保存 API Key，也不保存返回中的音频 hex。

## 0.1.5 - 2026-06-17

- 新增三层缓存：原始文字、增强文本、音频缓存会使用同一个缓存 ID 保存，方便对应排查。
- 菜单项从「打开音频缓存」调整为「打开缓存目录」，可直接查看所有缓存子目录。
- 打包脚本继续使用 miniforge Python，并补齐 py2app 运行所需的 conda 动态库后重新签名。

## 0.1.4 - 2026-06-17

- 切换 DMG 构建环境到 `/Users/jokkerling/miniforge3/bin/python`。
