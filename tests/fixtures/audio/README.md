# 转写演示录音与验收

`demo-meeting.webm` 是 203.625 秒的虚构工作站演示，由 macOS 自带普通话 Tingting、Meijia 两个声音交替朗读 [demo-script.txt](demo-script.txt)。六段分别用 `say -r 185` 合成，补 1.5 秒停顿，用 FFmpeg 转为单声道 16 kHz、24 kbit/s Opus WebM。分片测试运行时构造 20 MiB 边界 WAV，无需提交大文件。

## 内网服务

平台进程需要 FFmpeg 解码 WebM、M4A、OGG、MP3、FLAC 及非常规 WAV。16 kHz 单声道、16 位 PCM WAV 直接读取。内网模型进程另装 FunASR 和与本机匹配的 PyTorch、Torchaudio 及 ModelScope，例如本地验证使用的 FunASR 1.3.0。

以下变量由部署注入，尖括号内容是配置项说明。凭据由两个进程各自的环境注入。

| 环境变量 | 服务进程 | 平台进程 |
| --- | --- | --- |
| `JKQ_TRANSCRIBE_MODE` | | `local`（默认），可选 `mock` 或 `cloud` |
| `JKQ_TRANSCRIBE_LOCAL_URL` | | `<批准的内网 HTTPS 地址>/recognition`，本机可用回环 HTTP |
| `JKQ_TRANSCRIBE_LOCAL_API_KEY` | `<内网环境凭据>` | 同一凭据 |
| `JKQ_TRANSCRIBE_LOCAL_MODEL` | `paraformer-zh` 或对应的离线模型目录 | 同一值 |
| `JKQ_TRANSCRIBE_LOCAL_VAD_MODEL` | 例如 `fsmn-vad` | |
| `JKQ_TRANSCRIBE_LOCAL_PUNC_MODEL` | 例如 `ct-punc` | |
| `JKQ_TRANSCRIBE_LOCAL_SPK_MODEL` | 例如 `cam++` | |
| `JKQ_TRANSCRIBE_LOCAL_DEVICE` | 默认 `cpu`，按推理机器配置 | |
| `JKQ_TRANSCRIBE_HOTWORDS` | | 每行一条，追加到默认经开区词表 |
| `JKQ_TRANSCRIBE_TIMEOUT_SECONDS` | | 单次调用上限，默认 300 秒 |

本机启动和验证命令如下。内网生产部署可在 HTTPS 反向代理后运行同一工厂，模型先部署到离线模型目录。

```sh
PYTHONPATH=core/server:core/sdk:. python3 -m uvicorn \
  haiknow_core.aihub.transcribe_funasr:create_app --factory --host 127.0.0.1 --port 18735

PYTHONPATH=core/server:core/sdk:. HAIKNOW_NO_AUTOAPP=1 \
  python3 tests/fixtures/audio/smoke_local.py --compare-no-hotwords
```

FunASR 服务以 multipart `audio`、`model`、`hotword` 三字段接收已标准化的音频，返回每句的 `text`、片内毫秒 `start`/`end` 和局部说话人标识 `spk`。模型组合须支持时间戳、说话人和即时热词。官方原始 SenseVoice HTTP 示例返回全文，接入该场景需要提供相同的分句与说话人协议。

云端配置将来使用 `JKQ_TRANSCRIBE_MODE=cloud`、`JKQ_TRANSCRIBE_CLOUD_PROVIDER=<登记名>`、`JKQ_TRANSCRIBE_CLOUD_URL=<批准的 HTTPS 接口地址>`、`JKQ_TRANSCRIBE_CLOUD_MODEL=<模型>`、`JKQ_TRANSCRIBE_CLOUD_API_KEY=<环境注入凭据>`。当前包含 provider 注册接口。云端厂商待 Ben 决定后补一个 provider 实现。

## 会议长任务调用

`split_audio(audio_bytes)` 返回有序分片，每片的 `offset_frames`、`frames` 和 WAV 数据可独立保存。使用 `transcriber_from_environment(classification=...)` 创建适配器，实际转写逐片调用 `await transcriber.transcribe_chunk(chunk)`，然后调用 `transcriber.merge([(chunk, sentences), ...])`。如果 `source == 'preset'`，调用 `transcriber.preset_result(chunks)` 取演示结果。

结果字段为 `source`、`mock`、`durationMs`、`chunkCount`、`sentences[]`，每句带 `text`、`startMs`、`endMs`、`speaker`。预置结果的正文和时标属于演示录音，`chunkCount` 表示输入音频的分片数。片内说话人用匿名编号，重叠区出现可匹配句子时复用前片编号。少量无匹配边界可能给同一人分配新编号。
