#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

exit_code=0

echo "=== Backend + Data Script Tests (Python unittest) ==="
if ! python3 -m unittest tests.test_backend tests.test_build_data -v 2>&1; then
  exit_code=1
fi

echo ""
echo "=== Frontend Tests (Playwright) ==="
if ! PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers npx playwright test --reporter=list 2>&1; then
  exit_code=1
fi

echo ""
if [ "$exit_code" -eq 0 ]; then
  echo "=== All tests passed ==="
else
  echo "=== SOME TESTS FAILED ==="
fi
exit "$exit_code"
