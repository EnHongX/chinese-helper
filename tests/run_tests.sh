#!/usr/bin/env bash
# Run all chinese-helper tests
set -e
cd "$(dirname "$0")/.."

EXIT=0

echo "=== Running backend tests ==="
python3 tests/test_backend.py -v || EXIT=1

echo ""
echo "=== Running backend layer tests ==="
python3 tests/test_backend_layers.py -v || EXIT=1

echo ""
echo "=== Running build data tests ==="
python3 tests/test_build_data.py -v || EXIT=1

echo ""
echo "=== Running frontend integration tests ==="
python3 tests/test_frontend.py -v || EXIT=1

echo ""
if [ "$EXIT" -eq 0 ]; then
    echo "=== All test suites passed ==="
else
    echo "=== SOME TESTS FAILED (exit code $EXIT) ==="
fi
exit $EXIT
