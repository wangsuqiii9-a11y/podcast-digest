#!/usr/bin/env python3
"""
Podcast Digest — 小宇宙播客总结工具

功能：爬取小宇宙播客音频 → 语音转文字 → 重点提炼 + 多篇归纳 → Markdown/HTML 报告

使用方式：
  # 总结单集播客
  python3 main.py episode https://www.xiaoyuzhoufm.com/episode/xxx

  # 总结播客节目的最近 N 集
  python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/xxx --max-episodes 5

  # 跳过转录（仅基于 shownotes 生成总结）
  python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/xxx --no-transcribe

  # 指定 Whisper 模型大小
  python3 main.py episode https://www.xiaoyuzhoufm.com/episode/xxx --whisper-model small
"""

import argparse
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper import XiaoyuzhouScraper, download_audio
from transcriber import Transcriber
from summarizer import PodcastSummarizer
from report_generator import ReportGenerator


DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


async def process_episode(
    episode: dict,
    transcriber: Transcriber,
    audio_dir: str,
    transcript_dir: str,
    skip_transcribe: bool = False,
) -> dict:
    """处理单集：下载音频 → 转录 → 返回转录结果"""

    eid = episode.get("eid", "unknown")
    audio_url = episode.get("audio_url", "")

    # 如果跳过转录，返回空转录
    if skip_transcribe or not audio_url:
        return {"text": "", "segments": [], "language": "zh", "duration": 0}

    # 下载音频
    audio_filename = f"{eid}.m4a"
    audio_path = os.path.join(audio_dir, audio_filename)

    try:
        await download_audio(audio_url, audio_path)
    except Exception as e:
        print(f"  下载音频失败: {e}")
        return {"text": "", "segments": [], "language": "zh", "duration": 0}

    # 转录音频
    try:
        os.makedirs(transcript_dir, exist_ok=True)
        result = transcriber.transcribe_if_needed(audio_path, transcript_dir)
        return result
    except Exception as e:
        print(f"  转录失败: {e}")
        return {"text": "", "segments": [], "language": "zh", "duration": 0}


async def run_episode(
    url_or_id: str,
    output_dir: str,
    whisper_model: str = "small",
    skip_transcribe: bool = False,
    keep_audio: bool = False,
):
    """处理单集播客"""
    scraper = XiaoyuzhouScraper(headless=True)

    try:
        # 获取单集信息
        print(f"\n📡 获取单集信息...")
        episode = await scraper.get_episode(url_or_id)
        print(f"  标题: {episode['title']}")
        print(f"  时长: {episode['duration_minutes']:.0f} 分钟")
        print(f"  音频: {episode['audio_url'][:80]}...")

        # 初始化转录器
        audio_dir = os.path.join(output_dir, "audio")
        transcript_dir = os.path.join(output_dir, "transcripts")

        if not skip_transcribe:
            transcriber = Transcriber(model_size=whisper_model)
        else:
            transcriber = None
            print("\n⏭️ 跳过转录，仅基于 shownotes 生成总结")

        # 处理
        transcript = {"text": "", "segments": [], "language": "zh", "duration": 0}
        if transcriber:
            transcript = await process_episode(
                episode, transcriber, audio_dir, transcript_dir, skip_transcribe
            )

        # 总结
        print("\n📊 生成总结...")
        summarizer = PodcastSummarizer()
        summary = summarizer.summarize_episode(episode, transcript)

        # 生成报告
        multi_data = summarizer.summarize_multiple([summary])
        reporter = ReportGenerator(output_dir)
        md_path = reporter.generate_markdown(multi_data)
        html_path = reporter.generate_html(multi_data, md_path)

        # 保存元数据
        meta_path = os.path.join(output_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {"episode": episode, "transcript": transcript, "summary": summary},
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(f"\n✅ 完成！")
        print(f"  Markdown: {md_path}")
        print(f"  HTML: {html_path}")

        return html_path

    finally:
        await scraper.close()


async def run_hot(
    output_dir: str,
    top: int = 10,
    whisper_model: str = "small",
    skip_transcribe: bool = False,
    keep_audio: bool = False,
):
    """处理小宇宙『热门榜 Top N』(默认 Top 10，输出索引页 + 每集独立页)"""
    scraper = XiaoyuzhouScraper(headless=True)

    try:
        print(f"\n📡 抓取小宇宙热门榜 Top {top}…")
        episodes = await scraper.get_hot_episodes(limit=top)
        if not episodes:
            print("❌ 未抓到任何热门单集")
            return

        print(f"\n🔥 已锁定热门 Top {len(episodes)}")
        for ep in episodes:
            print(f"  · #{ep.get('rank', '?')} {ep['title'][:50]} —— {ep.get('podcast_title', '')}")

        audio_dir = os.path.join(output_dir, "audio")
        transcript_dir = os.path.join(output_dir, "transcripts")

        if not skip_transcribe:
            transcriber = Transcriber(model_size=whisper_model)
        else:
            transcriber = None
            print("\n⏭️ 跳过转录，仅基于 shownotes 生成总结")

        episode_summaries = []
        for i, ep in enumerate(episodes, 1):
            print(f"\n{'='*60}")
            print(f"处理 Top {ep.get('rank', i)} / {len(episodes)}: {ep['title'][:50]}")
            print(f"{'='*60}")

            transcript = {"text": "", "segments": [], "language": "zh", "duration": 0}
            if transcriber:
                transcript = await process_episode(
                    ep, transcriber, audio_dir, transcript_dir, skip_transcribe
                )

            summarizer = PodcastSummarizer()
            summary = summarizer.summarize_episode(ep, transcript)
            # 把榜单排名带到 summary，便于报告渲染
            summary["rank"] = ep.get("rank", i)
            episode_summaries.append(summary)

        print(f"\n📊 生成榜单归纳…")
        summarizer = PodcastSummarizer()
        multi_data = summarizer.summarize_multiple(episode_summaries)
        # 标记为榜单模式 + 自定义标题
        multi_data["is_ranking"] = True
        multi_data["ranking_label"] = f"小宇宙热门榜 Top {len(episodes)}"
        multi_data["podcast_title"] = f"小宇宙热门榜 Top {len(episodes)}"

        reporter = ReportGenerator(output_dir)
        md_path = reporter.generate_markdown(multi_data)
        # 榜单模式：拆成索引页 + 每集独立页
        html_path = reporter.generate_ranking_site(multi_data, md_path)

        meta_path = os.path.join(output_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ranking": multi_data["ranking_label"],
                    "episodes": episodes,
                    "summaries": episode_summaries,
                    "multi_summary": multi_data,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(f"\n✅ 完成！")
        print(f"  Markdown: {md_path}")
        print(f"  HTML: {html_path}")

        return html_path

    finally:
        await scraper.close()


async def run_podcast(
    url_or_id: str,
    output_dir: str,
    max_episodes: int = 5,
    whisper_model: str = "small",
    skip_transcribe: bool = False,
    keep_audio: bool = False,
):
    """处理播客节目（多集）"""
    scraper = XiaoyuzhouScraper(headless=True)

    try:
        # 获取播客信息和单集列表
        print(f"\n📡 获取播客信息...")
        podcast_info, episodes = await scraper.get_podcast_episodes(
            url_or_id, max_episodes=max_episodes
        )
        print(f"\n📻 {podcast_info['title']}")
        print(f"  作者: {podcast_info['author']}")
        print(f"  总集数: {podcast_info['episode_count']}")
        print(f"  本次获取: {len(episodes)} 集")

        if not episodes:
            print("❌ 未获取到任何单集")
            return

        # 初始化转录器
        audio_dir = os.path.join(output_dir, "audio")
        transcript_dir = os.path.join(output_dir, "transcripts")

        if not skip_transcribe:
            transcriber = Transcriber(model_size=whisper_model)
        else:
            transcriber = None
            print("\n⏭️ 跳过转录，仅基于 shownotes 生成总结")

        # 处理每集
        episode_summaries = []
        for i, ep in enumerate(episodes, 1):
            print(f"\n{'='*60}")
            print(f"处理第 {i}/{len(episodes)} 集: {ep['title'][:50]}")
            print(f"{'='*60}")

            # 转录
            transcript = {"text": "", "segments": [], "language": "zh", "duration": 0}
            if transcriber:
                transcript = await process_episode(
                    ep, transcriber, audio_dir, transcript_dir, skip_transcribe
                )

            # 总结
            summarizer = PodcastSummarizer()
            summary = summarizer.summarize_episode(ep, transcript)
            episode_summaries.append(summary)

        # 多篇归纳
        print(f"\n📊 生成多篇归纳...")
        summarizer = PodcastSummarizer()
        multi_data = summarizer.summarize_multiple(episode_summaries)

        # 生成报告
        reporter = ReportGenerator(output_dir)
        md_path = reporter.generate_markdown(multi_data)
        html_path = reporter.generate_html(multi_data, md_path)

        # 保存元数据
        meta_path = os.path.join(output_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "podcast": podcast_info,
                    "episodes": episodes,
                    "summaries": episode_summaries,
                    "multi_summary": multi_data,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(f"\n✅ 完成！")
        print(f"  Markdown: {md_path}")
        print(f"  HTML: {html_path}")

        return html_path

    finally:
        await scraper.close()


def main():
    parser = argparse.ArgumentParser(
        description="Podcast Digest — 小宇宙播客总结工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 总结单集播客
  python3 main.py episode https://www.xiaoyuzhoufm.com/episode/6a0c256be1eb34a939b0cb35

  # 总结播客最近5集
  python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/5e4ee557418a84a0466737b7 --max-episodes 5

  # 跳过转录（更快，仅基于 shownotes）
  python3 main.py podcast https://www.xiaoyuzhoufm.com/podcast/5e4ee557418a84a0466737b7 --no-transcribe

  # 使用更大的 Whisper 模型（更准确但更慢）
  python3 main.py episode https://www.xiaoyuzhoufm.com/episode/xxx --whisper-model medium
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="命令")

    # episode 命令
    ep_parser = subparsers.add_parser("episode", help="总结单集播客")
    ep_parser.add_argument("url", help="单集URL或EID")

    # podcast 命令
    pod_parser = subparsers.add_parser("podcast", help="总结播客节目（多集）")
    pod_parser.add_argument("url", help="播客URL或PID")
    pod_parser.add_argument(
        "--max-episodes", type=int, default=5, help="最多处理几集（默认5）"
    )

    # hot 命令
    hot_parser = subparsers.add_parser(
        "hot", help="抓取小宇宙『热门榜 Top N』并生成榜单总结报告"
    )
    hot_parser.add_argument(
        "--top", type=int, default=10, help="榜单前几名（默认 10）"
    )

    # 通用参数
    for p in [ep_parser, pod_parser, hot_parser]:
        p.add_argument(
            "-o",
            "--output",
            default=DEFAULT_OUTPUT_DIR,
            help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}）",
        )
        p.add_argument(
            "--whisper-model",
            default="small",
            choices=["tiny", "base", "small", "medium", "large-v3"],
            help="Whisper 模型大小（默认 small）",
        )
        p.add_argument(
            "--no-transcribe",
            action="store_true",
            help="跳过语音转录，仅基于 shownotes 生成总结",
        )
        p.add_argument(
            "--keep-audio",
            action="store_true",
            help="保留下载的音频文件（默认转录后删除）",
        )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "episode":
        asyncio.run(
            run_episode(
                url_or_id=args.url,
                output_dir=args.output,
                whisper_model=args.whisper_model,
                skip_transcribe=args.no_transcribe,
                keep_audio=args.keep_audio,
            )
        )
    elif args.command == "podcast":
        asyncio.run(
            run_podcast(
                url_or_id=args.url,
                output_dir=args.output,
                max_episodes=args.max_episodes,
                whisper_model=args.whisper_model,
                skip_transcribe=args.no_transcribe,
                keep_audio=args.keep_audio,
            )
        )
    elif args.command == "hot":
        asyncio.run(
            run_hot(
                output_dir=args.output,
                top=args.top,
                whisper_model=args.whisper_model,
                skip_transcribe=args.no_transcribe,
                keep_audio=args.keep_audio,
            )
        )


if __name__ == "__main__":
    main()
