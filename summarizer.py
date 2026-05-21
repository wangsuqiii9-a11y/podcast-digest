"""
AI 总结模块
对播客转录文本进行重点提炼和多篇归纳
支持基于 shownotes 的快速总结 和 基于转录文本的深度总结
"""

import json
import os
import re
from typing import Optional


class PodcastSummarizer:
    """播客内容总结器"""

    # 需要跳过的 shownotes 章节关键词
    SKIP_SECTIONS = {
        "制作团队", "互动方式", "支持我们", "音乐", "赞助商",
        "商务合作", "节目运营", "节目制作", "声音设计", "节目统筹",
        "logo设计", "出品", "微博", "微信公众号", "小红书",
        "B站", "抖音", "买书", "书目", "签名版",
    }

    def __init__(self, api_key: Optional[str] = None, model: str = ""):
        self.api_key = api_key
        self.model = model

    def summarize_episode(self, episode: dict, transcript: dict) -> dict:
        """总结单集播客内容"""
        title = episode.get("title", "")
        description = episode.get("description", "")
        shownotes = episode.get("shownotes", "")
        text = transcript.get("text", "")
        duration = episode.get("duration_minutes", 0)

        # 优先用换行更规整的字段做解析（description 通常有换行；shownotes 可能没有）
        primary_notes = description if description.count("\n") >= shownotes.count("\n") else shownotes
        if not primary_notes:
            primary_notes = description or shownotes

        # 解析 shownotes 为结构化数据
        parsed = self._parse_shownotes(primary_notes)

        # 如果时间轴还是空（说明文本被压扁了），尝试用正则在原文里直接抓时间戳
        if not parsed["timeline"]:
            parsed["timeline"] = self._extract_timeline_inline(shownotes or description)

        # 从 shownotes 提取时间轴
        timeline = parsed["timeline"]

        # 提取关键要点（优先时间轴，其次从描述/转录中提取）
        key_points = self._extract_key_points(parsed, text)

        # 生成总结
        summary = self._generate_summary(title, description, parsed, text)

        # 提取话题标签（仅基于标题+导语，避免被制作团队/音乐章节污染）
        intro_for_tags = parsed.get("intro", "") or description[:1200]
        tags = self._extract_tags(title, intro_for_tags, "")

        # 提取嘉宾信息
        guests = parsed.get("guests", [])
        if not guests:
            # 兜底：从原始文本里抓嘉宾段
            guests = self._extract_guests_inline(shownotes or description)

        # 结构化的"内容概要"分点（用于报告里"概要分几个大点"的展示）
        summary_points = self._build_summary_points(summary, parsed, guests, title)

        eid = episode.get("eid", "")
        return {
            "title": title,
            "podcast_title": episode.get("podcast_title", ""),
            "duration_minutes": duration,
            "pub_date": episode.get("pub_date", ""),
            "summary": summary,
            "summary_points": summary_points,
            "key_points": key_points,
            "timeline": timeline,
            "tags": tags,
            "guests": guests,
            "eid": eid,
            "audio_url": episode.get("audio_url", ""),
            "episode_url": f"https://www.xiaoyuzhoufm.com/episode/{eid}" if eid else "",
        }

    def summarize_multiple(self, episode_summaries: list[dict]) -> dict:
        """多篇归纳：跨集总结"""
        if not episode_summaries:
            return {"overview": "", "common_themes": [], "cross_episode_insights": []}

        # 提取共同主题
        all_tags = []
        for s in episode_summaries:
            all_tags.extend(s.get("tags", []))

        tag_freq = {}
        for tag in all_tags:
            tag_freq[tag] = tag_freq.get(tag, 0) + 1

        common_themes = sorted(tag_freq.items(), key=lambda x: -x[1])[:10]

        # 生成跨集洞察
        cross_insights = self._generate_cross_insights(episode_summaries)

        # 生成总体概述
        overview = self._generate_overview(episode_summaries)

        return {
            "total_episodes": len(episode_summaries),
            "podcast_title": episode_summaries[0].get("podcast_title", "") if episode_summaries else "",
            "overview": overview,
            "common_themes": [
                {"tag": tag, "count": count} for tag, count in common_themes
            ],
            "cross_episode_insights": cross_insights,
            "episodes": episode_summaries,
        }

    # ========== Shownotes 解析 ==========

    def _parse_shownotes(self, shownotes: str) -> dict:
        """将 shownotes 解析为结构化数据

        Returns:
            dict: {
                intro: str,           # 导语
                timeline: list,       # 时间轴 [{time, content}]
                guests: list[str],    # 嘉宾列表
                sections: dict,       # 其他章节 {name: [lines]}
            }
        """
        result = {"intro": "", "timeline": [], "guests": [], "sections": {}}

        if not shownotes:
            return result

        lines = shownotes.split("\n")
        current_section = ""
        skip_mode = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测章节标记: - 章节名 -
            section_match = re.match(r"^[-–—]\s*(.+?)\s*[-–—]$", line)
            if section_match:
                current_section = section_match.group(1).strip()
                skip_mode = any(s in current_section for s in self.SKIP_SECTIONS)
                continue

            # 跳过无关章节
            if skip_mode:
                continue

            # 检测时间轴条目: 01:23:45 描述 / 1:23 描述
            time_match = re.match(
                r"^(\d{1,2}:\d{2}(?::\d{2})?)\s*[：:\s]\s*(.+)$", line
            )
            if time_match:
                time_str = time_match.group(1)
                content = time_match.group(2).strip()
                if content:
                    result["timeline"].append({"time": time_str, "content": content})
                continue

            # 导语章节
            if current_section in ("导语", ""):
                if result["intro"]:
                    result["intro"] += " " + line
                else:
                    result["intro"] = line
                continue

            # 嘉宾/话题成员章节
            if any(kw in current_section for kw in ("话题成员", "嘉宾", "本期成员", "成员")):
                # 尝试提取人名和身份
                guest = line.lstrip("-• ").strip()
                if guest and len(guest) > 1:
                    result["guests"].append(guest)
                continue

            # 其他有价值的章节
            if current_section and not skip_mode:
                if current_section not in result["sections"]:
                    result["sections"][current_section] = []
                result["sections"][current_section].append(line)

        return result

    # ========== 关键要点提取 ==========

    def _extract_timeline_inline(self, raw: str) -> list[dict]:
        """从未分行的 shownotes 中直接抽取时间轴。

        通过定位时间戳出现的位置切分文本，每个时间戳到下一个时间戳之间的内容视为该条目的描述。
        """
        if not raw:
            return []

        # 时间戳模式：1:23 / 12:34 / 1:23:45
        pattern = re.compile(r"(?<![\d:])(\d{1,2}:\d{2}(?::\d{2})?)")
        matches = list(pattern.finditer(raw))
        if not matches:
            return []

        timeline = []
        for i, m in enumerate(matches):
            time_str = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            content = raw[start:end].strip(" :：-—\n")
            # 截断到下一个章节标记 "- xxx -" 之前
            cut = re.search(r"\s*-\s*[^-\n]{2,20}\s*-", content)
            if cut:
                content = content[: cut.start()].strip()
            if content and len(content) < 200:
                timeline.append({"time": time_str, "content": content})

        return timeline

    def _extract_guests_inline(self, raw: str) -> list[str]:
        """从未分行的 shownotes 中抽取话题成员/嘉宾段落"""
        if not raw:
            return []

        # 找到 "- 本期话题成员 -" / "- 嘉宾 -" 等章节起点到下一个章节
        m = re.search(
            r"-\s*(?:本期话题成员|话题成员|嘉宾|本期嘉宾|本期成员)\s*-\s*(.+?)(?=-\s*[^-\n]{2,20}\s*-|$)",
            raw,
            flags=re.DOTALL,
        )
        if not m:
            return []
        block = m.group(1).strip()
        # 按括号或顿号/换行切分多个嘉宾
        # 简单策略：按 "）" 之后切分
        candidates = re.split(r"(?<=）)|(?<=\))|\n|、", block)
        guests = []
        for c in candidates:
            c = c.strip(" ，,.。-—•")
            if c and len(c) > 1 and len(c) < 100:
                guests.append(c)
        return guests

    def _extract_key_points(self, parsed: dict, transcript_text: str) -> list[str]:
        """提取关键要点"""
        key_points = []

        # 1. 优先从时间轴提取（最结构化）
        timeline = parsed.get("timeline", [])
        if timeline:
            for item in timeline:
                key_points.append(f"[{item['time']}] {item['content']}")

        # 2. 从其他有价值的章节中提取要点（跳过导语，避免把长摘要塞入要点）
        EXCLUDE_FROM_KEYPOINTS = {"导语", "本期话题成员", "话题成员", "嘉宾", "本期嘉宾", "本期成员"}
        for section_name, lines in parsed.get("sections", {}).items():
            if any(skip in section_name for skip in self.SKIP_SECTIONS):
                continue
            if section_name in EXCLUDE_FROM_KEYPOINTS:
                continue
            for line in lines:
                line = line.strip().lstrip("-• ").strip()
                if line and len(line) > 5 and len(line) < 200:
                    # 避免与时间轴重复
                    if not any(line in kp for kp in key_points):
                        key_points.append(line)

        # 3. 如果以上都不够，从转录文本提取
        if len(key_points) < 3 and transcript_text:
            trans_points = self._extract_from_transcript(transcript_text)
            for p in trans_points:
                if not any(p in kp for kp in key_points):
                    key_points.append(p)

        return key_points[:20]

    def _extract_from_transcript(self, text: str) -> list[str]:
        """从转录文本中提取要点"""
        if not text:
            return []

        points = []
        # 按句号分割
        sentences = re.split(r"[。！？；\n]", text)
        for s in sentences:
            s = s.strip()
            if len(s) > 20 and len(s) < 200:
                # 优先选择包含观点性关键词的句子
                if any(kw in s for kw in [
                    "我觉得", "我认为", "其实", "关键是", "重要的是",
                    "核心", "本质", "问题在于", "根本原因", "换句话说",
                    "也就是说", "总结来说", "换言之",
                ]):
                    points.append(s)
                    if len(points) >= 10:
                        break

        # 如果观点性句子不够，补充长句
        if len(points) < 5:
            for s in sentences:
                s = s.strip()
                if len(s) > 30 and len(s) < 200 and s not in points:
                    points.append(s)
                    if len(points) >= 10:
                        break

        return points

    # ========== 总结生成 ==========

    def _build_summary_points(
        self, summary: str, parsed: dict, guests: list[str], title: str
    ) -> list[dict]:
        """把整段导语+时间轴+章节信息糅合成一篇有逻辑层次的"微缩文章"。

        每一个大点都包含：title（小标题）+ lead（一句话总起）+ content（展开论述）。
        构造逻辑（按时间轴长度自适应）：
          1. 节目主旨：导语首句 + 嘉宾画像
          2. 时代背景与缘起：时间轴前 1/4 + 导语里"年/背景"相关句
          3. 核心议题：时间轴中段 + 导语里"问题/疑问/为何/如何"句
          4. 关键转折与悬念：时间轴后段
          5. 本期收获/收尾：时间轴最后一项 + 导语收尾句

        Returns:
            list[dict]: [{title, lead, content}]
        """
        points: list[dict] = []

        intro = (parsed.get("intro") or summary or "").strip()
        timeline = parsed.get("timeline") or []
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[。！？!?])", intro)
            if s.strip()
        ]

        # ---------- 工具函数 ----------
        def join_timeline(items: list[dict]) -> str:
            """把时间轴段落串成一段连贯的中文叙述。"""
            if not items:
                return ""
            parts = []
            for it in items:
                c = (it.get("content") or "").strip().rstrip("。.；;")
                if c:
                    parts.append(f"{it['time']} 切入「{c}」")
            return "；".join(parts) + "。" if parts else ""

        def pick_sentences(keywords: list[str], used: set) -> str:
            """从导语里挑出含关键词的句子，避免与已用句子重复。"""
            picked = []
            for s in sentences:
                if s in used:
                    continue
                if any(k in s for k in keywords):
                    picked.append(s)
                    used.add(s)
            return "".join(picked)

        used_sents: set = set()

        # ---------- 1. 节目主旨 ----------
        opener = sentences[0] if sentences else (intro[:120] if intro else "")
        if opener:
            used_sents.add(opener)

        guest_brief = ""
        if guests:
            # 仅取第一句嘉宾名 + 身份，避免太冗长
            short_guests = []
            for g in guests:
                # 把"姓名，身份，著作"截断成"姓名（身份）"
                g_clean = re.sub(r"\s*[（(].*?[）)]\s*", "", g)
                short_guests.append(g_clean.strip())
            guest_brief = "本期对谈嘉宾：" + "、".join(short_guests) + "。"

        if opener or guest_brief:
            # content 不再重复 lead（lead 取自 opener 时把 content 留给嘉宾说明）
            body_parts = []
            if guest_brief:
                body_parts.append(guest_brief)
            # 如果导语只有 1 句，content 给个补充说明，避免完全空白
            if not body_parts and opener:
                body_parts.append(opener)
            points.append({
                "title": "节目主旨",
                "lead": opener[:120] if opener else "本期节目核心议题",
                "content": "\n\n".join(body_parts).strip() or opener,
            })

        # ---------- 2. 时代背景与缘起 ----------
        bg_sents = pick_sentences(
            ["年", "背景", "曾", "前", "起源", "诞生", "由来", "历史", "当年"],
            used_sents,
        )
        n = len(timeline)
        bg_tl = timeline[: max(1, n // 4)] if n else []
        bg_text = ""
        if bg_sents:
            bg_text += bg_sents
        if bg_tl:
            if bg_text:
                bg_text += "\n\n"
            bg_text += "节目从 " + join_timeline(bg_tl)
        if bg_text:
            points.append({
                "title": "时代背景与缘起",
                "lead": "理解本期讨论的历史与现实背景。",
                "content": bg_text.strip(),
            })

        # ---------- 3. 核心议题与叙事主线 ----------
        core_sents = pick_sentences(
            ["新发现", "新解读", "重新", "梳理", "视角", "切入", "观察", "如何", "为何", "是否", "?", "？"],
            used_sents,
        )
        if n >= 4:
            mid_start = max(1, n // 4)
            mid_end = max(mid_start + 1, (3 * n) // 4)
            mid_tl = timeline[mid_start:mid_end]
        else:
            mid_tl = timeline[1:-1] if n > 2 else []

        core_text = ""
        if core_sents:
            core_text += core_sents
        if mid_tl:
            if core_text:
                core_text += "\n\n"
            core_text += "本期主线沿以下几条线索展开：" + join_timeline(mid_tl)
        if core_text:
            points.append({
                "title": "核心议题与叙事主线",
                "lead": "本期最值得关注的几个追问与展开。",
                "content": core_text.strip(),
            })

        # ---------- 4. 关键转折与悬念 ----------
        end_tl = timeline[(3 * n) // 4:] if n >= 4 else (timeline[-1:] if n else [])
        # 排除 mid_tl 末尾重复的 item
        end_tl = [it for it in end_tl if it not in mid_tl]
        twist_sents = pick_sentences(
            ["竟然", "其实", "真相", "魔改", "重新", "悬念", "疑团", "之谜", "暴毙", "废"],
            used_sents,
        )
        twist_text = ""
        if twist_sents:
            twist_text += twist_sents
        if end_tl:
            if twist_text:
                twist_text += "\n\n"
            twist_text += "尾段聚焦最具张力的若干节点：" + join_timeline(end_tl)
        if twist_text:
            points.append({
                "title": "关键转折与悬念",
                "lead": "全集最有张力、最颠覆常识的几个时刻。",
                "content": twist_text.strip(),
            })

        # ---------- 5. 收尾邀请 / 剩余信息 ----------
        rest = "".join(s for s in sentences if s not in used_sents).strip()
        if rest:
            points.append({
                "title": "本期看点收束",
                "lead": "嘉宾对核心问题的回应与节目落点。",
                "content": rest,
            })

        # ---------- 兜底：信息太少时利用其他章节 ----------
        if len(points) < 2:
            for sec_name, lines in parsed.get("sections", {}).items():
                if any(skip in sec_name for skip in self.SKIP_SECTIONS):
                    continue
                joined = " ".join(l.strip().lstrip("-• ") for l in lines if l.strip())
                if joined:
                    points.append({
                        "title": sec_name,
                        "lead": "节目延伸内容。",
                        "content": joined[:400],
                    })
                    break

        # ---------- 嘉宾速览（短卡片放最前面）----------
        # 节目主旨里已用 guest_brief 简短带过，这里用更详细的"姓名 + 身份/著作"卡片
        if guests:
            points.insert(0, {
                "title": "嘉宾速览",
                "lead": f"本期共 {len(guests)} 位对谈者。",
                "content": "\n".join(f"· {g}" for g in guests),
            })

        return points

    def _generate_summary(
        self, title: str, description: str, parsed: dict, text: str
    ) -> str:
        """生成单集总结"""
        parts = []

        # 1. 使用导语作为核心总结
        intro = parsed.get("intro", "")
        if intro:
            parts.append(intro)

        # 2. 如果没有导语，使用 description
        if not parts and description:
            # 清理 description，跳过无关部分
            clean_desc = self._clean_description(description)
            if clean_desc:
                parts.append(clean_desc)

        # 3. 如果描述也太短，用转录文本的前部分
        if (not parts or len(parts[0]) < 50) and text:
            first_part = text[:800]
            parts.append(f"内容概要：{first_part}...")

        return "\n\n".join(parts) if parts else "暂无总结"

    def _clean_description(self, description: str) -> str:
        """清理描述文本，去除无关章节"""
        lines = description.split("\n")
        clean_lines = []
        skip = False

        for line in lines:
            line = line.strip()
            if not line:
                if not skip:
                    clean_lines.append("")
                continue

            # 检测章节标题
            section_match = re.match(r"^[-–—]\s*(.+?)\s*[-–—]$", line)
            if section_match:
                section_name = section_match.group(1).strip()
                skip = any(s in section_name for s in self.SKIP_SECTIONS)
                continue

            if not skip:
                clean_lines.append(line)

        result = "\n".join(clean_lines).strip()
        # 清理多余空行
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result

    # ========== 话题标签提取 ==========

    def _extract_tags(self, title: str, description: str, shownotes: str) -> list[str]:
        """提取话题标签"""
        tags = set()
        combined = f"{title} {description} {shownotes}"

        topic_keywords = {
            "历史": ["历史", "古代", "朝代", "皇帝", "革命", "战争", "文明", "晚清", "民国", "清史", "传教士"],
            "科技": ["科技", "技术", "AI", "人工智能", "互联网", "数字化", "算法", "芯片"],
            "文化": ["文化", "文学", "艺术", "电影", "阅读", "出版"],
            "社会": ["社会", "城市", "教育", "就业", "人口", "老龄化", "移民"],
            "经济": ["经济", "金融", "市场", "投资", "消费", "贸易", "资本"],
            "政治": ["政治", "政策", "国际", "外交", "地缘", "治理"],
            "心理": ["心理", "情绪", "认知", "思维", "意识", "精神"],
            "哲学": ["哲学", "思想", "伦理", "道德", "存在", "启蒙"],
            "商业": ["商业", "创业", "管理", "品牌", "营销", "企业"],
            "法律": ["法律", "法规", "司法", "权利", "制度"],
            "环境": ["环境", "气候", "可持续", "碳", "生态"],
            "医疗": ["医疗", "健康", "医学", "疾病", "公共卫生"],
            "国际关系": ["国际", "外交", "冷战", "情报", "间谍", "地缘"],
            "宗教": ["宗教", "佛教", "基督教", "伊斯兰", "传教士"],
            "军事": ["军事", "军队", "战争", "武器", "国防"],
            "音乐": ["音乐", "乐队", "摇滚", "古典", "爵士"],
            "设计": ["设计", "用户体验", "UI", "UX", "建筑"],
            "女性主义": ["女性", "性别", "平权", "女权"],
        }

        for tag, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                tags.add(tag)

        return list(tags)

    # ========== 多篇归纳 ==========

    def _generate_cross_insights(self, summaries: list[dict]) -> list[str]:
        """生成跨集洞察"""
        insights = []

        if len(summaries) < 2:
            return insights

        # 共同标签
        all_tag_sets = [set(s.get("tags", [])) for s in summaries]
        common = all_tag_sets[0]
        for tag_set in all_tag_sets[1:]:
            common = common & tag_set

        if common:
            insights.append(
                f"多期节目共同涉及的话题：{'、'.join(common)}"
            )

        # 时长统计
        durations = [s.get("duration_minutes", 0) for s in summaries]
        if durations:
            avg = sum(durations) / len(durations)
            insights.append(
                f"平均时长 {avg:.0f} 分钟，"
                f"最长 {max(durations):.0f} 分钟，最短 {min(durations):.0f} 分钟"
            )

        # 话题演变
        all_tags_ordered = []
        for s in summaries:
            all_tags_ordered.extend(s.get("tags", []))
        unique_tags = list(dict.fromkeys(all_tags_ordered))
        if len(unique_tags) > 3:
            insights.append(
                f"话题覆盖范围：{'、'.join(unique_tags[:8])}"
            )

        return insights

    def _generate_overview(self, summaries: list[dict]) -> str:
        """生成总体概述"""
        if not summaries:
            return ""

        podcast_title = summaries[0].get("podcast_title", "播客")
        total = len(summaries)
        titles = [f"《{s['title']}》" for s in summaries]

        overview = f"本报告涵盖 {podcast_title} 的 {total} 期节目："
        if total <= 5:
            overview += "、".join(titles)
        else:
            overview += "、".join(titles[:5]) + "等"

        total_duration = sum(s.get("duration_minutes", 0) for s in summaries)
        if total_duration:
            hours = total_duration / 60
            if hours >= 1:
                overview += f"，总时长约 {hours:.1f} 小时"
            else:
                overview += f"，总时长约 {total_duration:.0f} 分钟"

        return overview
