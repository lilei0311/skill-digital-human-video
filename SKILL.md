---
name: digital-human-video
summary: 全自动 AI 数字人口播视频生产（MiniMax 声音复刻/TTS + HeyGen v3 数字人 + FFmpeg 字幕包装），支持 15 秒预览、状态恢复、发布素材。
description: Use this skill when the user requests AI digital human talking-head videos, voice cloning with consent, HeyGen avatar video generation, short-video scripts, subtitles, video packaging, or a repeatable topic-to-MP4 production pipeline. Works in Codex and Claude Code; prefer external executable tools over claiming model itself can edit video.
---

# Digital Human Video · Agent Skill

## 目标

接收一个主题或准备好的文案，产出一条竖屏 AI 数字人口播视频：`脚本 -> MiniMax TTS -> HeyGen 数字人口型 -> FFmpeg 加字幕、标题、AI 标识、可选画中画/BGM -> MP4 + 发布文案`。第一次只建立个人数字人 Look ID 和克隆声线 Voice ID，以后重复调用，不重复创建。提供 15 秒有成本的 HeyGen 预览；默认需要用户看过预览才生产完整版。经用户**明确选择**自动批准，才连跑两段。

## 安装和检查

- Skill 放到 `~/.codex/skills/digital-human-video` 或 `~/.claude/skills/digital-human-video`，确保 `SKILL.md` 在文件夹根目录。
- Python 3.10+、`pip install -r requirements.txt`、系统安装 `ffmpeg`/`ffprobe`（含 `libass` 和 H.264 encoder），中文字体可用时效果最佳。
- 复制 `.env.example` 为 `.env`，通过**本地**安全方式设置 Key；不要求用户把 Key、本人照片/声音贴在聊天中。永远不要把 `.env` 纳入 Git。
- 先运行：`python scripts/dhv.py doctor`，再 `python scripts/dhv.py run --topic '...' --out ./outputs/example --dry-run`。

## 操作流程（按顺序）

1. **确认许可和素材。** 仅接受本人或拥有充分授权的真人肖像/声音，禁止未经同意复刻、冒充或误导观众。对真人照片/视频及音频分别核查授权；AI 合成视频保留明确标识。音乐、画中画素材必须有许可。
2. **一次性建档。** 人声样本 30-60 秒干净录音最佳（MiniMax 官方接受 10 秒到 5 分钟，≤20MB，mp3/m4a/wav）。视频/照片在 HeyGen v3 上传建 Avatar；照片建议正面高清，视频训练可能涉及独立的真人 consent/verification，必须完成，且训练异步。用 `avatars` 查询已训练完成的 Look ID。提供 `MINIMAX_VOICE_ID`、`HEYGEN_AVATAR_ID` 给后续流水线。
3. **先写口播稿。** 用户没给正文则 LLM 自动写 3 秒钩子 → 2~3 个论点 → 总结，明确受众、平台和预计秒数。不能捏造不可验证数据。编排/剪辑创意可以由 Claude Opus 5.5 处理，也可由 Codex 处理；**模型负责脚本和调度，实际媒体处理由 FFmpeg 执行**。
4. **预览。** `run --mode preview`：优先复用 `state.json` 和 `script.txt`；对前约 55 字（近似 15 秒）合成音频、驱动数字人，产出 `preview_final.mp4`。不同语速时预览秒数不保证严格为 15。
5. **导演/剪辑方案。** 如当前 Agent 为 Claude Opus 5.5 或可以委派给 Opus，将 `script.txt`、主题、品牌和素材清单交给它，让它输出 `edit-plan.json`，严格符合 `examples/edit-plan.json` 的 JSON 键：`headline`、`brand`、`key_points[{text,start,end}]`、`pip_start/end`、`subtitle_font_size`、`music_volume`（0~0.3）。开始/结束时间必须在成片长度范围内。`--edit-plan` 让 FFmpeg 执行重点文字卡片动画/画中画时间轴、字幕样式和 BGM 音量；没有 Opus 时由 Codex/当前 Agent 生成同样 JSON。模型只负责决策，不假装自行渲染视频。
6. **审查并执行。** 用户检查口型、清晰度、版权、字幕、真实感。通过后 `run --mode full --approve`；已获授权且明确选择无人工审片时 `run --mode full --auto-approve` 自动生产两段。不要未经授权直接发到社交平台。
7. **校验交付。** 检查 `full_final.mp4` 时长、音画、字幕、标题遮挡、音乐音量、AI 合成标识，并交付 `publish.md`。对外发布前要求检查事实与平台 AIGC 规则。

## CLI 使用（在 Skill 根目录）

```bash
# 初始化：自己的肖像及音频，已知合法授权才允许使用 consent flag
python scripts/dhv.py avatar --file ./myself.mp4 --kind digital_twin --name 'My Presenter' --i-own-the-likeness
python scripts/dhv.py avatars  # 训练可能需要等待、补官方验证
python scripts/dhv.py clone --file ./myvoice.wav --voice-id MyBrandVoice2026 --i-own-the-voice

# 预览：默认由 MiniMax 文本模型写稿；也可传 --script-file bypass LLM
python scripts/dhv.py run --topic 'AI如何帮助企业减少重复流程' --out ./outputs/ai-workflow --mode preview --edit-plan ./examples/edit-plan.json

# 用户审查通过后才跑全片
python scripts/dhv.py run --topic 'AI如何帮助企业减少重复流程' --out ./outputs/ai-workflow --mode full --approve

# 明确同意无人值守时，一条命令预览 + 成片（API 视频调用按两段分别计费）
python scripts/dhv.py run --topic '一分钟讲明白数字人' --out ./outputs/demo --mode full --auto-approve

# 可选素材
python scripts/dhv.py run --script-file ./script.txt --out ./outputs/manual --mode preview --music ./licensed-bgm.mp3 --broll ./owned-broll.mp4
```

## Agent 的执行准则

- 不得将 `--dry-run`、单元测试通过描述为“HeyGen/MiniMax 真实跑通”。没有有效付费 Key 和授权素材只能验证离线渲染/请求格式。
- API 异步调用超时，应展示 `state.json` 中的 `video_id` 并复用，不要直接重建引发二次计费。
- 语音克隆需 MiniMax 实名认证，若 `voice_id` 7 天内未用于正式 TTS 可能失效；优先尝试现有音色，不静默重克隆。
- 平台字幕文件可能并非逐字精确；若未返回可用 SRT，工具会生成**估时字幕**并在 `state.json` 标注 `approximate`。交付前需复查，追求逐字精准建议额外接 ASR 对齐。
- 遇到视频大小/训练政策/认证/额度限制，应报告具体错误，而不是声称已经全自动完成。
- 不会自动登录或向抖音、快手、视频号、小红书、B站等直接发布，因为未接入各平台授权 API；只生成 `publish.md` 待审核发布。
- 避免把 API Key、录制原件、相似音色和原始生成资产提交公开代码库。

## 参照

- API 接口与地区配置详见 `references/api.md`。
- 交付与排错详见 `README.md`。
