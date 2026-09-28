.PHONY: test portability lint demo

test:
	uv run pytest tests/ -v

portability:
	bash scripts/portability_check.sh

lint: portability
	uv run python -m core.lint.checks_lint --help >/dev/null

demo:
	uv run python -m demo.run
