#!/usr/bin/env bash
# 一键运行自动化测试：./run_tests.sh [api|ui|smoke|all]
set -euo pipefail
cd "$(dirname "$0")"

SUITE="${1:-all}"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers"

if [ ! -x venv/bin/pytest ]; then
  echo "==> 初始化虚拟环境"
  python3.12 -m venv venv
  ./venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

if [ ! -d .browsers ] && { [ "$SUITE" = "ui" ] || [ "$SUITE" = "all" ] || [ "$SUITE" = "smoke" ]; }; then
  echo "==> 安装 Playwright Chromium"
  ./venv/bin/playwright install chromium
fi

mkdir -p reports
COMMON=(--screenshot only-on-failure --output ui/artifacts)

case "$SUITE" in
  api)
    ./venv/bin/pytest api --html reports/api-report.html --self-contained-html ;;
  ui)
    ./venv/bin/pytest ui "${COMMON[@]}" --html reports/ui-report.html --self-contained-html ;;
  smoke)
    ./venv/bin/pytest -m smoke "${COMMON[@]}" --html reports/smoke-report.html --self-contained-html ;;
  all)
    ./venv/bin/pytest api ui "${COMMON[@]}" --html reports/full-report.html --self-contained-html ;;
  *)
    echo "用法: $0 [api|ui|smoke|all]" && exit 1 ;;
esac
