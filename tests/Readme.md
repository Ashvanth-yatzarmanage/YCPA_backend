# Testing Guide

## Install

```bash
pip install pytest pytest-asyncio httpx pytest-cov
```

---

## Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode     = "auto"
testpaths        = ["tests"]
python_files     = "test_*.py"
python_classes   = "Test*"
python_functions = "test_*"
addopts          = "-v --tb=short"
```

Or create `pytest.ini` in project root:

```ini
[pytest]
asyncio_mode = auto
testpaths    = tests
addopts      = -v --tb=short
```

---

## Test Structure

```
tests/
├── conftest.py              ← shared fixtures (fake_user, mock_session etc.)
├── unit/
│   ├── test_exceptions.py   ← exception classes (simplest, start here)
│   └── services/
│       └── test_base_service.py  ← service logic with mock DB
└── integration/
    └── test_health.py       ← full stack, real HTTP calls
```

### Types of tests

| Type | Uses real DB? | Uses real HTTP? | When to use |
|------|----------|---------------|-------------|
| Unit |  Mock |  No | Testing logic, exceptions, helpers |
| Integration |   Mock |  Real app | Testing endpoints end-to-end |

---

## Run Commands

```bash
# Run all tests
pytest

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run specific file
pytest tests/unit/test_exceptions.py

# Run specific test
pytest tests/unit/test_exceptions.py::TestNotFoundException::test_with_resource

# Run with print output visible
pytest -s

# Run and stop at first failure
pytest -x
```

---

## Coverage

```bash
# Run with coverage report
pytest --cov=app --cov-report=html

# Open report in browser
open htmlcov/index.html      # mac
xdg-open htmlcov/index.html  # linux
```

---

## Quick Reference

```bash
# most useful during development
pytest tests/unit/ -v          # run unit tests, verbose
pytest tests/ -x --tb=short   # stop on first fail, short traceback
pytest -k "test_login"         # run only tests matching keyword
pytest --lf                    # run only tests that failed last time
```