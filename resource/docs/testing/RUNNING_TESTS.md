# Running the Tests

Complete guide to running the remakeai_ros2 test suite.

---

## Quick Commands

### Run All Tests (Fastest)
```bash
cd "C:\Users\Ricardo\Documents\Remake Ai\remakeai_ros2"
python -m pytest test_*.py -q
```

### Run All Tests with Details (Recommended)
```bash
python -m pytest test_*.py -v
```

### Run Tests and Generate HTML Report
```bash
python -m pytest test_*.py --html=test_report.html --self-contained-html
```

---

## Test Execution Methods

### 1. Run All Tests at Once
```bash
# Quick summary (pass/fail count)
pytest test_*.py -q

# Verbose output (each test result)
pytest test_*.py -v

# Very verbose (full details)
pytest test_*.py -vv
```

**Expected Output:**
```
================================ 106 passed in 1.91s =================================
```

---

### 2. Run Individual Test Suites

**CLI Tests Only:**
```bash
pytest test_cli_integration.py -v
```

**Platform Connection Tests:**
```bash
pytest test_platform_connect.py -v
```

**3-Phase App Launch Tests:**
```bash
pytest test_app_launch.py -v
```

**Movement & Sensor Tests:**
```bash
pytest test_movement_and_sensors.py -v
```

**Asset Manager Tests:**
```bash
pytest test_asset_manager.py -v
```

**End-to-End Tests:**
```bash
pytest test_end_to_end.py -v
```

---

### 3. Run Specific Test Classes

```bash
# Run only CLI auth tests
pytest test_cli_integration.py::TestCLIAuth -v

# Run only 3-phase protocol tests
pytest test_app_launch.py::TestPhase1EstablishAppSession -v

# Run only sensor streaming tests
pytest test_movement_and_sensors.py::TestSensorStreaming -v
```

---

### 4. Run Specific Individual Test

```bash
# Run one specific test
pytest test_cli_integration.py::TestCLIAuth::test_login_saves_token -v

# Show print statements in output
pytest test_cli_integration.py::TestCLIAuth::test_login_saves_token -v -s
```

---

### 5. Show Print Statements (Debug Output)

```bash
# Show all print() statements during test
pytest test_*.py -v -s

# Show only for failed tests
pytest test_*.py -v -s --tb=short
```

---

### 6. Stop on First Failure

```bash
# Useful for debugging
pytest test_*.py -x

# Show last N lines of traceback
pytest test_*.py -x --tb=long
```

---

### 7. Run Last Failed Tests Only

```bash
# Re-run only tests that failed last time
pytest test_*.py --lf

# Run failed tests + passed tests
pytest test_*.py --ff
```

---

### 8. Match Tests by Name

```bash
# Run tests matching pattern
pytest test_*.py -k "auth" -v

# Run tests NOT matching pattern
pytest test_*.py -k "not auth" -v

# Multiple patterns
pytest test_*.py -k "auth or pairing" -v
```

---

### 9. Generate HTML Report

```bash
# Create self-contained HTML report
pytest test_*.py --html=report.html --self-contained-html

# Report opens in browser (Windows)
start report.html

# Report opens in browser (Mac)
open report.html

# Report opens in browser (Linux)
xdg-open report.html
```

**Report Includes:**
- Test results and timings
- Pass/fail statistics
- Test names and descriptions
- Error messages and tracebacks
- Timeline graph

---

### 10. Generate Coverage Report

```bash
# First, install coverage package
pip install pytest-cov

# Generate coverage
pytest test_*.py --cov=remakeai --cov-report=html

# View report
start htmlcov/index.html
```

**Coverage Report Shows:**
- Files covered
- Line coverage percentage
- Branch coverage
- Missing lines
- Coverage trends

---

### 11. Run Tests in Parallel (Faster)

```bash
# Install parallel plugin
pip install pytest-xdist

# Run 4 tests in parallel
pytest test_*.py -n 4

# Auto-detect number of CPUs
pytest test_*.py -n auto
```

**Performance:**
- Sequential: ~2 seconds
- Parallel (4): ~1 second
- Parallel (auto): varies by CPU

---

### 12. Watch Mode (Auto Re-run)

```bash
# Install watch plugin
pip install pytest-watch

# Watch and re-run on file changes
ptw test_*.py

# Re-run only failed tests
ptw test_*.py --last-failed
```

**Useful for:**
- Test-driven development
- Continuous testing
- Quick iteration

---

### 13. Detailed Failure Output

```bash
# Show full traceback
pytest test_*.py --tb=long

# Show short traceback
pytest test_*.py --tb=short

# Show one-line traceback
pytest test_*.py --tb=line

# Show no traceback
pytest test_*.py --tb=no
```

---

### 14. Filter by Mark

```bash
# Run only tests marked as "slow"
pytest test_*.py -m slow

# Run tests NOT marked as "slow"
pytest test_*.py -m "not slow"
```

---

## Common Scenarios

### Scenario 1: Quick Verification
```bash
# Run all tests, minimal output, fast
pytest test_*.py -q
```

### Scenario 2: Debug Failing Test
```bash
# Stop on first failure, show output, full traceback
pytest test_*.py -x -s --tb=long
```

### Scenario 3: Check Specific Feature
```bash
# Run only authentication tests
pytest test_*.py -k "auth" -v

# Watch for changes
ptw test_*.py -k "auth"
```

### Scenario 4: Generate Report for Stakeholders
```bash
# Create detailed HTML report
pytest test_*.py --html=test_report.html --self-contained-html

# Create coverage report
pytest test_*.py --cov=remakeai --cov-report=html
```

### Scenario 5: Performance Benchmarking
```bash
# Show slowest tests
pytest test_*.py -v --durations=10

# Run in parallel for speed comparison
pytest test_*.py -n auto --durations=10
```

---

## Test Output Examples

### Passing Test
```
test_cli_integration.py::TestCLIAuth::test_login_saves_token PASSED  [ 10%]
```

### Failing Test
```
test_cli_integration.py::TestCLIAuth::test_login_saves_token FAILED  [ 10%]
AssertionError: assert None == 'token'
```

### Test with Fixture
```
test_platform_connect.py::TestRobotConnection::test_signature_computation PASSED [ 25%]
```

---

## Troubleshooting

### Issue: "Module not found"
```bash
# Solution: Install package in development mode
pip install -e .
```

### Issue: "Permission denied"
```bash
# Solution: Check permissions
ls -la C:\Users\Ricardo\Documents\Remake\ Ai\remakeai_ros2\

# Or run as administrator
```

### Issue: "Tests hang/timeout"
```bash
# Solution: Run with timeout
pytest test_*.py --timeout=30

# Install timeout plugin first
pip install pytest-timeout
```

### Issue: "Test order affects results"
```bash
# Solution: Run tests in random order (detects dependencies)
pytest test_*.py --random-order

# Install plugin first
pip install pytest-randomly
```

---

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - run: pip install -r requirements.txt
      - run: pytest test_*.py -v
```

### GitLab CI Example
```yaml
test:
  script:
    - pip install -r requirements.txt
    - pytest test_*.py -v
  coverage: '/TOTAL.*\s+(\d+%)$/'
```

---

## Test Report Locations

After running tests:

- **HTML Report:** `./test_report.html`
- **Coverage Report:** `./htmlcov/index.html`
- **JUnit XML:** `./results.xml`
- **JSON Results:** `./results.json`

---

## Next Steps

1. Run all tests: `pytest test_*.py -v`
2. Review passing tests
3. Check coverage: `pytest test_*.py --cov=remakeai`
4. Generate report: `pytest test_*.py --html=report.html`
5. Review documentation in `docs/` folder
