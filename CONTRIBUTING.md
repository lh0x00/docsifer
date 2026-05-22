# Contributing

Thanks for your interest in Docsifer.

## Development setup

```bash
git clone https://github.com/lh0x00/docsifer.git
cd docsifer
make install
cp .env.example .env
make run
```

Hop into <http://localhost:7860/docs> for the OpenAPI docs.

## Style

We use:

- **ruff** for linting and formatting (`make lint` / `make format`).
- **mypy** for type checking (`make type`).
- **pytest** + **pytest-asyncio** for tests (`make test`).

Pre-commit hooks are configured in `.pre-commit-config.yaml`. Install them
with `pre-commit install` to catch issues before pushing.

## Pull requests

1. Branch from `main`.
2. Add tests for any new behavior — see `tests/unit` and `tests/integration`.
3. Make sure `make lint test` passes locally.
4. Update `README.md` / `ARCHITECTURE.md` when you change behavior.

## Bug reports

Please include:

- Docsifer version (`docsifer/__init__.py:__version__`).
- Python and OS versions.
- A minimal reproduction (curl command or test snippet).
- Logs (with `DOCSIFER_LOG_JSON=false` for readability).
