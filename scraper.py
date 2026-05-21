"""
小宇宙播客爬取模块
通过 Playwright 渲染页面，从 __NEXT_DATA__ 中提取播客和单集信息
"""

import asyncio
import json
import re
import os
import hashlib
from typing import Optional
from playwright.async_api import async_playwright


class XiaoyuzhouScraper:
    """小宇宙播客数据爬取器"""

    BASE_URL = "https://www.xiaoyuzhoufm.com"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._context = None

    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/136.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )

    async def close(self):
        if self._browser:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = None
            self._context = None

    def _parse_url(self, url: str) -> tuple[str, str]:
        """解析小宇宙URL，返回 (类型, ID)

        支持的URL格式:
        - https://www.xiaoyuzhoufm.com/episode/{eid}
        - https://www.xiaoyuzhoufm.com/podcast/{pid}
        """
        url = url.strip().rstrip("/")
        patterns = [
            (r"xiaoyuzhoufm\.com/episode/([a-f0-9]+)", "episode"),
            (r"xiaoyuzhoufm\.com/episode/(\w+)", "episode"),
            (r"xiaoyuzhoufm\.com/podcast/([a-f0-9]+)", "podcast"),
            (r"xiaoyuzhoufm\.com/podcast/(\w+)", "podcast"),
        ]
        for pattern, type_ in patterns:
            m = re.search(pattern, url)
            if m:
                return type_, m.group(1)
        raise ValueError(f"无法解析URL: {url}")

    async def _fetch_next_data(self, url: str) -> dict:
        """获取页面的 __NEXT_DATA__ JSON 数据"""
        await self._ensure_browser()
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)

            next_data = await page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                if (el) return JSON.parse(el.textContent);
                return null;
            }""")

            if not next_data:
                raise ValueError(f"页面没有 __NEXT_DATA__: {url}")

            page_path = next_data.get("page", "")
            if page_path == "/404":
                raise ValueError(f"页面不存在 (404): {url}")

            return next_data.get("props", {}).get("pageProps", {})
        finally:
            await page.close()

    async def get_episode(self, episode_url_or_id: str) -> dict:
        """获取单集信息

        Args:
            episode_url_or_id: 单集URL或EID

        Returns:
            dict: 单集信息，包含 title, description, shownotes, audio_url, duration 等
        """
        if episode_url_or_id.startswith("http"):
            type_, eid = self._parse_url(episode_url_or_id)
            assert type_ == "episode", f"URL不是单集页面: {episode_url_or_id}"
        else:
            eid = episode_url_or_id

        url = f"{self.BASE_URL}/episode/{eid}"
        page_props = await self._fetch_next_data(url)

        episode = page_props.get("episode", {})
        if not episode:
            raise ValueError(f"未找到单集数据: {url}")

        return self._normalize_episode(episode)

    async def get_hot_episodes(self, limit: int = 5) -> list[dict]:
        """获取『中国区热门播客』Top N 的最新一期内容。

        因小宇宙网页未登录态几乎不渲染推荐内容，这里改用公开稳定的数据源：
          1) Apple Podcasts 中国区『热门节目』Top N （rss.applemarketingtools.com）
          2) iTunes Lookup API → feedUrl
          3) 解析 RSS 最新一集（标题、描述、shownotes、音频URL、时长、发布时间）

        返回字段与 _normalize_episode 保持兼容，可直接喂给 summarizer。

        Args:
            limit: 取榜单前几名，默认 5。

        Returns:
            list[dict]: 已按排名排列的 episode 列表，每项额外带 "rank" 字段。
        """
        import aiohttp
        import ssl

        # 部分公司/学校网络会拦截 HTTPS，先尝试 certifi，再退化到默认上下文
        ssl_ctx = None
        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ssl_ctx = ssl.create_default_context()

        connector = aiohttp.TCPConnector(ssl=ssl_ctx)

        async def safe_get(session, url, **kw):
            """对 SSLCertificateError 兜底关闭校验，仅用于公开榜单接口。"""
            try:
                return await session.get(url, **kw)
            except aiohttp.ClientConnectorCertificateError:
                # 关闭校验重试
                insecure_conn = aiohttp.TCPConnector(ssl=False)
                tmp_sess = aiohttp.ClientSession(connector=insecure_conn)
                resp = await tmp_sess.get(url, **kw)
                # 让 caller 用完后关闭
                resp._tmp_session = tmp_sess  # noqa
                return resp

        top_url = (
            f"https://rss.applemarketingtools.com/api/v2/cn/podcasts/top/"
            f"{max(limit, 10)}/podcasts.json"
        )

        async with aiohttp.ClientSession(connector=connector) as session:
            # 1) 拉 Top 榜
            try:
                resp = await session.get(top_url, timeout=20)
            except aiohttp.ClientConnectorCertificateError:
                print("  ⚠️ SSL 证书校验失败，关闭校验重试…")
                insecure = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
                resp = await insecure.get(top_url, timeout=20)
                if resp.status != 200:
                    await insecure.close()
                    raise ValueError(f"Apple Top 榜抓取失败: HTTP {resp.status}")
                top_data = await resp.json(content_type=None)
                resp.release()
                # 切换到 insecure session 完成后续所有请求
                session_to_use = insecure
            else:
                if resp.status != 200:
                    raise ValueError(f"Apple Top 榜抓取失败: HTTP {resp.status}")
                top_data = await resp.json(content_type=None)
                resp.release()
                session_to_use = session

            try:
                results = top_data.get("feed", {}).get("results", [])
                if not results:
                    raise ValueError("Apple Top 榜返回为空")

                episodes: list[dict] = []
                for rank, podcast in enumerate(results[:limit], 1):
                    pid = podcast.get("id")
                    p_name = podcast.get("name", "")
                    p_artist = podcast.get("artistName", "")
                    p_artwork = podcast.get("artworkUrl100", "")
                    p_url = podcast.get("url", "")
                    if not pid:
                        continue

                    print(f"  [Top {rank}] 抓取 «{p_name}» 最新一期…")

                    lookup_url = f"https://itunes.apple.com/lookup?id={pid}&entity=podcast&country=cn"
                    try:
                        async with session_to_use.get(lookup_url, timeout=15) as r2:
                            lookup_data = await r2.json(content_type=None)
                    except Exception as e:
                        print(f"    lookup 失败: {e}")
                        continue
                    lookup_results = lookup_data.get("results", [])
                    if not lookup_results:
                        print(f"    没有 lookup 结果")
                        continue
                    feed_url = lookup_results[0].get("feedUrl")
                    if not feed_url:
                        print(f"    没有 feedUrl")
                        continue

                    rss_headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                            "Version/17.0 Safari/605.1.15"
                        ),
                        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                    }
                    try:
                        async with session_to_use.get(
                            feed_url, timeout=60, headers=rss_headers, allow_redirects=True
                        ) as r3:
                            if r3.status != 200:
                                print(f"    RSS HTTP {r3.status}")
                                continue
                            raw = await r3.read()
                            # 用 BOM/headers 优先，否则按 UTF-8 兜底解码
                            try:
                                xml = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                xml = raw.decode("utf-8", errors="ignore")
                    except Exception as e:
                        print(f"    RSS 抓取失败 ({type(e).__name__}): {e}")
                        continue

                    ep = self._parse_first_rss_item(xml, p_name, p_artist, p_artwork, p_url)
                    if ep:
                        ep["rank"] = rank
                        episodes.append(ep)
                        print(f"    → {ep['title'][:50]}")
                    else:
                        print(f"    解析 RSS item 失败 (xml 长度={len(xml)})")

                    await asyncio.sleep(0.3)
            finally:
                if session_to_use is not session:
                    await session_to_use.close()

        if not episodes:
            raise ValueError("没有成功抓到任何热门单集")

        return episodes

    def _parse_first_rss_item(
        self, xml: str, podcast_name: str, podcast_artist: str,
        podcast_artwork: str, podcast_url: str,
    ) -> Optional[dict]:
        """从播客 RSS XML 里抽取最新一集 (<item>) 的关键信息。

        覆盖 itunes/podcast 标准字段：title / description / enclosure / itunes:duration / pubDate /
        itunes:summary / itunes:image。
        """
        m = re.search(r"<item>.*?</item>", xml, re.S)
        if not m:
            return None
        item = m.group(0)

        def grab(tag: str) -> str:
            # 兼容 CDATA 与普通文本
            cdata = re.search(
                rf"<{tag}[^>]*><!\[CDATA\[(.*?)\]\]></{tag}>", item, re.S
            )
            if cdata:
                return cdata.group(1).strip()
            plain = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S)
            if plain:
                return plain.group(1).strip()
            return ""

        title = grab("title")
        description = grab("description") or grab("itunes:summary")
        shownotes = grab("content:encoded") or description
        pub_date = grab("pubDate")
        guid = grab("guid")

        # 音频 enclosure
        enc = re.search(r'<enclosure[^>]*url=["\']([^"\']+)["\'][^>]*/?>', item)
        audio_url = enc.group(1) if enc else ""

        # 时长（itunes:duration 可能是 1:23:45 或 5025）
        duration_seconds = 0
        dur_str = grab("itunes:duration")
        if dur_str:
            if ":" in dur_str:
                parts = [int(x) for x in dur_str.split(":") if x.strip().isdigit()]
                if len(parts) == 3:
                    duration_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
                elif len(parts) == 2:
                    duration_seconds = parts[0] * 60 + parts[1]
            else:
                try:
                    duration_seconds = int(dur_str)
                except ValueError:
                    duration_seconds = 0

        # 单集图（fallback 用播客封面）
        img_match = re.search(r'<itunes:image[^>]*href=["\']([^"\']+)["\']', item)
        image = img_match.group(1) if img_match else podcast_artwork

        # eid：从音频 URL 中提取（小宇宙 CDN 一般含 /<eid>/）
        eid = ""
        if audio_url:
            eid_m = re.search(r"/([a-f0-9]{16,})/", audio_url)
            if eid_m:
                eid = eid_m.group(1)
        if not eid and guid:
            eid_m = re.search(r"([a-f0-9]{16,})", guid)
            if eid_m:
                eid = eid_m.group(1)

        return {
            "eid": eid,
            "title": title,
            "description": self._clean_html(description),
            "shownotes": self._clean_html(shownotes),
            "audio_url": audio_url,
            "media_key": "",
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_seconds / 60, 1) if duration_seconds else 0,
            "pub_date": pub_date,
            "podcast_title": podcast_name,
            "podcast_pid": "",
            "podcast_author": podcast_artist,
            "podcast_url": podcast_url,
            "image": image,
            "play_count": 0,
            "comment_count": 0,
            "clap_count": 0,
            "episode_url": podcast_url,  # 没有单集 URL，跳到节目页
        }

    async def get_podcast_episodes(
        self, podcast_url_or_id: str, max_episodes: int = 20
    ) -> tuple[dict, list[dict]]:
        """获取播客节目信息及单集列表

        Args:
            podcast_url_or_id: 播客URL或PID
            max_episodes: 最多获取多少集

        Returns:
            tuple: (播客信息, 单集列表)
        """
        if podcast_url_or_id.startswith("http"):
            type_, pid = self._parse_url(podcast_url_or_id)
            assert type_ == "podcast", f"URL不是播客页面: {podcast_url_or_id}"
        else:
            pid = podcast_url_or_id

        url = f"{self.BASE_URL}/podcast/{pid}"
        page_props = await self._fetch_next_data(url)

        podcast = page_props.get("podcast", {})
        if not podcast:
            raise ValueError(f"未找到播客数据: {url}")

        podcast_info = {
            "pid": podcast.get("pid", pid),
            "title": podcast.get("title", ""),
            "author": podcast.get("author", ""),
            "description": podcast.get("description", ""),
            "episode_count": podcast.get("episodeCount", 0),
            "image": podcast.get("image", {}).get("picUrl", ""),
        }

        # 播客页面的episodes在pageProps中，但可能需要滚动加载更多
        # 首先获取页面可见的episodes
        episodes = []

        # 从页面文本中提取episode信息
        await self._ensure_browser()
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)

            # Scroll down to load more episodes
            for _ in range(min(max_episodes // 5, 10)):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            # Get episode links and basic info from the page
            episode_links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href*="/episode/"]')).map(a => ({
                    href: a.href,
                    eid: a.href.split('/episode/')[1],
                    text: a.textContent.trim().substring(0, 200)
                }));
            }""")

            seen_eids = set()
            for link in episode_links:
                eid = link.get("eid", "")
                if eid and eid not in seen_eids:
                    seen_eids.add(eid)
                    episodes.append({"eid": eid, "url": link["href"]})
                    if len(episodes) >= max_episodes:
                        break
        finally:
            await page.close()

        # Now fetch detailed info for each episode
        detailed_episodes = []
        for i, ep in enumerate(episodes):
            try:
                detail = await self.get_episode(ep["eid"])
                detailed_episodes.append(detail)
                print(f"  [{i+1}/{len(episodes)}] {detail['title'][:50]}")
                # Rate limiting
                await asyncio.sleep(1.0)
            except Exception as e:
                print(f"  [{i+1}/{len(episodes)}] 获取失败: {e}")

        return podcast_info, detailed_episodes

    def _normalize_episode(self, episode: dict) -> dict:
        """标准化单集数据"""
        duration_seconds = episode.get("duration", 0) or 0
        duration_minutes = round(duration_seconds / 60, 1)

        # Clean HTML from description/shownotes
        description = self._clean_html(episode.get("description", ""))
        shownotes = self._clean_html(episode.get("shownotes", ""))

        audio_url = episode.get("enclosure", {}).get("url", "")
        media_key = episode.get("mediaKey", "")

        # If no enclosure URL, construct from mediaKey
        if not audio_url and media_key:
            audio_url = f"https://media.xyzcdn.net/{media_key}"

        return {
            "eid": episode.get("eid", ""),
            "title": episode.get("title", ""),
            "description": description,
            "shownotes": shownotes,
            "audio_url": audio_url,
            "media_key": media_key,
            "duration_seconds": duration_seconds,
            "duration_minutes": duration_minutes,
            "pub_date": episode.get("pubDate", ""),
            "podcast_title": episode.get("podcast", {}).get("title", ""),
            "podcast_pid": episode.get("podcast", {}).get("pid", ""),
            "image": episode.get("image", {}).get("picUrl", ""),
            "play_count": episode.get("playCount", 0),
            "comment_count": episode.get("commentCount", 0),
            "clap_count": episode.get("clapCount", 0),
        }

    @staticmethod
    def _clean_html(html: str) -> str:
        """去除HTML标签，保留纯文本，并将块级元素转换为换行"""
        if not html:
            return ""
        text = html
        # 块级标签 / 换行标签 → \n
        text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(
            r"</\s*(p|div|li|h[1-6]|tr|section|article)\s*>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"<\s*(p|div|li|h[1-6]|tr|section|article)[^>]*>",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        # 其他 HTML 标签去掉
        text = re.sub(r"<[^>]+>", "", text)
        # HTML 实体
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&#39;|&apos;", "'", text)
        text = re.sub(r"&quot;", '"', text)
        # 规范化空白
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def get_audio_filename(self, episode: dict) -> str:
        """根据episode信息生成音频文件名"""
        eid = episode.get("eid", "unknown")
        return f"{eid}.m4a"


async def download_audio(audio_url: str, output_path: str, chunk_size: int = 8192) -> str:
    """下载音频文件

    Args:
        audio_url: 音频URL
        output_path: 输出文件路径
        chunk_size: 下载块大小

    Returns:
        str: 下载的文件路径
    """
    import aiohttp

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if os.path.exists(output_path):
        print(f"  音频文件已存在，跳过下载: {output_path}")
        return output_path

    print(f"  下载音频: {audio_url[:80]}...")
    async with aiohttp.ClientSession() as session:
        async with session.get(audio_url) as response:
            if response.status != 200:
                raise ValueError(f"下载失败: HTTP {response.status}")

            total = response.content_length
            downloaded = 0
            with open(output_path, "wb") as f:
                async for chunk in response.content.iter_chunked(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  下载进度: {pct:.1f}%", end="", flush=True)

            print()  # newline after progress

    return output_path
