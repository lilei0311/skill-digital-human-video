# Official API references (checked 2026-10-24)

- MiniMax voice clone: `POST /v1/files/upload`, form `purpose=voice_clone` + audio file, then `POST /v1/voice_clone` with integer `file_id` and unique `voice_id`. Voice clone requires verified identity. Source: https://platform.minimax.cn/docs/api-reference/voice-cloning-uploadcloneaudio and https://platform.minimax.cn/docs/api-reference/voice-cloning-clone
- MiniMax TTS: `POST /v1/t2a_v2` with `model` (`speech-2.8-turbo` supported), `text`, `stream:false`, `voice_setting.voice_id`, `audio_setting`; response `data.audio` is hex, not base64. Source: https://platform.minimax.cn/docs/api-reference/speech-t2a-http
- MiniMax API domains: China `https://api.minimax.cn`; overseas some accounts use `https://api.minimax.io`; choose the one provisioned for your account, keys/quotas are not interchangeable.
- HeyGen asset upload: `POST https://api.heygen.com/v3/assets`, multipart file; `data.asset_id`; max 50MB simple upload (image max 32MB). Source: https://developers.heygen.com/reference/upload-asset
- HeyGen avatar creation: `POST /v3/avatars`, `type=photo` or `digital_twin`, `name`, `file={type:'asset_id',asset_id:...}`; asynchronous training plus consent/verification where required. Source: https://developers.heygen.com/reference/create-avatar and https://github.com/heygen-com/skills/blob/master/heygen-avatar/references/avatar-creation.md
- HeyGen looks: `GET /v3/avatars/looks`; use `data[].id` of a completed look as avatar ID. Source: https://developers.heygen.com/reference/list-avatar-looks
- HeyGen avatar video: `POST /v3/videos`, with `type=avatar,avatar_id,aspect_ratio,audio_asset_id`. `audio_asset_id` and `script` are mutually exclusive; our approach deliberately uses MiniMax externally-generated audio. `Idempotency-Key` for safe retry. Source: https://developers.heygen.com/reference/create-video
- HeyGen video status: `GET /v3/videos/{video_id}`; `data.status`, `data.video_url`, sometimes `subtitle_url`; rendering asynchronous. Source: https://developers.heygen.com/reference/get-video
- Claude Opus 5.5 is an agent/coding model (not a standalone audio/video editing binary). Source: https://www.anthropic.com/news/models

API versions and plans change. If a user account returns 400/403, inspect current official schema and plan limits before changing code.
