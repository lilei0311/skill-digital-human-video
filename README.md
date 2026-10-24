# Digital Human Video Skill v0.2

**Codex / Claude Code 可安装的 `SKILL.md` + Python CLI**。

从「主题」自动生成口播文字，MiniMax 用克隆声线 TTS，HeyGen v3 生成头像口播视频，再用本地 FFmpeg 做 9:16 竖屏、AI 合成标识、中文字幕、片头顶栏、可选按时间出现的重点文字卡片、画中画与可调 BGM 混音。输出两种版本 `preview_final.mp4` 和 `full_final.mp4`，另带 `script.txt`、`publish.md`、`state.json`。

> 不是云端生产服务，也不是“无需 Key 免费生成”。首次需上传有授权的自拍照/本人视频和人声素材，并在 MiniMax/HeyGen 通过相关实名认证/肖像验证、具有 API 付费额度。实拍素材不要放在公开仓库。

## 安装

在 macOS/Windows 的终端：

```bash
python -m pip install -r requirements.txt
# macOS: brew install ffmpeg
# Windows PowerShell: winget install Gyan.FFmpeg
cp .env.example .env        # Windows cmd: copy .env.example .env
python scripts/dhv.py doctor
```

Agent 安装：将完整目录复制到 `~/.codex/skills/digital-human-video` 或 `~/.claude/skills/digital-human-video`（Windows 对应用户家目录），重启 Agent。然后对它说：

**“调用 digital-human-video skill，用我保存的声音和 HeyGen 数字人，制作一个《XXX》主题的 60 秒竖版口播。先生成 15 秒预览，字幕风格简洁，确认后生成完整 MP4。”**

脚本示例见 `SKILL.md`。

## Opus 5.5 / Codex 剪辑方案

让你的 Agent 先读取 `script.txt` 与 `examples/edit-plan.json`，为每条视频写出新的 `edit-plan.json`（严格 JSON）。传给生成命令：

```bash
python scripts/dhv.py run --topic 'AI如何改变企业培训' --out ./outputs/ai-training --mode preview --edit-plan ./examples/edit-plan.json
```

真实生产时务必修改样例中关键文字及开始/结束秒数。剪辑方案能控制标题栏、字幕字号、重点卡片、画中画起止时间、音乐音量；外部素材仍需用户提供已授权本地文件。**Opus/Agent 负责构思，FFmpeg 负责可靠渲染**。

## 状态和费用

- 首次建设形象 / 克隆声音：一次性；后续仅使用已有 ID。克隆音色若 7 天内没有用于正式 TTS，可能被平台清理。
- `preview` 实际上传并生成一小段数字人，发生付费或额度消耗；`full` 需要第二次生成。这才是真正的“先看预览再花钱制作完整版”，但会比只生成完整版多一次短片费用。
- `--auto-approve` 在用户主动允许下**一次执行两次视频 API 调用**，而不是免费在大视频内部做 15 秒预览。
- `state.json` 记住 LLM 文稿与 HeyGen 视频任务 ID，网络暂时超时后重复相同命令可续跑；更换主题/音色/头像时应换新 `--out` 文件夹。
- 30 分钟是一条合理的目标耗时，但受账号权限、模型排队、素材时长、网络和后期视频编码影响，不保证 SLA。

## 设计约束和当前边界

1. **AI 文稿**：默认读取 MiniMax Key，调用 MiniMax OpenAI-compatible Chat Completions；也可设置任意兼容供应商的 `LLM_API_URL/LLM_API_KEY/LLM_MODEL`；或以 `--script-file` 绕过自动写稿。
2. **数字人训练**：`avatar` 支持照片和 video digital twin 的 HeyGen v3 初始提交。训练异步，consent 验证也可能要求登录 HeyGen 官网完成，工具不规避平台认证；`avatars` 返回 Look ID。
3. **字幕**：优先采用 HeyGen `subtitle_url`；没有时按文稿字符数自动估时并写 SRT，属于**估时字幕**而非精准语音识别。正式商业交付请听看复核，未来可以接 ASR 对齐服务。
4. **剪辑**：本地 FFmpeg 合成标题条/AI 标识/视频层、可选 B-roll PiP (4-12s)、可选背景音乐和自动烧录字幕。不是智能自动寻找股票/新闻素材，也不允许未经确认联网抓取有版权的视频。
5. **发布**：准备发布文案和 MP4，但不擅自发布。实际跨平台自动发布需要每个平台受认可的官方授权接口和账户 OAuth；本包未接入。
6. **Opus 5.5**：如果你的 Agent 切到 Claude Opus 5.5，它可以优化脚本和 storyboard，实际画面合成仍靠 FFmpeg。并未集成模型计费或无脑循环剪辑。
7. **安全**：仅克隆有授权的真人形象和声线；AI 生成视频要显著标注，遵守各平台规则；不要在 output 中传播私密原件或 Token。

## 验收

- `python -m pytest -q` 离线验证 API payload、预览截断、时间轴与基本渲染。
- `python scripts/dhv.py run --topic '测试' --out ./outputs/dry --dry-run` 检查不发生扣费的配置预检。
- 实际通路需自备 Key、本人音视频素材及可用额度。**本包未用用户的私有 Key 发起真实调用**，所以不能将此交付等同于“真实生成成功”。

## 后续产品化建议

把一次性的头像/声音建档做成 UI 设置页，视频生产用队列/重试；以 `{topic, length, script, avatar, voice, style, project}` 为作业输入，采用 FFmpeg Worker。增加 ASR 精准字幕、镜头节奏规划和授权 B-roll 库，再考虑 OAuth 发布。留有 Stage 2 扩展空间。
