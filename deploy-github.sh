#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# 把 hot_output/ 里的最新榜单网站发布到 GitHub Pages
# 用法：
#   1. 第一次：在仓库根目录 (podcast-digest/) 执行 `git init && 关联远端仓库`
#   2. 之后只要：bash deploy-github.sh
#   3. 想配合定时任务：crontab -e 加一行：
#        0 8 * * * cd /Users/wangsuqi/CodeBuddy/20260522002851/podcast-digest && \
#                 python3 main.py hot --top 10 -o hot_output >> /tmp/podcast-cron.log 2>&1 && \
#                 bash deploy-github.sh >> /tmp/podcast-cron.log 2>&1
# -----------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"

SITE_DIR="hot_output"
BRANCH="${PODCAST_BRANCH:-main}"

if [[ ! -d "$SITE_DIR" ]]; then
  echo "[deploy] 错误：找不到 $SITE_DIR/，请先运行 python3 main.py hot 生成榜单。"
  exit 1
fi

if [[ ! -d ".git" ]]; then
  echo "[deploy] 当前目录尚未初始化 git。请先执行："
  echo "         git init"
  echo "         git remote add origin git@github.com:<你的用户名>/podcast-digest.git"
  echo "         git checkout -b $BRANCH"
  exit 1
fi

# 确保 hot_output/ 不在 .gitignore 中
if [[ -f .gitignore ]] && grep -qE "^\s*hot_output/?\s*$" .gitignore; then
  echo "[deploy] 警告：.gitignore 里忽略了 hot_output/，发布需要它，请手动移除该行。"
  exit 1
fi

echo "[deploy] 切到分支 $BRANCH"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"

echo "[deploy] 添加站点文件..."
git add "$SITE_DIR" .nojekyll README.md 2>/dev/null || true

if git diff --cached --quiet; then
  echo "[deploy] 没有新变化，跳过提交。"
else
  TS="$(date '+%Y-%m-%d %H:%M')"
  git commit -m "auto: refresh ranking site @ $TS"
  echo "[deploy] 推送到远端..."
  git push origin "$BRANCH"
  echo "[deploy] ✅ 已推送，GitHub Pages 通常在 1~2 分钟内更新。"
fi
