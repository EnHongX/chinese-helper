#!/bin/bash
# Run all automated tests for chinese-helper
#
# Tests:
# - Backend API (history CRUD, dictation lifecycle, is_hanzi filtering)
# - Build script (pinyin parsing, shard generation, data validation)
# - Frontend Playwright tests (input, pagination, history, graceful degradation)
#
# All tests use temporary database - does not affect production data.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "======================================"
echo "Running Backend Tests"
echo "======================================"
python3 -m unittest tests.test_backend -v
BACKEND_RESULT=$?

echo ""
echo "======================================"
echo "Running Frontend Playwright Tests"
echo "======================================"
python3 -m unittest tests.test_frontend_playwright -v
FRONTEND_RESULT=$?

echo ""
echo "======================================"
echo "Test Summary"
echo "======================================"
if [ $BACKEND_RESULT -eq 0 ] && [ $FRONTEND_RESULT -eq 0 ]; then
    echo "✓ All tests passed!"
    exit 0
else
    echo "✗ Some tests failed"
    [ $BACKEND_RESULT -ne 0 ] && echo "  - Backend tests: FAILED"
    [ $FRONTEND_RESULT -ne 0 ] && echo "  - Frontend tests: FAILED"
    exit 1
fi
