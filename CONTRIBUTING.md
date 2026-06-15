# Contributing to Kinova

Thanks for your interest in contributing! This document covers the basics for getting started.

## Development setup

```bash
# 1. Clone the repository
git clone https://github.com/5aeidi/kinova.git
cd kinova

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Copy the example environment file
cp .env.example .env
```

## Running checks

Use the convenience targets in the `Makefile`:

```bash
make lint      # Run Ruff linter and formatter checks
make test      # Run the pytest suite
make check     # Run lint + test
```

Or run the tools directly:

```bash
ruff check app tests
ruff format --check app tests
pytest
```

## Code style

- We target Python 3.10+.
- Line length is 100 characters.
- Import order is handled automatically by Ruff.
- Type hints are encouraged for new public functions and methods.

## Pull request process

1. Create a feature branch from `main`.
2. Make your changes and add or update tests.
3. Run `make check` locally and ensure everything passes.
4. Push your branch and open a pull request.
5. Fill out the PR description with what changed and why.

## Reporting issues

If you find a bug or have a feature request, please open an issue on GitHub. Include:

- A clear description of the problem or idea.
- Steps to reproduce (for bugs).
- The Python version and OS you are using.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
