# Podcast Digest — 小宇宙播客总结工具

一键爬取小宇宙播客，转录音频为文字，自动提炼重点并生成多篇归纳报告。

## 功能特性

- 🕷️ **爬取小宇宙播客** — 输入节目链接，自动获取单集信息、音频URL、shownotes
- 🎙️ **语音转文字** — 使用 faster-whisper（本地免费）转录播客音频
- 📝 **重点提炼** — 自动提取时间轴、关键要点、话题标签
- 📊 **多篇归纳** — 跨集总结，发现共同主题和洞察
- 📄 **双格式输出** — 同时生成 Markdown 和精美 HTML 报告

## 安装依赖

```bash
# Python 依赖
pip3 install -r requirements.txt

# 安装 Playwright 浏览器
python3 -m playwright install chromium

# 安装 ffmpeg（音频处理，如未安装）
brew install ffmpeg
```

## 使用方法

### 总结单集播客

```bash
python3 main.py episode https://www.xiaoyuzhoufm.com/episode/6a0c256be1eb34a939b0cb35
```

### 总结播客节目的最近 N 集

```bash
# 最近5集
python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/5e4ee557418a84a0466737b7

# 最近10集
python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/5e4ee557418a84a0466737b7 --max-episodes 10
```

### 跳过转录（更快，仅基于 shownotes）

```bash
python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/5e4ee557418a84a0466737b7 --no-transcribe
```

### 指定 Whisper 模型

```bash
# 更快但不够准确
python3 main.py episode <URL> --whisper-model tiny

# 更准确但更慢
python3 main.py episode <URL> --whisper-model medium
```

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--max-episodes` | 最多处理几集 | 5 |
| `--whisper-model` | Whisper 模型大小 (tiny/base/small/medium/large-v3) | small |
| `--no-transcribe` | 跳过语音转录，仅基于 shownotes | false |
| `--keep-audio` | 保留下载的音频文件 | false |
| `-o, --output` | 输出目录 | ./output |

## 输出文件

运行后在输出目录生成：

```
output/
├── 忽左忽右_播客总结.md    # Markdown 报告
├── 忽左忽右_播客总结.html   # HTML 报告（精美可视化）
├── metadata.json            # 完整元数据
├── audio/                   # 下载的音频文件
│   └── xxx.m4a
└── transcripts/             # 转录结果
    ├── xxx.txt              # 纯文本
    ├── xxx.srt              # 字幕文件
    └── xxx.json             # 带时间戳的JSON
```

## 工作流程

```
小宇宙URL → Playwright渲染 → __NEXT_DATA__提取 → 音频下载
                                                    ↓
HTML/MD报告 ← 总结/归纳 ← Whisper转录 ← ffmpeg处理
```

## 注意事项

- 本工具仅爬取公开免费的播客内容，不绕过付费限制
- 建议添加适当延迟，不要频繁请求，避免对小宇宙服务器造成压力
- Whisper 转录需要较多计算资源，建议使用 `small` 或 `medium` 模型
- 首次使用时会自动下载 Whisper 模型（约 500MB-2GB）
