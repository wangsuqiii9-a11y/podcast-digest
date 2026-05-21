"""
语音转文字模块
使用 faster-whisper 将播客音频转录为文字
"""

import os
import json
from typing import Optional
from faster_whisper import WhisperModel


class Transcriber:
    """播客音频转录器"""

    # 可用模型: tiny, base, small, medium, large-v2, large-v3
    MODEL_SIZES = {
        "tiny": "最快，准确率最低",
        "base": "较快，准确率一般",
        "small": "平衡，推荐日常使用",
        "medium": "较慢，准确率较高",
        "large-v3": "最慢，准确率最高",
    }

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
    ):
        """初始化转录器

        Args:
            model_size: 模型大小，默认 small
            device: 计算设备，auto/cpu/cuda
            compute_type: 计算精度，auto/int8/float16
        """
        self.model_size = model_size

        if device == "auto":
            device = "cpu"  # macOS 默认用 CPU (faster-whisper 的 CUDA 不支持 macOS)
        if compute_type == "auto":
            compute_type = "int8" if device == "cpu" else "float16"

        print(f"加载 Whisper 模型: {model_size} (device={device}, compute_type={compute_type})")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print("模型加载完成")

    def transcribe(
        self,
        audio_path: str,
        language: str = "zh",
        output_dir: Optional[str] = None,
        with_timestamps: bool = True,
    ) -> dict:
        """转录音频文件

        Args:
            audio_path: 音频文件路径
            language: 语言，默认中文
            output_dir: 输出目录（保存转录结果）
            with_timestamps: 是否包含时间戳

        Returns:
            dict: 转录结果，包含 text, segments, language
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        print(f"开始转录: {os.path.basename(audio_path)}")

        segments_iter, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        segments = []
        full_text_parts = []

        for segment in segments_iter:
            seg = {
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip(),
            }
            segments.append(seg)
            full_text_parts.append(seg["text"])

        full_text = " ".join(full_text_parts)

        result = {
            "text": full_text,
            "segments": segments if with_timestamps else [],
            "language": info.language,
            "language_probability": round(info.language_probability, 4),
            "duration": round(info.duration, 2),
        }

        # 保存结果
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(audio_path))[0]

            # 保存纯文本
            txt_path = os.path.join(output_dir, f"{base_name}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(full_text)

            # 保存带时间戳的文本
            if with_timestamps:
                srt_path = os.path.join(output_dir, f"{base_name}.srt")
                self._write_srt(segments, srt_path)

            # 保存JSON
            json_path = os.path.join(output_dir, f"{base_name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"转录结果已保存: {output_dir}")

        return result

    def _write_srt(self, segments: list, path: str):
        """写入SRT字幕文件"""
        with open(path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = self._format_srt_time(seg["start"])
                end = self._format_srt_time(seg["end"])
                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{seg['text']}\n\n")

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """将秒数格式化为SRT时间格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def transcribe_if_needed(
        self, audio_path: str, transcript_dir: str, **kwargs
    ) -> dict:
        """如果已有转录结果则直接读取，否则执行转录"""
        base_name = os.path.splitext(os.path.basename(audio_path))[0]
        json_path = os.path.join(transcript_dir, f"{base_name}.json")

        if os.path.exists(json_path):
            print(f"转录结果已存在，直接读取: {json_path}")
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)

        return self.transcribe(audio_path, output_dir=transcript_dir, **kwargs)
