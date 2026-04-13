# Contributing

## Quick Start

```bash
git clone https://github.com/HemantBK/llm-eval-pipeline.git
cd llm-eval-pipeline
cp .env.example .env
docker compose up postgres redis -d
cd backend && pip install -e ".[test]"
make test
```

## PR Process

1. Fork → Clone → Branch (`git checkout -b feature/my-feature`)
2. Make changes
3. Run `make test` and `make lint`
4. Commit → Push → Open PR

## Adding a New LLM Provider

1. Create `backend/src/app/providers/your_provider.py`
2. Implement the `LLMProvider` ABC (see `base.py`)
3. Register in `registry.py` → `create_registry()`
4. Add rate limit to `config.py`
5. Add tests

## Adding a Rubric

Create `rubrics/your_rubric.yaml`:

```yaml
name: your_rubric
description: What this rubric evaluates.
pass_threshold: 3.0
dimensions:
  - name: accuracy
    description: Is it correct?
    weight: 1.0
    fail_threshold: 2.0
```

## Adding Test Prompts

Append rows to any CSV in `prompts/`:

```csv
prompt_id,category,prompt,difficulty,expected_behavior
YOUR-001,coding,"Your prompt here",medium,"Expected behavior"
```

## Code Style

- Python 3.11+, formatted with ruff
- Type hints on all functions
- Async/await for IO operations
- structlog for logging (not print)
