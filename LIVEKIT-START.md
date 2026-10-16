# LiveKit 版：iPhone → Photon → LiveKit → 本地字幕

这个版本替代 Twilio 接入，不需要 Twilio、ngrok、云端付费转写或电脑麦克风。
LiveKit 免费 Build 和 Photon beta 额度仍需在各自控制台确认；不要启用付费升级或自动充值。
手机拨号使用你现有的运营商套餐，可能受套餐通话费用约束。

## 1. 安装

Terminal 中进入 phone-demo 文件夹，建议使用 Python 3.11 或 3.12（若系统 3.13 安装成功也可）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-livekit.txt
```

首次安装需要联网下载依赖。首次启动还会从 Hugging Face 下载免费 Whisper tiny.en 模型。
不需要 OpenAI、Deepgram 或其他付费模型 key。tiny.en 用 CPU/int8，延迟需在你的 Mac 上实测。

## 2. 配置

如果已有 .env，先保存原配置，再用 livekit.env.example 的字段配置 .env。
若此前没创建 .env：

```bash
cp livekit.env.example .env
open -e .env
```

填入 LiveKit → Settings → API keys 获取的 LIVEKIT_API_KEY / LIVEKIT_API_SECRET。
保持以下值：

```dotenv
LIVEKIT_URL=wss://YOUR_PROJECT.livekit.cloud
LIVEKIT_ROOM=photon-demo
```

设置自己的 DEMO_PASSWORD。真实密钥只留在 .env，不上传、不截图、不发聊天。

## 3. 运行

先停止旧的 server.py（原 Terminal 按 Ctrl+C），再运行：

```bash
source .venv/bin/activate
python3 livekit_demo.py
```

打开 http://localhost:8765，用户名 demo，密码为 .env 的 DEMO_PASSWORD。
等待 Terminal 出现 `Connected to room photon-demo`。
然后用 iPhone 拨打 Photon 号码，在电话中说英文，例如：

“That seems a little expensive.”

句末停顿约一秒。字幕按短句/最长约五秒音频块生成，不是逐词流式。
短句之间可能产生切分；本地模型推理还会增加延迟。不要点击 Run text simulation 来测试电话。
只有实际转写出文字才会显示 LIVE PHONE；收到音轨/音频帧的状态另有显示。
程序订阅远端音轨，并发布生成的短提示音及静音完成接听；不采集电脑麦克风，不生成语音回复。

## 4. 成功标准

1. Connected to room：本地程序成功进入房间。
2. Telephone audio track subscribed：订阅到电话音轨。
3. Audio frames received：实际收到网络音频帧。
4. 页面出现 Caller … 和你在 iPhone 中说的原话：单人真实电话转写通过。

此版本是一个来电者的转写测试，不是两部电话桥接。不会自动拨回你的手机。
两人对话需要让销售和客户分别加入房间，再分别转写音轨。不要把这个单人验证称为完整双人 Sales Agent。

## 5. 排查

- 一直响铃、没有音轨：保持本地程序在线后重新拨号；检查 Photon 呼叫详情和 LiveKit Events。
- 认证失败：API key/secret 必须属于此 LiveKit 项目；不能填 SIP 用户名密码。
- Connected 但不订阅：确认 dispatch rule 的固定房间恰好是 photon-demo。
- 有音频帧但安静：先确认手机通话计时开始，并且没静音；看 remote audio level。
- 安装报错：保留报错文字，用 Python 3.11/3.12 重建 venv 再试；不要修改系统 Python。
- 转写慢：默认 tiny.en 已是较小英文模型；不要先换大模型。队列超限会明确显示丢块。
- 本地模型载入失败：检查网络能访问 Hugging Face，或将 WHISPER_MODEL 设置为已下载的本地模型目录。

历史存于内存，重启清空；导出为 final transcript JSON。未将电话音频保存为录音文件。
每次用完按 Ctrl+C，断开本地接收器。测试参与者需事先同意转写。

## 当前验证范围

代码参考 LiveKit 官方 Python RTC AudioStream / track_subscribed / token grants API。
离线单元测试可检查已有服务器逻辑；原始测试者已在 Mac 上手动验证真实电话音频和字幕。更换设备或账户后仍需实测；自动化测试不验证语音准确率。

https://docs.livekit.io/transport/media/raw-tracks/
https://docs.livekit.io/frontends/reference/tokens-grants/
https://github.com/SYSTRAN/faster-whisper
