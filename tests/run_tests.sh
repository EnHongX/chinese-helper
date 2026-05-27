#!/usr/bin/env bash
# 运行小学语文助手全套自动化测试
# 用法：
#   ./tests/run_tests.sh            # 跑全部 93 个测试
#   ./tests/run_tests.sh backend    # 只跑后端（不含前端）
#   ./tests/run_tests.sh frontend   # 只跑前端
set -e

cd "$(dirname "$0")/.."

MODE="${1:-all}"

if [ "$MODE" = "backend" ]; then
    python3 -m unittest tests.test_suite -v 2>&1 | grep -vE '^\.\.$|^[0-9.]+ - -' \
        | grep -E 'test_|^OK|^FAILED|^Ran |ERROR:|^FAIL:'
elif [ "$MODE" = "frontend" ]; then
    python3 -m unittest tests.test_suite.TestFrontend -v 2>&1 \
        | grep -vE '^[0-9.]+ - -'
else
    python3 -m unittest tests.test_suite 2>&1 | grep -vE '^[0-9.]+ - -' | tail -8
fi
