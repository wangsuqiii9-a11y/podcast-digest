"""
报告生成模块
输出 Markdown 和 HTML 格式的播客总结报告
"""

import html as html_module
import json
import os
from datetime import datetime
from typing import Optional


def _esc(text: str) -> str:
    """HTML escape 工具"""
    return html_module.escape(text or "", quote=True)


def _time_to_seconds(t: str) -> int:
    """把 1:23 / 01:23 / 1:23:45 / 01:23:45 转成秒数"""
    if not t:
        return 0
    parts = t.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return 0


class ReportGenerator:
    """播客总结报告生成器"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ========== 数据兜底 ==========

    @staticmethod
    def _split_sentences(text: str) -> list:
        """中英文混合切句：句号/感叹号/问号/分号/逗号。允许较短句子，便于稀薄数据兜底。"""
        if not text:
            return []
        import re as _re
        chunks: list = []
        for para in text.replace("\r\n", "\n").split("\n"):
            para = para.strip()
            if not para:
                continue
            # 先按强标点切；如果切完仍然只有 1 大段，再按逗号/顿号细分
            parts = _re.split(r"(?<=[。！？!?；;])", para)
            if len(parts) <= 1 and len(para) > 40:
                parts = _re.split(r"(?<=[，,、])", para)
            for p in parts:
                p = p.strip(" 　\t")
                if len(p) >= 4:  # 放宽阈值
                    chunks.append(p)
        return chunks

    @classmethod
    def _ensure_episode_explanation(cls, ep: dict) -> dict:
        """
        若节目数据较少（无 summary_points / timeline / key_points），
        基于 summary / 标题 / 嘉宾 / 标签 自动凑出 3-5 个『内容速览要点』，
        保证任何一集详情页都不会出现"无解析"。
        """
        ep = dict(ep)  # 不污染原对象
        summary = (ep.get("summary") or "").strip()
        # 过滤掉源数据里的占位文本（如"暂无总结"/"无数据"）
        _PLACEHOLDER = {"暂无总结", "无数据", "无", "暂无", "暂无概要", "暂无内容", "—", "-", "/"}
        raw_sps = ep.get("summary_points") or []
        sps = []
        for s in raw_sps:
            lead_ = (s.get("lead") or "").strip()
            content_ = (s.get("content") or "").strip()
            if not (lead_ or content_):
                continue
            if (lead_ in _PLACEHOLDER) and (content_ in _PLACEHOLDER or not content_):
                continue
            sps.append(s)
        kps = ep.get("key_points") or []
        tl = ep.get("timeline") or []
        title = (ep.get("title") or "").strip()
        podcast = (ep.get("podcast_title") or "").strip()
        guests = ep.get("guests") or []
        tags = ep.get("tags") or []
        duration = ep.get("duration_minutes") or 0
        pub_date_raw = (ep.get("pub_date") or "").strip()
        # pub_date 兼容 RFC822（"Mon, 18 May 2026 ..."）和 ISO（"2026-05-18..."）
        pub_date = ""
        if pub_date_raw:
            if pub_date_raw[:4].isdigit():
                pub_date = pub_date_raw[:10]
            else:
                # 取逗号后那段日期文字
                try:
                    parts = pub_date_raw.split(" ")
                    if len(parts) >= 4:
                        pub_date = f"{parts[1]} {parts[2]} {parts[3]}"
                    else:
                        pub_date = pub_date_raw[:16]
                except Exception:
                    pub_date = pub_date_raw[:16]

        TITLES = ["节目主旨", "重要观点", "亮点片段", "嘉宾分享", "更多内容"]

        def _push(title_, lead, content):
            """去重追加。"""
            key = (content or lead or "")[:40]
            if not key:
                return
            for s in sps:
                if (s.get("content") or s.get("lead") or "")[:40] == key:
                    return
            sps.append({"title": title_, "lead": lead[:80], "content": content})

        # 1) 用 summary 切句兜底（忽略 summary 本身就是占位文本的情况）
        summary_clean = "" if summary in _PLACEHOLDER else summary
        if len(sps) < 3 and summary_clean:
            sentences = [s for s in cls._split_sentences(summary_clean) if s.strip() not in _PLACEHOLDER]
            for i, s in enumerate(sentences[:5]):
                _push(TITLES[len(sps)] if len(sps) < 5 else "更多内容",
                      s[:80] + ("…" if len(s) > 80 else ""), s)
                if len(sps) >= 5:
                    break

        # 2) 仍不足：从 标题 / 嘉宾 / 标签 / 节目元信息 / 排名 拼出兜底卡
        if len(sps) < 3:
            if title:
                _push("节目标题速读", title[:80], title)
            if guests:
                gtxt = "本期嘉宾：" + "、".join(str(g) for g in guests)
                _push("嘉宾阵容", gtxt[:80], gtxt)
            if tags:
                ttxt = "话题关键词：" + " / ".join(str(t) for t in tags)
                _push("话题方向", ttxt[:80], ttxt)
            meta_bits = []
            if podcast:
                meta_bits.append(f"出自播客《{podcast}》")
            if duration:
                meta_bits.append(f"时长约 {duration:.0f} 分钟")
            if pub_date:
                meta_bits.append(f"发布于 {pub_date}")
            if meta_bits:
                mtxt = "，".join(meta_bits) + "。"
                _push("节目信息", mtxt[:80], mtxt)
            # 上榜理由
            rank_v = ep.get("rank")
            if rank_v:
                rtxt = f"本期在当前热门榜中排名第 {rank_v} 位，由听众讨论度与播放热度共同推选。"
                _push("上榜原因", rtxt[:80], rtxt)
            # 实在啥都没有，给一个温和的占位，避免空白
            if len(sps) == 0:
                _push("内容暂未抓取",
                      "本期节目尚未抓取到详细概要，可点击下方在小宇宙打开收听完整节目。",
                      "本期节目尚未抓取到详细概要。你可以点击下方按钮在小宇宙打开，收听完整节目内容。")

        ep["summary_points"] = sps[:5]

        # 3) key_points 兜底
        if not kps and not tl:
            if summary_clean:
                ep["key_points"] = [s for s in cls._split_sentences(summary_clean)[:5] if s.strip() not in _PLACEHOLDER]
            elif sps:
                # 用 summary_points 的 lead 当 key_points
                ep["key_points"] = [s.get("lead") or s.get("content") or "" for s in sps[:5] if (s.get("lead") or s.get("content"))]

        return ep

    # ========== Markdown ==========

    def generate_markdown(self, data: dict) -> str:
        """生成 Markdown 报告"""
        lines = []

        podcast_title = data.get("podcast_title", "播客")
        total = data.get("total_episodes", 0)
        lines.append(f"# {podcast_title} — 播客总结报告\n")

        overview = data.get("overview", "")
        if overview:
            lines.append(f"## 总体概述\n\n{overview}\n")

        common_themes = data.get("common_themes", [])
        if common_themes:
            lines.append("## 共同主题\n")
            for theme in common_themes:
                lines.append(f"- **{theme['tag']}** (出现 {theme['count']} 次)")
            lines.append("")

        cross_insights = data.get("cross_episode_insights", [])
        if cross_insights:
            lines.append("## 跨集洞察\n")
            for insight in cross_insights:
                lines.append(f"- {insight}")
            lines.append("")

        episodes = data.get("episodes", [])
        if episodes:
            lines.append("## 各集详细总结\n")
            for i, ep in enumerate(episodes, 1):
                lines.append(f"### 第 {i} 期：{ep.get('title', '未知')}\n")

                podcast = ep.get("podcast_title", "")
                duration = ep.get("duration_minutes", 0)
                pub_date = ep.get("pub_date", "")
                if pub_date:
                    pub_date = pub_date[:10]

                lines.append(
                    f"> 来源：{podcast} | 时长：{duration:.0f} 分钟 | 日期：{pub_date}\n"
                )

                episode_url = ep.get("episode_url", "")
                if episode_url:
                    lines.append(f"🔗 [在小宇宙打开]({episode_url})\n")

                guests = ep.get("guests", [])
                if guests:
                    lines.append(f"**嘉宾**：{'、'.join(guests)}\n")

                # 概要分点
                summary_points = ep.get("summary_points", [])
                if summary_points:
                    lines.append("**📌 内容概要**\n")
                    for idx, sp in enumerate(summary_points, 1):
                        title_ = sp.get("title", "")
                        lead = sp.get("lead", "")
                        content = sp.get("content", "")
                        lines.append(f"### {idx:02d}. {title_}")
                        if lead:
                            lines.append(f"> {lead}")
                        lines.append("")
                        # content 中已存在的换行保持原样
                        for para in content.split("\n"):
                            if para.strip():
                                lines.append(para.strip())
                        lines.append("")
                else:
                    summary = ep.get("summary", "")
                    if summary:
                        lines.append(f"**📌 内容概要**\n\n{summary}\n")

                # 章节速览（合并 关键要点 + 时间轴）
                timeline = ep.get("timeline", [])
                if timeline:
                    lines.append("**章节速览**（点击 HTML 报告中的时间码可跳转播放）\n")
                    for item in timeline:
                        lines.append(f"- `{item['time']}` {item['content']}")
                    lines.append("")

                tags = ep.get("tags", [])
                if tags:
                    lines.append(
                        f"**话题标签**：{' '.join(f'`{t}`' for t in tags)}\n"
                    )

                lines.append("---\n")

        lines.append(
            f"\n---\n\n*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"
        )

        md_content = "\n".join(lines)
        md_path = os.path.join(self.output_dir, f"{podcast_title}_播客总结.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"Markdown 报告已生成: {md_path}")
        return md_path

    # ========== HTML（榜单模式：索引页 + 每集独立页） ==========

    def generate_ranking_site(self, data: dict, md_path: str) -> str:
        """
        榜单模式专用：
        - 生成 index.html ：仅展示 Top N 入口卡片（不放详细概要）
        - 生成 episodes/episode_{NN}.html ：每篇一页，带『← 返回榜单』按钮

        返回 index.html 的绝对路径。
        """
        episodes = data.get("episodes", [])
        # 数据兜底：解析为空的集自动用 summary 切句补全
        episodes = [self._ensure_episode_explanation(ep) for ep in episodes]
        data = {**data, "episodes": episodes}

        ranking_label = data.get("ranking_label", f"热门榜 Top {len(episodes)}")
        site_title = data.get("podcast_title", ranking_label)

        # 准备每集页面所在子目录
        ep_dir = os.path.join(self.output_dir, "episodes")
        os.makedirs(ep_dir, exist_ok=True)

        # ---- 1) 渲染每集独立 HTML ----
        for i, ep in enumerate(episodes, 1):
            rank = ep.get("rank", i)
            ep_filename = f"episode_{rank:02d}.html"
            ep_path = os.path.join(ep_dir, ep_filename)

            # 该集的 EPISODES（仅含自己），index 固定为 0
            ep_payload = [{
                "index": 0,
                "audio_url": ep.get("audio_url", ""),
                "episode_url": ep.get("episode_url", ""),
                "title": ep.get("title", ""),
            }]
            ep_payload_json = json.dumps(ep_payload, ensure_ascii=False)

            page_title = f"TOP {rank:02d} · {ep.get('title', '')}"
            page_html = self._html_head(
                page_title, 1, is_ranking=True, sub_override=f"{ranking_label} · 第 {rank} 名"
            )

            # 顶部返回榜单按钮 + 当前用户 + 关注按钮
            ep_key = f"episode_{rank:02d}"
            ep_title_safe = _esc(ep.get('title', ''))
            page_html += (
                '        <div class="back-bar">\n'
                '            <a class="back-btn" href="../index.html">← 返回榜单首页</a>\n'
                f'            <button class="follow-btn" id="followBtn" data-epkey="{ep_key}" data-eptitle="{ep_title_safe}" onclick="toggleFollow()">☆ 加入我的关注榜</button>\n'
                '            <span class="ep-user-badge" id="epUserBadge">未登录</span>\n'
                '            <a class="ep-login-link" href="../login.html">切换账号</a>\n'
                '        </div>\n'
            )

            # 把 ep 强制 idx=1，以便 _render_episode_card 内部用 ep_index=0
            page_html += self._render_episode_card(1, ep, is_ranking=True)

            # 浮动播放器
            page_html += """
        <div class="audio-bar" id="audioBar">
            <div class="audio-bar-inner">
                <div class="audio-meta">
                    <div class="audio-title" id="audioTitle">未在播放</div>
                    <div class="audio-current" id="audioCurrent">点击章节速览中的时间码即可播放</div>
                </div>
                <audio id="audioPlayer" controls preload="none" style="flex:1; min-width: 240px;"></audio>
                <div class="speed-group">
                    <span class="speed-label">倍速</span>
                    <button class="speed-btn" data-speed="0.75">0.75×</button>
                    <button class="speed-btn" data-speed="1" data-active="true">1×</button>
                    <button class="speed-btn" data-speed="1.25">1.25×</button>
                    <button class="speed-btn" data-speed="1.5">1.5×</button>
                    <button class="speed-btn" data-speed="2">2×</button>
                </div>
            </div>
        </div>
"""

            page_html += f"""
        <div class="footer">
            报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} · Podcast Digest
        </div>
    </div>

    <!-- 个人随笔抽屉 -->
    <button class="notes-fab" id="notesFab" onclick="toggleNotesPanel()" title="打开随笔">📝<span id="notesFabDot" style="display:none">●</span></button>
    <aside class="notes-panel" id="notesPanel" aria-hidden="true">
        <div class="notes-panel-head">
            <div class="notes-panel-title">📝 我的随笔</div>
            <button class="notes-panel-close" onclick="toggleNotesPanel()" title="收起">✕</button>
        </div>
        <div class="notes-panel-meta">
            <span id="notesPanelUser" class="user-badge">未登录</span>
            <span id="notesPanelStatus" class="notes-panel-status">就绪</span>
        </div>
        <textarea id="notesEditor" class="notes-editor"
            placeholder="写下你听这一集的感想、金句、行动项……（自动保存到本地）"></textarea>
        <div class="notes-panel-tip">仅保存在你这台设备上，按账号隔离；可在首页『我的随笔』回顾全部。</div>
    </aside>
"""

            page_html += f"""
    <script>
        const EPISODES = {ep_payload_json};
        const EP_KEY = "{ep_key}";
        const EP_TITLE = {json.dumps(ep.get('title', ''), ensure_ascii=False)};
        const audio = document.getElementById('audioPlayer');
        const audioTitle = document.getElementById('audioTitle');
        const audioCurrent = document.getElementById('audioCurrent');
        let currentEpisode = -1;

        function playSegment(epIndex, seconds, contentText) {{
            const ep = EPISODES[epIndex];
            if (!ep || !ep.audio_url) {{
                alert('该集没有可用的音频地址');
                return;
            }}
            if (currentEpisode !== epIndex) {{
                audio.src = ep.audio_url;
                currentEpisode = epIndex;
                audioTitle.textContent = ep.title || '正在播放';
            }}
            const start = () => {{
                try {{ audio.currentTime = seconds; }} catch (e) {{}}
                audio.play().catch(() => {{}});
                audioCurrent.textContent = contentText || '';
            }};
            if (audio.readyState >= 1) {{
                start();
            }} else {{
                audio.addEventListener('loadedmetadata', start, {{ once: true }});
                audio.load();
            }}
            document.getElementById('audioBar').scrollIntoView({{ behavior: 'smooth', block: 'end' }});
        }}

        document.querySelectorAll('.speed-btn').forEach(btn => {{
            btn.addEventListener('click', () => {{
                const speed = parseFloat(btn.dataset.speed);
                audio.playbackRate = speed;
                document.querySelectorAll('.speed-btn').forEach(b => b.removeAttribute('data-active'));
                btn.setAttribute('data-active', 'true');
            }});
        }});
        window.playSegment = playSegment;

        // —— 用户/随笔/关注 ——
        const PD_USER_KEY = 'pd_current_user';
        function pdGetUser() {{ return localStorage.getItem(PD_USER_KEY) || ''; }}
        function pdNotesKey(user) {{ return 'pd_notes::' + (user || 'guest'); }}
        function pdFollowKey(user) {{ return 'pd_follow::' + (user || 'guest'); }}
        function pdLoadNotes(user) {{
            try {{ return JSON.parse(localStorage.getItem(pdNotesKey(user)) || '{{}}'); }}
            catch (e) {{ return {{}}; }}
        }}
        function pdSaveNotes(user, notes) {{ localStorage.setItem(pdNotesKey(user), JSON.stringify(notes)); }}
        function pdLoadFollow(user) {{
            try {{ return JSON.parse(localStorage.getItem(pdFollowKey(user)) || '[]'); }}
            catch (e) {{ return []; }}
        }}
        function pdSaveFollow(user, list) {{ localStorage.setItem(pdFollowKey(user), JSON.stringify(list)); }}

        function refreshUserUI() {{
            const user = pdGetUser();
            ['epUserBadge','notesPanelUser'].forEach(id => {{
                const el = document.getElementById(id);
                if (!el) return;
                el.textContent = user ? ('@' + user) : '未登录（游客模式）';
                el.dataset.logged = user ? '1' : '0';
            }});
            const fb = document.getElementById('followBtn');
            const follows = new Set(pdLoadFollow(user));
            const on = follows.has(EP_KEY);
            fb.dataset.active = on ? 'true' : 'false';
            fb.textContent = on ? '★ 已加入关注榜' : '☆ 加入我的关注榜';
        }}

        function toggleFollow() {{
            const user = pdGetUser();
            const list = pdLoadFollow(user);
            const idx = list.indexOf(EP_KEY);
            if (idx >= 0) list.splice(idx, 1); else list.push(EP_KEY);
            pdSaveFollow(user, list);
            refreshUserUI();
        }}
        window.toggleFollow = toggleFollow;

        // 随笔抽屉
        const editor = document.getElementById('notesEditor');
        const statusEl = document.getElementById('notesPanelStatus');
        const fabDot = document.getElementById('notesFabDot');

        function loadEpNote() {{
            const user = pdGetUser();
            const notes = pdLoadNotes(user);
            const cur = notes[EP_KEY] || {{}};
            editor.value = cur.text || '';
            fabDot.style.display = (cur.text && cur.text.trim()) ? 'inline' : 'none';
        }}
        let saveTimer = null;
        editor.addEventListener('input', () => {{
            statusEl.textContent = '编辑中…';
            clearTimeout(saveTimer);
            saveTimer = setTimeout(() => {{
                const user = pdGetUser();
                const notes = pdLoadNotes(user);
                notes[EP_KEY] = {{
                    text: editor.value,
                    epTitle: EP_TITLE,
                    updatedAt: Date.now()
                }};
                pdSaveNotes(user, notes);
                statusEl.textContent = '✔ 已保存 ' + new Date().toLocaleTimeString('zh-CN', {{hour12:false}});
                fabDot.style.display = editor.value.trim() ? 'inline' : 'none';
            }}, 350);
        }});
        function toggleNotesPanel() {{
            const panel = document.getElementById('notesPanel');
            const now = panel.dataset.open === '1';
            panel.dataset.open = now ? '0' : '1';
            panel.setAttribute('aria-hidden', now ? 'true' : 'false');
        }}
        window.toggleNotesPanel = toggleNotesPanel;

        refreshUserUI();
        loadEpNote();
        window.addEventListener('storage', () => {{ refreshUserUI(); loadEpNote(); }});
    </script>
</body>
</html>
"""

            with open(ep_path, "w", encoding="utf-8") as f:
                f.write(page_html)

        # ---- 2) 渲染索引页 index.html ----
        index_html = self._html_head(site_title, len(episodes), is_ranking=True)

        # Hero + Top N 卡片网格（链接到 episodes/episode_NN.html）
        if episodes:
            index_html += '        <div class="ranking-hero">\n'
            index_html += (
                f'            <div class="hero-row">\n'
                f'                <div class="ranking-badge">🔥 '
                f'{_esc(ranking_label)}</div>\n'
                f'                <div class="user-area">\n'
                f'                    <span id="heroUserBadge" class="user-badge">未登录</span>\n'
                f'                    <a class="login-btn" href="login.html">登录 / 切换</a>\n'
                f'                </div>\n'
                f'            </div>\n'
            )
            index_html += (
                f'            <div class="ranking-update">'
                f'更新时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}'
                f'</div>\n'
            )
            index_html += (
                '            <div class="filter-row">\n'
                '                <button class="filter-btn" id="filterAll" data-active="true" onclick="setFilter(\'all\')">全部 Top 10</button>\n'
                '                <button class="filter-btn" id="filterFollow" onclick="setFilter(\'follow\')">⭐ 我的关注榜</button>\n'
                '                <span class="filter-tip">在每集详情页右上角点 ☆ 即可关注 / 取消关注</span>\n'
                '            </div>\n'
            )
            index_html += '            <div class="ranking-grid" id="rankingGrid">\n'
            for ep in episodes:
                rank = ep.get("rank", 0)
                title_ = ep.get("title", "")
                pod = ep.get("podcast_title", "")
                dur = ep.get("duration_minutes", 0)
                guests = ep.get("guests", [])
                guest_str = "、".join(guests[:2]) if guests else ""
                href = f"episodes/episode_{rank:02d}.html"
                rank_class = "rank-top" if rank <= 3 else "rank-rest"

                # —— 一句话速览：优先用 summary_points[0].lead，再退到 summary 首句 ——
                lead_text = ""
                sps = ep.get("summary_points") or []
                if sps:
                    lead_text = (sps[0].get("lead") or sps[0].get("content") or "").strip()
                if not lead_text:
                    lead_text = (ep.get("summary") or "").strip()
                # 取首段、限长，避免卡片过长（CSS 控制最多 3 行，这里宽容一些）
                lead_text = lead_text.replace("\r\n", "\n").split("\n\n")[0].split("\n")[0]
                if len(lead_text) > 160:
                    lead_text = lead_text[:158].rstrip() + "…"

                # —— 核心要点：取 key_points 前 3 条，去掉时间码前缀 ——
                kps_raw = ep.get("key_points") or []
                bullets: list[str] = []
                for kp in kps_raw:
                    if not isinstance(kp, str):
                        continue
                    s = kp.strip()
                    if not s:
                        continue
                    # 去掉形如 [00:05:09] / [05:09] 前缀
                    if s.startswith("["):
                        rb = s.find("]")
                        if rb != -1:
                            s = s[rb + 1:].strip()
                    s = s.replace("\n", " ").strip()
                    if not s:
                        continue
                    if len(s) > 80:
                        s = s[:78].rstrip() + "…"
                    bullets.append(s)
                    if len(bullets) >= 3:
                        break

                tags = ep.get("tags") or []
                tag_html = ""
                if tags:
                    tag_html = '                        <div class="ranking-tags">'
                    for t in tags[:4]:
                        tag_html += f'<span class="ranking-tag">{_esc(str(t))}</span>'
                    tag_html += '</div>\n'

                lead_html = (
                    f'                        <div class="ranking-lead">{_esc(lead_text)}</div>\n'
                    if lead_text else ""
                )

                bullets_html = ""
                if bullets:
                    bullets_html = '                        <ul class="ranking-bullets">\n'
                    for b in bullets:
                        bullets_html += (
                            f'                            <li>{_esc(b)}</li>\n'
                        )
                    bullets_html += '                        </ul>\n'

                index_html += (
                    f'                <a class="ranking-item {rank_class}" href="{href}" data-epkey="episode_{rank:02d}">\n'
                    f'                    <div class="ranking-num">{rank:02d}</div>\n'
                    f'                    <div class="ranking-info">\n'
                    f'                        <div class="ranking-title">{_esc(title_)}</div>\n'
                    f'                        <div class="ranking-meta">📻 {_esc(pod)}'
                    f' · ⏱ {dur:.0f} 分钟'
                    + (f' · 🎤 {_esc(guest_str)}' if guest_str else "")
                    + '</div>\n'
                    + lead_html
                    + bullets_html
                    + tag_html
                    + f'                        <div class="ranking-cta">查看详细解析 →</div>\n'
                    f'                    </div>\n'
                    f'                </a>\n'
                )
            index_html += '            </div>\n        </div>\n'

        # —— 我的随笔（前端 localStorage 渲染，无服务器） ——
        index_html += """
        <div class="card notes-card" id="myNotesCard">
            <div class="notes-card-head">
                <h2>📝 我的随笔</h2>
                <div class="notes-card-meta">
                    <span id="notesUserBadge" class="user-badge">未登录</span>
                    <a class="notes-link" href="login.html">切换账号 →</a>
                </div>
            </div>
            <div id="myNotesList" class="my-notes-list">
                <div class="notes-empty">还没有任何随笔。点开任意一集，在右侧面板写下你的感想吧～</div>
            </div>
        </div>
"""

        index_html += f"""
        <div class="footer">
            报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} · Podcast Digest
        </div>
    </div>

    <script>
        // —— 用户/随笔/关注最小核心 ——
        const PD_USER_KEY = 'pd_current_user';
        function pdGetUser() {{ return localStorage.getItem(PD_USER_KEY) || ''; }}
        function pdNotesKey(user) {{ return 'pd_notes::' + (user || 'guest'); }}
        function pdFollowKey(user) {{ return 'pd_follow::' + (user || 'guest'); }}
        function pdLoadNotes(user) {{
            try {{ return JSON.parse(localStorage.getItem(pdNotesKey(user)) || '{{}}'); }}
            catch (e) {{ return {{}}; }}
        }}
        function pdLoadFollow(user) {{
            try {{ return JSON.parse(localStorage.getItem(pdFollowKey(user)) || '[]'); }}
            catch (e) {{ return []; }}
        }}

        function refreshUserBadges() {{
            const user = pdGetUser();
            ['heroUserBadge', 'notesUserBadge'].forEach(id => {{
                const el = document.getElementById(id);
                if (!el) return;
                el.textContent = user ? ('@' + user) : '未登录（游客模式）';
                el.dataset.logged = user ? '1' : '0';
            }});
        }}

        function setFilter(mode) {{
            const user = pdGetUser();
            const follows = new Set(pdLoadFollow(user));
            document.getElementById('filterAll').dataset.active = (mode === 'all') ? 'true' : 'false';
            document.getElementById('filterFollow').dataset.active = (mode === 'follow') ? 'true' : 'false';
            const items = document.querySelectorAll('#rankingGrid .ranking-item');
            let shown = 0;
            items.forEach(it => {{
                const key = it.dataset.epkey;
                const show = (mode === 'all') || follows.has(key);
                it.style.display = show ? '' : 'none';
                if (show) shown++;
            }});
            const tip = document.querySelector('.filter-tip');
            if (mode === 'follow') {{
                tip.textContent = shown ? `已为你筛选 ${{shown}} 集关注内容` :
                    (user ? '你还没有关注任何一集，进入详情页点 ☆ 即可加入关注榜' :
                            '请先登录，再进入详情页点 ☆ 即可加入关注榜');
            }} else {{
                tip.textContent = '在每集详情页右上角点 ☆ 即可关注 / 取消关注';
            }}
        }}

        function renderMyNotes() {{
            const user = pdGetUser();
            const listEl = document.getElementById('myNotesList');
            const notes = pdLoadNotes(user);
            const items = Object.entries(notes)
                .filter(([k, v]) => v && v.text && v.text.trim())
                .sort((a, b) => (b[1].updatedAt || 0) - (a[1].updatedAt || 0));
            if (!items.length) {{
                listEl.innerHTML = '<div class="notes-empty">还没有任何随笔。点开任意一集，在右侧面板写下你的感想吧～</div>';
                return;
            }}
            listEl.innerHTML = items.map(([epKey, n]) => {{
                const time = new Date(n.updatedAt || Date.now()).toLocaleString('zh-CN', {{hour12:false}});
                const title = (n.epTitle || epKey).replace(/</g,'&lt;');
                const text = (n.text || '').replace(/</g,'&lt;');
                const href = 'episodes/' + epKey + '.html';
                return `<a class="my-note-item" href="${{href}}">
                    <div class="my-note-head">
                        <span class="my-note-title">${{title}}</span>
                        <span class="my-note-time">${{time}}</span>
                    </div>
                    <div class="my-note-text">${{text}}</div>
                </a>`;
            }}).join('');
        }}

        refreshUserBadges();
        renderMyNotes();
        window.addEventListener('storage', () => {{
            refreshUserBadges();
            renderMyNotes();
            // 当前若处于关注榜模式，重新筛一次
            if (document.getElementById('filterFollow').dataset.active === 'true') setFilter('follow');
        }});
        window.setFilter = setFilter;
    </script>
</body>
</html>
"""

        index_path = os.path.join(self.output_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)

        # —— 写出 login.html ——
        self._write_login_page()

        print(f"榜单首页已生成: {index_path}")
        print(f"已生成 {len(episodes)} 篇独立详细页 -> {ep_dir}")
        return index_path

    # ========== 登录页（前端账号体系） ==========

    def _write_login_page(self) -> str:
        """生成简单的本地账号登录/注册页 login.html。
        - 数据完全保存在 localStorage 中（pd_users / pd_current_user）
        - 切换账号后，随笔自动按账号隔离
        """
        login_path = os.path.join(self.output_dir, "login.html")
        html_str = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>登录 · Podcast Digest</title>
<style>
:root { --accent:#ff5e3a; --bg:#fff7f2; --text:#333; }
* { box-sizing: border-box; }
body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: linear-gradient(135deg,#ffe9dc,#fff7f2); min-height:100vh;
  display:flex; align-items:center; justify-content:center; color:var(--text); }
.box { width: 360px; max-width: 92vw; background:#fff; border-radius: 18px;
  padding: 30px 28px; box-shadow: 0 12px 40px rgba(255,122,89,0.18); }
h1 { margin:0 0 6px; font-size: 20px; }
.sub { margin:0 0 18px; color:#888; font-size: 13px; }
label { display:block; font-size: 12px; color:#666; margin: 12px 0 4px; }
input { width:100%; padding: 9px 12px; border:1px solid #eee; border-radius: 10px;
  font-size: 14px; outline: none; transition: border .15s; }
input:focus { border-color: var(--accent); }
.btn { display:block; width:100%; margin-top: 16px; padding: 10px; border:0;
  border-radius: 10px; background: linear-gradient(135deg,#ff5e3a,#ff2a68);
  color:#fff; font-weight: 700; font-size: 14px; cursor: pointer;
  box-shadow: 0 4px 14px rgba(255,94,58,0.35); }
.btn.ghost { background: #fff; color: var(--accent); border: 1px solid var(--accent);
  box-shadow: none; }
.row { display:flex; gap:8px; }
.row .btn { margin-top: 0; }
.tip { margin-top: 14px; font-size: 12px; color:#999; text-align:center; }
.user-list { margin-top: 14px; max-height: 120px; overflow:auto; border:1px dashed #f0d4c4; border-radius:10px; padding:6px; }
.user-item { display:flex; justify-content:space-between; align-items:center;
  padding:6px 8px; border-radius:6px; }
.user-item:hover { background: #fff7f2; }
.user-item button { background:none; border:0; color:var(--accent); cursor:pointer; font-size:12px; }
.current { font-weight:700; color: var(--accent); }
.back { display:block; text-align:center; margin-top: 14px; font-size: 12px; color:#888; text-decoration:none; }
.back:hover { color: var(--accent); }
</style>
</head>
<body>
<div class="box">
  <h1>👤 个人账号</h1>
  <p class="sub">本地账号体系：账号、随笔、关注榜全部存在你这台设备上，不上传服务器。</p>

  <label>用户名（拼音/英文，2–20 位）</label>
  <input id="username" placeholder="例如 wsq" maxlength="20" autocomplete="off" />

  <label>口令（可选，仅本机校验）</label>
  <input id="password" type="password" placeholder="留空也可以直接使用" autocomplete="off" />

  <div class="row" style="margin-top:14px;">
    <button class="btn" onclick="doLogin()">登录 / 注册</button>
    <button class="btn ghost" onclick="doGuest()">游客模式</button>
  </div>

  <div class="user-list" id="userList"></div>
  <div class="tip" id="tip"></div>
  <a class="back" href="index.html">← 返回榜单首页</a>
</div>

<script>
const USERS_KEY = 'pd_users';
const CUR_KEY = 'pd_current_user';
function getUsers(){ try { return JSON.parse(localStorage.getItem(USERS_KEY)||'{}'); } catch(e){ return {}; } }
function setUsers(u){ localStorage.setItem(USERS_KEY, JSON.stringify(u)); }
function setCur(name){ if(name) localStorage.setItem(CUR_KEY, name); else localStorage.removeItem(CUR_KEY); }
function getCur(){ return localStorage.getItem(CUR_KEY) || ''; }

function tip(msg, ok){
  const t = document.getElementById('tip');
  t.textContent = msg;
  t.style.color = ok ? '#2e7d32' : '#c62828';
}

function doLogin(){
  const name = (document.getElementById('username').value || '').trim();
  const pwd = document.getElementById('password').value || '';
  if (!name || name.length < 2) return tip('用户名至少 2 位', false);
  if (!/^[a-zA-Z0-9_\\-]+$/.test(name)) return tip('用户名只能包含字母数字、下划线和短横线', false);
  const users = getUsers();
  if (users[name] === undefined) {
    users[name] = { pwd: pwd, createdAt: Date.now() };
    setUsers(users);
    setCur(name);
    tip('注册并登录成功：' + name, true);
  } else {
    if (users[name].pwd && users[name].pwd !== pwd) return tip('口令错误', false);
    setCur(name);
    tip('欢迎回来，' + name, true);
  }
  renderList();
  setTimeout(()=>{ location.href='index.html'; }, 600);
}

function doGuest(){
  setCur('');
  tip('已切换为游客模式', true);
  setTimeout(()=>{ location.href='index.html'; }, 400);
}

function switchTo(name){ setCur(name); renderList(); tip('已切换为：' + name, true); }
function removeUser(name){
  if (!confirm('删除账号 ' + name + ' 吗？该账号下的随笔也会一并删除。')) return;
  const users = getUsers();
  delete users[name];
  setUsers(users);
  localStorage.removeItem('pd_notes::' + name);
  localStorage.removeItem('pd_follow::' + name);
  if (getCur() === name) setCur('');
  renderList();
}
function renderList(){
  const users = getUsers();
  const cur = getCur();
  const el = document.getElementById('userList');
  const names = Object.keys(users).sort();
  if (!names.length) { el.style.display='none'; return; } else el.style.display='block';
  el.innerHTML = '<div style="font-size:12px;color:#888;padding:4px 8px;">本机账号：</div>' +
    names.map(n => `<div class="user-item">
      <span class="${n===cur?'current':''}">${n===cur?'● ':''}${n}</span>
      <span>
        ${n===cur?'<span style="color:#888;font-size:12px;">当前</span>':`<button onclick="switchTo('${n}')">切换</button>`}
        <button onclick="removeUser('${n}')">删除</button>
      </span>
    </div>`).join('');
}
renderList();
</script>
</body>
</html>
"""
        with open(login_path, "w", encoding="utf-8") as f:
            f.write(html_str)
        return login_path

    # ========== HTML（旧：单文件，保留给 episode/podcast 子命令） ==========

    def generate_html(self, data: dict, md_path: str) -> str:
        """生成 HTML 报告（带可点击播放、倍速控制、跳回原始界面）"""
        podcast_title = data.get("podcast_title", "播客")
        episodes = data.get("episodes", [])
        is_ranking = bool(data.get("is_ranking"))
        ranking_label = data.get("ranking_label", "")

        # 把每集的关键数据传给前端 JS（用于音频播放）
        episodes_payload = []
        for i, ep in enumerate(episodes):
            episodes_payload.append({
                "index": i,
                "audio_url": ep.get("audio_url", ""),
                "episode_url": ep.get("episode_url", ""),
                "title": ep.get("title", ""),
            })
        episodes_json = json.dumps(episodes_payload, ensure_ascii=False)

        html = self._html_head(podcast_title, len(episodes), is_ranking=is_ranking)

        # ========= 榜单模式：Top N Hero =========
        if is_ranking and episodes:
            html += '        <div class="ranking-hero">\n'
            html += f'            <div class="ranking-badge">🔥 {_esc(ranking_label or f"热门榜 Top {len(episodes)}")}</div>\n'
            html += '            <div class="ranking-grid">\n'
            for ep in episodes:
                rank = ep.get("rank", 0)
                title_ = ep.get("title", "")
                pod = ep.get("podcast_title", "")
                dur = ep.get("duration_minutes", 0)
                ep_url = ep.get("episode_url", "")
                guests = ep.get("guests", [])
                guest_str = "、".join(guests[:2]) if guests else ""
                anchor = f"#ep-{rank}"
                rank_class = "rank-top" if rank <= 3 else "rank-rest"
                html += (
                    f'                <a class="ranking-item {rank_class}" href="{anchor}">\n'
                    f'                    <div class="ranking-num">{rank:02d}</div>\n'
                    f'                    <div class="ranking-info">\n'
                    f'                        <div class="ranking-title">{_esc(title_)}</div>\n'
                    f'                        <div class="ranking-meta">📻 {_esc(pod)}'
                    f' · ⏱ {dur:.0f} 分钟'
                    + (f' · 🎤 {_esc(guest_str)}' if guest_str else "")
                    + '</div>\n'
                    f'                    </div>\n'
                    f'                </a>\n'
                )
            html += '            </div>\n        </div>\n'

        # 总体概述
        overview = data.get("overview", "")
        if overview:
            html += f"""
        <div class="card">
            <h2>📋 总体概述</h2>
            <p>{_esc(overview)}</p>
        </div>
"""

        common_themes = data.get("common_themes", [])
        if common_themes:
            html += """
        <div class="card">
            <h2>🏷️ 共同主题</h2>
            <div class="themes">
"""
            for theme in common_themes:
                html += (
                    f'                <span class="theme-tag">'
                    f'{_esc(theme["tag"])}'
                    f'<span class="count">{theme["count"]}</span></span>\n'
                )
            html += "            </div>\n        </div>\n"

        cross_insights = data.get("cross_episode_insights", [])
        if cross_insights:
            html += """
        <div class="card">
            <h2>💡 跨集洞察</h2>
            <ul class="insights">
"""
            for insight in cross_insights:
                html += f"                <li>{_esc(insight)}</li>\n"
            html += "            </ul>\n        </div>\n"

        # 各集详细
        if episodes:
            section_title = "📝 各集详细解析" if is_ranking else "📝 各集详细总结"
            html += f'        <h2 class="section-title">{section_title}</h2>\n'
            for i, ep in enumerate(episodes, 1):
                html += self._render_episode_card(i, ep, is_ranking=is_ranking)

        # 浮动音频播放器
        html += """
        <div class="audio-bar" id="audioBar">
            <div class="audio-bar-inner">
                <div class="audio-meta">
                    <div class="audio-title" id="audioTitle">未在播放</div>
                    <div class="audio-current" id="audioCurrent">点击章节速览中的时间码即可播放</div>
                </div>
                <audio id="audioPlayer" controls preload="none" style="flex:1; min-width: 240px;"></audio>
                <div class="speed-group">
                    <span class="speed-label">倍速</span>
                    <button class="speed-btn" data-speed="0.75">0.75×</button>
                    <button class="speed-btn" data-speed="1" data-active="true">1×</button>
                    <button class="speed-btn" data-speed="1.25">1.25×</button>
                    <button class="speed-btn" data-speed="1.5">1.5×</button>
                    <button class="speed-btn" data-speed="2">2×</button>
                </div>
            </div>
        </div>
"""

        # 页脚
        html += f"""
        <div class="footer">
            报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} · Podcast Digest
        </div>
    </div>
"""

        # JS 控制逻辑
        html += f"""
    <script>
        const EPISODES = {episodes_json};
        const audio = document.getElementById('audioPlayer');
        const audioTitle = document.getElementById('audioTitle');
        const audioCurrent = document.getElementById('audioCurrent');
        let currentEpisode = -1;

        function playSegment(epIndex, seconds, contentText) {{
            const ep = EPISODES[epIndex];
            if (!ep || !ep.audio_url) {{
                alert('该集没有可用的音频地址');
                return;
            }}
            if (currentEpisode !== epIndex) {{
                audio.src = ep.audio_url;
                currentEpisode = epIndex;
                audioTitle.textContent = ep.title || '正在播放';
            }}
            const start = () => {{
                try {{ audio.currentTime = seconds; }} catch (e) {{}}
                audio.play().catch(() => {{}});
                audioCurrent.textContent = contentText || '';
            }};
            if (audio.readyState >= 1) {{
                start();
            }} else {{
                audio.addEventListener('loadedmetadata', start, {{ once: true }});
                audio.load();
            }}
            // 滚动到播放器
            document.getElementById('audioBar').scrollIntoView({{ behavior: 'smooth', block: 'end' }});
        }}

        // 倍速按钮
        document.querySelectorAll('.speed-btn').forEach(btn => {{
            btn.addEventListener('click', () => {{
                const speed = parseFloat(btn.dataset.speed);
                audio.playbackRate = speed;
                document.querySelectorAll('.speed-btn').forEach(b => b.removeAttribute('data-active'));
                btn.setAttribute('data-active', 'true');
            }});
        }});

        // 暴露给 onclick 调用
        window.playSegment = playSegment;
    </script>
</body>
</html>
"""

        html_path = os.path.join(self.output_dir, f"{podcast_title}_播客总结.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"HTML 报告已生成: {html_path}")
        return html_path

    # ========== HTML 局部 ==========

    def _render_episode_card(self, idx: int, ep: dict, is_ranking: bool = False) -> str:
        title = ep.get("title", "未知")
        podcast = ep.get("podcast_title", "")
        duration = ep.get("duration_minutes", 0)
        pub_date = (ep.get("pub_date", "") or "")[:10]
        episode_url = ep.get("episode_url", "")
        audio_url = ep.get("audio_url", "")
        ep_index = idx - 1  # JS 中 EPISODES 索引
        rank = ep.get("rank", idx) if is_ranking else None

        # 嘉宾标签
        guests = ep.get("guests", [])
        guests_html = ""
        if guests:
            guests_html = (
                '<span>🎤 ' + _esc("、".join(guests)) + "</span>"
            )

        # 头部按钮（跳回小宇宙 + 从头听）
        header_actions = []
        if episode_url:
            header_actions.append(
                f'<a class="action-btn primary" href="{_esc(episode_url)}" target="_blank" rel="noopener">↗ 打开节目主页</a>'
            )
        if audio_url:
            header_actions.append(
                f'<button class="action-btn" onclick="playSegment({ep_index}, 0, \'从头开始\')">▶ 从头收听</button>'
            )
        actions_html = ""
        if header_actions:
            actions_html = '<div class="actions">' + "".join(header_actions) + "</div>"

        # 排名徽章 / 标题
        if is_ranking and rank:
            rank_html = f'<span class="rank-badge">TOP {rank:02d}</span>'
            anchor = f' id="ep-{rank}"'
            heading = f'{rank_html} {_esc(title)}'
        else:
            anchor = ""
            heading = f'{idx}. {_esc(title)}'

        out = f"""
        <div class="episode-card"{anchor}>
            <h3>{heading}</h3>
            <div class="episode-meta">
                <span>📻 {_esc(podcast)}</span>
                <span>⏱️ {duration:.0f} 分钟</span>
                <span>📅 {_esc(pub_date)}</span>
                {guests_html}
            </div>
            {actions_html}
"""

        # 内容概要：分点（每个点支持 title / lead / content 三层结构）
        summary_points = ep.get("summary_points", [])
        summary_text = ep.get("summary", "")
        if summary_points:
            out += '            <div class="summary">\n'
            out += '                <div class="summary-title">📌 内容概要</div>\n'
            out += '                <div class="summary-cards">\n'
            for idx, sp in enumerate(summary_points, 1):
                title_ = _esc(sp.get("title", ""))
                lead = _esc(sp.get("lead", ""))
                content = sp.get("content", "")
                # content 内的换行渲染成 <br>，保持多段落结构
                content_html = "<br>".join(_esc(p) for p in content.split("\n") if p.strip() != "")
                lead_html = (
                    f'<div class="summary-card-lead">{lead}</div>' if lead else ""
                )
                out += (
                    '                    <div class="summary-card">\n'
                    f'                        <div class="summary-card-head">'
                    f'<span class="summary-card-index">{idx:02d}</span>'
                    f'<span class="summary-card-title">{title_}</span></div>\n'
                    f'                        {lead_html}\n'
                    f'                        <div class="summary-card-body">{content_html}</div>\n'
                    "                    </div>\n"
                )
            out += "                </div>\n            </div>\n"
        elif summary_text:
            out += (
                '            <div class="summary">\n'
                '                <div class="summary-title">📌 内容概要</div>\n'
                f'                <p>{_esc(summary_text)}</p>\n'
                "            </div>\n"
            )

        # 章节速览（合并 关键要点 + 时间轴）
        timeline = ep.get("timeline", [])
        if timeline:
            out += """            <div class="timeline">
                <h4>🎧 章节速览（点击时间码跳转播放）</h4>
                <div class="timeline-list">
"""
            for item in timeline:
                t = item.get("time", "")
                content = item.get("content", "")
                seconds = _time_to_seconds(t)
                # 用 JS 字符串字面量；通过 json.dumps 安全转义
                content_js = json.dumps(content, ensure_ascii=False)
                onclick = (
                    f"playSegment({ep_index}, {seconds}, {content_js})"
                    if audio_url
                    else "alert('该集没有可用的音频地址')"
                )
                out += f"""                    <div class="timeline-item" onclick="{_esc(onclick)}" role="button" tabindex="0">
                        <span class="timeline-time">▶ {_esc(t)}</span>
                        <span class="timeline-content">{_esc(content)}</span>
                    </div>
"""
            out += "                </div>\n            </div>\n"

        # 标签
        tags = ep.get("tags", [])
        if tags:
            out += '            <div class="tags">\n'
            for tag in tags:
                out += f'                <span class="tag">{_esc(tag)}</span>\n'
            out += "            </div>\n"

        out += "        </div>\n"
        return out

    def _html_head(
        self,
        podcast_title: str,
        ep_count: int,
        is_ranking: bool = False,
        sub_override: str = "",
    ) -> str:
        """HTML 头部 + CSS"""
        if sub_override:
            sub_title = sub_override
        else:
            sub_title = (
                f"榜单 Top {ep_count} · 实时热门内容速览" if is_ranking
                else f"播客总结报告 · 共 {ep_count} 期"
            )
        head_emoji = "🔥" if is_ranking else "🎙️"
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(podcast_title)} — 播客总结报告</title>
    <style>
        :root {{
            --bg: #f4f6fa;
            --card-bg: #ffffff;
            --text: #2c3e50;
            --text-secondary: #6b7785;
            --accent: #4a6fa5;
            --accent-2: #6b8cba;
            --accent-light: #e8eef5;
            --border: #e3e8f0;
            --tag-bg: #f0f4f8;
            --tag-text: #4a6fa5;
            --success: #2ecc71;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.7;
            padding: 20px;
            padding-bottom: 140px; /* 给浮动播放器留位 */
        }}
        .container {{ max-width: 920px; margin: 0 auto; }}

        .header {{
            background: linear-gradient(135deg, #4a6fa5, #6b8cba);
            color: white;
            padding: 40px 30px;
            border-radius: 16px;
            margin-bottom: 24px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(74, 111, 165, 0.18);
        }}
        .header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 8px; }}
        .header .meta {{ font-size: 14px; opacity: 0.9; }}

        .card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }}
        .card h2 {{
            font-size: 18px;
            color: var(--accent);
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--accent-light);
        }}

        .themes {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
        .theme-tag {{
            background: var(--tag-bg);
            color: var(--tag-text);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
        }}
        .theme-tag .count {{
            background: var(--accent);
            color: white;
            border-radius: 10px;
            padding: 1px 6px;
            font-size: 11px;
            margin-left: 4px;
        }}

        .insights {{ margin-top: 12px; padding-left: 18px; }}
        .insights li {{ margin-bottom: 6px; color: var(--text-secondary); font-size: 14px; }}

        /* ============ 榜单 Hero / 排名徽章 ============ */
        .ranking-hero {{
            background: linear-gradient(135deg, #fff5e6 0%, #ffe8d6 50%, #ffe1f0 100%);
            border-radius: 16px;
            padding: 22px 24px 24px;
            margin-bottom: 22px;
            box-shadow: 0 4px 16px rgba(255, 122, 89, 0.15);
            border: 1px solid rgba(255, 138, 101, 0.18);
        }}
        .ranking-badge {{
            display: inline-block;
            background: linear-gradient(135deg, #ff6b6b, #ff9966);
            color: #fff;
            font-weight: 700;
            font-size: 15px;
            letter-spacing: 0.6px;
            padding: 6px 14px;
            border-radius: 20px;
            margin-bottom: 14px;
            box-shadow: 0 2px 8px rgba(255, 107, 107, 0.3);
        }}
        .ranking-grid {{
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: 14px;
        }}
        @media (min-width: 1100px) {{
            .ranking-grid {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }}
        }}
        .ranking-item {{
            display: flex;
            align-items: flex-start;
            gap: 14px;
            background: rgba(255, 255, 255, 0.85);
            border-radius: 12px;
            padding: 14px 16px;
            text-decoration: none;
            color: var(--text);
            transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
            border: 1px solid rgba(255, 138, 101, 0.12);
        }}
        .ranking-item:hover {{
            transform: translateY(-2px);
            background: #fff;
            box-shadow: 0 6px 18px rgba(255, 122, 89, 0.18);
        }}
        .ranking-num {{
            flex-shrink: 0;
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            font-weight: 800;
            color: #fff;
            font-family: 'SF Mono', 'Menlo', monospace;
        }}
        .ranking-item.rank-top .ranking-num {{
            background: linear-gradient(135deg, #ff5e3a, #ff2a68);
            box-shadow: 0 3px 10px rgba(255, 94, 58, 0.4);
        }}
        .ranking-item.rank-rest .ranking-num {{
            background: linear-gradient(135deg, #6b8cba, #4a6fa5);
        }}
        .ranking-info {{ flex: 1; min-width: 0; }}
        .ranking-title {{
            font-size: 15px;
            font-weight: 700;
            color: var(--text);
            line-height: 1.4;
            margin-bottom: 4px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .ranking-meta {{
            font-size: 12px;
            color: var(--text-secondary);
            line-height: 1.5;
        }}
        .rank-badge {{
            display: inline-block;
            background: linear-gradient(135deg, #ff5e3a, #ff2a68);
            color: #fff;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.6px;
            padding: 3px 10px;
            border-radius: 12px;
            margin-right: 8px;
            vertical-align: middle;
            box-shadow: 0 2px 6px rgba(255, 94, 58, 0.3);
        }}

        .ranking-update {{
            font-size: 12px;
            color: #b8552c;
            margin-bottom: 12px;
            opacity: 0.85;
        }}
        .ranking-cta {{
            font-size: 12px;
            color: #ff5e3a;
            margin-top: 10px;
            font-weight: 600;
            letter-spacing: 0.4px;
        }}

        .ranking-lead {{
            margin-top: 8px;
            font-size: 13.5px;
            line-height: 1.65;
            color: #444;
            background: rgba(255, 247, 240, 0.8);
            border-left: 3px solid #ffb199;
            padding: 8px 12px;
            border-radius: 6px;
        }}
        .ranking-bullets {{
            margin: 10px 0 0;
            padding: 0;
            list-style: none;
        }}
        .ranking-bullets li {{
            position: relative;
            padding: 3px 0 3px 20px;
            font-size: 13px;
            line-height: 1.55;
            color: #333;
        }}
        .ranking-bullets li::before {{
            content: "▸";
            position: absolute;
            left: 4px;
            top: 3px;
            color: #ff5e3a;
            font-weight: 700;
        }}
        .ranking-tags {{
            margin-top: 10px;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }}
        .ranking-tag {{
            font-size: 11px;
            color: #b8552c;
            background: #fff3ec;
            border: 1px solid #ffd3bf;
            padding: 2px 8px;
            border-radius: 10px;
            line-height: 1.6;
        }}

        .back-bar {{
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .back-btn {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #fff;
            color: var(--accent);
            border: 1px solid var(--accent);
            padding: 7px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            transition: all .15s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .back-btn:hover {{
            background: var(--accent);
            color: #fff;
            transform: translateX(-2px);
        }}
        .follow-btn {{
            background: #fff;
            color: #b8552c;
            border: 1px solid #ffd3bf;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            cursor: pointer;
            font-weight: 600;
            transition: all .15s;
        }}
        .follow-btn[data-active="true"] {{
            background: linear-gradient(135deg, #ff5e3a, #ff2a68);
            color: #fff;
            border-color: transparent;
            box-shadow: 0 3px 10px rgba(255, 94, 58, 0.35);
        }}
        .follow-btn:hover {{ transform: translateY(-1px); }}
        .ep-user-badge {{
            margin-left: auto;
            font-size: 12px;
            color: #888;
            background: #f6f6f6;
            border: 1px solid #eee;
            border-radius: 12px;
            padding: 4px 10px;
        }}
        .ep-user-badge[data-logged="1"] {{ color: var(--accent); border-color: #ffd3bf; background: #fff7f2; }}
        .ep-login-link {{ font-size: 12px; color: #888; text-decoration: none; }}
        .ep-login-link:hover {{ color: var(--accent); }}

        /* —— 首页卡片等宽 + 自适应高 + 内容温和裁剪 —— */
        .ranking-grid {{ width: 100%; align-items: stretch; }}
        .ranking-grid > .ranking-item {{ min-width: 0; width: 100%; box-sizing: border-box; }}
        .ranking-item {{ min-height: 200px; }}
        .ranking-info {{
            display: flex; flex-direction: column;
            min-width: 0; flex: 1 1 0;
            overflow: hidden;
            overflow-wrap: anywhere;
            word-break: break-word;
        }}
        .ranking-info > * {{ min-width: 0; max-width: 100%; }}
        .ranking-cta {{ margin-top: auto; }}
        .ranking-title, .ranking-meta {{
            overflow-wrap: anywhere; word-break: break-word;
        }}
        .ranking-lead {{
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
            overflow-wrap: anywhere;
            word-break: break-word;
        }}
        .ranking-bullets {{ max-width: 100%; }}
        .ranking-bullets li {{
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            overflow-wrap: anywhere;
            word-break: break-word;
        }}
        .ranking-tags {{ max-width: 100%; }}

        /* —— 首页 hero/筛选/用户区 —— */
        .hero-row {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 10px; flex-wrap: wrap;
        }}
        .user-area {{ display: flex; align-items: center; gap: 8px; }}
        .user-badge {{
            font-size: 12px; color: #888; background: #f6f6f6;
            border: 1px solid #eee; border-radius: 12px; padding: 4px 10px;
        }}
        .user-badge[data-logged="1"] {{ color: var(--accent); border-color: #ffd3bf; background: #fff7f2; }}
        .login-btn {{
            font-size: 12px; color: #fff; background: linear-gradient(135deg,#ff5e3a,#ff2a68);
            padding: 6px 12px; border-radius: 14px; text-decoration: none; font-weight: 600;
            box-shadow: 0 2px 8px rgba(255, 94, 58, 0.3);
        }}
        .login-btn:hover {{ transform: translateY(-1px); }}
        .filter-row {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 12px 0 4px; }}
        .filter-btn {{
            background: #fff; color: var(--accent); border: 1px solid #ffd3bf;
            border-radius: 14px; padding: 5px 14px; font-size: 12px; font-weight: 600;
            cursor: pointer; transition: all .15s;
        }}
        .filter-btn[data-active="true"] {{
            background: linear-gradient(135deg,#ff5e3a,#ff2a68);
            color: #fff; border-color: transparent;
            box-shadow: 0 2px 8px rgba(255, 94, 58, 0.3);
        }}
        .filter-tip {{ font-size: 12px; color: #888; }}

        /* —— 我的随笔区域（首页） —— */
        .notes-card-head {{
            display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;
        }}
        .notes-card-meta {{ display: flex; align-items: center; gap: 8px; }}
        .notes-link {{ font-size: 12px; color: var(--accent); text-decoration: none; }}
        .notes-link:hover {{ text-decoration: underline; }}
        .my-notes-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .my-note-item {{
            display: block; padding: 10px 12px; border-radius: 10px;
            background: #fff7f2; border: 1px solid #ffe1ce; text-decoration: none; color: #333;
            transition: all .15s;
        }}
        .my-note-item:hover {{ background: #ffeede; transform: translateX(2px); }}
        .my-note-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }}
        .my-note-title {{ font-size: 13.5px; font-weight: 700; color: var(--accent);
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex:1; }}
        .my-note-time {{ font-size: 11.5px; color: #aaa; flex-shrink: 0; }}
        .my-note-text {{
            margin-top: 4px; font-size: 13px; color: #555; line-height: 1.55;
            display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
        }}
        .notes-empty {{ font-size: 13px; color: #999; padding: 14px 0; text-align: center; }}

        /* —— 详情页右下浮动随笔抽屉 —— */
        .notes-fab {{
            position: fixed; right: 20px; bottom: 110px; z-index: 50;
            width: 52px; height: 52px; border-radius: 50%;
            background: linear-gradient(135deg,#ff5e3a,#ff2a68); color:#fff;
            border:0; font-size: 22px; cursor: pointer;
            box-shadow: 0 6px 20px rgba(255, 94, 58, 0.4); transition: transform .15s;
        }}
        .notes-fab:hover {{ transform: scale(1.05); }}
        .notes-fab > span {{
            position: absolute; top: 6px; right: 8px; font-size: 8px; color: #fff200;
        }}
        .notes-panel {{
            position: fixed; right: 0; top: 0; bottom: 0; width: 360px; max-width: 92vw;
            background: #fff; box-shadow: -10px 0 30px rgba(0,0,0,0.12); z-index: 60;
            transform: translateX(100%); transition: transform .25s ease;
            display: flex; flex-direction: column; padding: 16px;
        }}
        .notes-panel[data-open="1"] {{ transform: translateX(0); }}
        .notes-panel-head {{ display: flex; align-items: center; justify-content: space-between; }}
        .notes-panel-title {{ font-size: 15px; font-weight: 700; color: var(--accent); }}
        .notes-panel-close {{
            border:0; background: #f6f6f6; width: 28px; height: 28px;
            border-radius: 50%; cursor: pointer; font-size: 14px;
        }}
        .notes-panel-close:hover {{ background: #ffebe0; color: var(--accent); }}
        .notes-panel-meta {{ display: flex; align-items: center; gap: 8px; margin: 10px 0; }}
        .notes-panel-status {{ font-size: 11px; color: #888; }}
        .notes-editor {{
            flex: 1; width: 100%; border: 1px solid #eee; border-radius: 10px;
            padding: 10px 12px; font-size: 14px; line-height: 1.6; color: #333;
            resize: none; outline: none; font-family: inherit;
        }}
        .notes-editor:focus {{ border-color: var(--accent); }}
        .notes-panel-tip {{ font-size: 11px; color: #aaa; margin-top: 8px; }}

        .episode-card {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            border-left: 4px solid var(--accent);
        }}
        .episode-card h3 {{ font-size: 18px; color: var(--text); margin-bottom: 8px; }}
        .episode-meta {{
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 14px;
            display: flex;
            flex-wrap: wrap;
            gap: 6px 16px;
        }}

        .actions {{
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .action-btn {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 6px 14px;
            border-radius: 18px;
            border: 1px solid var(--accent);
            background: white;
            color: var(--accent);
            font-size: 13px;
            cursor: pointer;
            text-decoration: none;
            transition: all .15s;
        }}
        .action-btn:hover {{ background: var(--accent-light); }}
        .action-btn.primary {{
            background: var(--accent);
            color: white;
        }}
        .action-btn.primary:hover {{ background: #3d5d8a; }}

        .summary {{
            background: linear-gradient(180deg, var(--accent-light) 0%, #ffffff 100%);
            border-radius: 12px;
            padding: 18px 20px 20px;
            margin-bottom: 16px;
            font-size: 14px;
            border: 1px solid rgba(74, 111, 165, 0.12);
        }}
        .summary-title {{
            font-weight: 700;
            font-size: 16px;
            color: var(--accent);
            margin-bottom: 14px;
            letter-spacing: 0.5px;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }}
        .summary-card {{
            background: #ffffff;
            border-radius: 10px;
            padding: 14px 16px 16px;
            border-left: 4px solid var(--accent);
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }}
        .summary-card:hover {{
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(74, 111, 165, 0.12);
        }}
        .summary-card-head {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 6px;
        }}
        .summary-card-index {{
            display: inline-block;
            min-width: 30px;
            padding: 2px 8px;
            background: var(--accent);
            color: #fff;
            font-size: 12px;
            font-weight: 700;
            border-radius: 12px;
            text-align: center;
            letter-spacing: 0.5px;
        }}
        .summary-card-title {{
            font-size: 15px;
            font-weight: 700;
            color: var(--accent);
        }}
        .summary-card-lead {{
            font-size: 13px;
            color: #6c7a8b;
            margin: 4px 0 8px;
            font-style: italic;
            line-height: 1.6;
        }}
        .summary-card-body {{
            font-size: 14px;
            line-height: 1.85;
            color: var(--text);
            white-space: normal;
            word-break: break-word;
        }}
        @media (min-width: 900px) {{
            .summary-cards {{ grid-template-columns: 1fr 1fr; }}
            .summary-card:first-child,
            .summary-card:nth-child(2) {{ grid-column: span 1; }}
        }}

        .timeline {{ margin-bottom: 16px; }}
        .timeline h4 {{ font-size: 14px; color: var(--accent); margin-bottom: 10px; }}
        .timeline-list {{ display: flex; flex-direction: column; gap: 4px; }}
        .timeline-item {{
            display: flex;
            gap: 12px;
            align-items: flex-start;
            padding: 8px 10px;
            font-size: 14px;
            border-radius: 8px;
            cursor: pointer;
            transition: background .15s;
        }}
        .timeline-item:hover {{ background: var(--accent-light); }}
        .timeline-item:focus {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
        .timeline-time {{
            background: var(--accent);
            color: white;
            padding: 3px 10px;
            border-radius: 4px;
            font-family: 'SF Mono', Menlo, monospace;
            font-size: 12px;
            white-space: nowrap;
            min-width: 78px;
            text-align: center;
            flex-shrink: 0;
            font-weight: 600;
        }}
        .timeline-item:hover .timeline-time {{ background: #3d5d8a; }}
        .timeline-content {{ color: var(--text); flex: 1; }}

        .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }}
        .tag {{
            background: var(--tag-bg);
            color: var(--tag-text);
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 12px;
        }}

        .footer {{
            text-align: center;
            color: var(--text-secondary);
            font-size: 12px;
            padding: 20px 0 10px;
        }}

        .section-title {{
            font-size: 20px;
            color: var(--accent);
            margin: 24px 0 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--accent-light);
        }}

        /* 浮动播放器 */
        .audio-bar {{
            position: fixed;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.97);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border-top: 1px solid var(--border);
            box-shadow: 0 -4px 20px rgba(0,0,0,0.08);
            z-index: 50;
            padding: 12px 20px;
        }}
        .audio-bar-inner {{
            max-width: 920px;
            margin: 0 auto;
            display: flex;
            gap: 16px;
            align-items: center;
            flex-wrap: wrap;
        }}
        .audio-meta {{ min-width: 180px; flex-shrink: 0; }}
        .audio-title {{ font-size: 13px; font-weight: 600; color: var(--text); }}
        .audio-current {{ font-size: 12px; color: var(--text-secondary); margin-top: 2px; }}
        .speed-group {{
            display: flex;
            gap: 4px;
            align-items: center;
            flex-wrap: wrap;
        }}
        .speed-label {{ font-size: 12px; color: var(--text-secondary); margin-right: 4px; }}
        .speed-btn {{
            background: white;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 4px 10px;
            border-radius: 14px;
            font-size: 12px;
            cursor: pointer;
            font-weight: 600;
            transition: all .15s;
        }}
        .speed-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
        .speed-btn[data-active="true"] {{
            background: var(--accent);
            border-color: var(--accent);
            color: white;
        }}

        @media (max-width: 640px) {{
            body {{ padding: 12px; padding-bottom: 200px; }}
            .header {{ padding: 24px 16px; }}
            .header h1 {{ font-size: 22px; }}
            .episode-card {{ padding: 16px; }}
            .audio-bar-inner {{ gap: 8px; }}
            .audio-meta {{ min-width: 100%; }}
            #audioPlayer {{ width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{head_emoji} {_esc(podcast_title)}</h1>
            <div class="meta">{sub_title}</div>
        </div>
"""
