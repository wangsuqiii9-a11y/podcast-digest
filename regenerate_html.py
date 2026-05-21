"""
重新生成 hot_output 下的 HTML：
- 把 multi_summary.episodes 与 summaries 中的 episode_url
  替换为各 episode 对应的 podcast_url（Apple Podcasts 节目主页，稳定可用），
  避免小宇宙单集页 404 的问题。
- 不重新抓取 / 转写 / 总结，仅基于现有 metadata.json 重新生成 HTML 与 Markdown。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from report_generator import ReportGenerator  # noqa: E402


def main():
    output_dir = os.path.join(HERE, "hot_output")
    meta_path = os.path.join(output_dir, "metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    episodes_top = meta.get("episodes", [])
    # 用 eid 建立映射：eid -> podcast_url
    eid_to_pod_url = {}
    eid_to_pod_title = {}
    for ep in episodes_top:
        eid = ep.get("eid")
        if eid:
            eid_to_pod_url[eid] = ep.get("podcast_url", "") or ep.get("episode_url", "")
            eid_to_pod_title[eid] = ep.get("podcast_title", "")

    # 修正 summaries / multi_summary 里的 episode_url
    def patch_list(items):
        for it in items:
            eid = it.get("eid")
            new_url = eid_to_pod_url.get(eid, "")
            if new_url:
                it["episode_url"] = new_url

    patch_list(meta.get("summaries", []))
    multi = meta.get("multi_summary", {})
    patch_list(multi.get("episodes", []))

    # 重新生成 HTML / Markdown（榜单站点：index.html + episodes/*.html）
    reporter = ReportGenerator(output_dir)
    md_path = reporter.generate_markdown(multi)
    if multi.get("is_ranking"):
        html_path = reporter.generate_ranking_site(multi, md_path)
    else:
        html_path = reporter.generate_html(multi, md_path)

    # 把改动也保存回 metadata.json，避免下次再生成又走旧 URL
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[OK] Markdown: {md_path}")
    print(f"[OK] HTML:     {html_path}")
    print(f"[OK] Metadata patched: {meta_path}")
    print("[OK] 链接策略：episode_url 已替换为 podcast_url（节目主页，稳定可用）")


if __name__ == "__main__":
    main()
