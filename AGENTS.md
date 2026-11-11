# AGENTS.md

Guidance for AI coding agents and contributors. `CLAUDE.md` imports this file, and `.github/copilot-instructions.md` adds the review checklist.

## Language

- All deliverables are written in **English**: commit messages, PR/Issue titles and bodies, review comments, code comments and docstrings, and documentation (`README.md`, `AGENTS.md`, etc.).
- Exceptions (keep as is): the Japanese strings that the tool writes into the GitHub Issue (the `不明` / `期限切れ` / `日後` OS EOL labels and the dpkg repair comments in `src/linux/update_apt_softwares.py`), the Japanese-locale `winget pin list` fixture in the tests, the Japanese Copilot re-request comment posted by `.github/workflows/copilot-review-response.yml`, quotations, technical identifiers, generated files, and external source text.
- Runtime messages (logs, errors, console output) are English.
- Do not rewrite Git history to change the language of past commits.

## Overview

A Python tool that updates packages on Linux (apt) and Windows (scoop) machines and tracks the progress in a GitHub Issue. Each machine runs `python3 -m src <ISSUE_NUMBER>`, finds its own rows in the Issue table, updates them, and posts comments. After the scoop update on Windows it also prints (does not update) outdated winget apps. See `README.md` for behavior and setup.

## Commands

```bash
pip install -r requirements.txt pytest    # install dependencies (requests, psutil) and the test runner
PYTHONPATH=. pytest tests/                # run the tests (see Known issues for why PYTHONPATH is needed)
python3 -m src <ISSUE_NUMBER>             # run the tool; needs data/github_token.txt and updates real packages
```

CI (`.github/workflows/linux-ci.yml`, `windows-ci.yml`) runs `pytest tests/` with `PYTHONPATH=.` (Python 3.10 to 3.13 and 3.x on Windows). `python3 -m unittest discover -s tests -p "test_*.py"` also works. There is no linter or formatter configuration. Never run the tool against a real machine just to test a change: it upgrades packages (and on Linux reboots the machine).

## Structure

- `src/__main__.py`: entry point. Sets up logging, reads the Issue, and runs the apt or scoop updater for the package managers listed for the current host.
- `src/__init__.py`: `GitHubIssue` (parses and updates the Issue table, `atomic_update_with_retry`), plus helpers (`get_github_token`, `get_real_hostname`, `is_root`, ...).
- `src/linux/update_apt_softwares.py`: apt flow (dpkg repair, simulation, upgrade, reboot).
- `src/windows/update_scoop_softwares.py`: scoop flow (update, running-app handling, cleanup).
- `src/windows/winget_outdated.py`: winget report through `pwsh` and `Microsoft.WinGet.Client` (display only).
- `src/os_eol.py`: OS name/version detection and EOL lookup from endoflife.date.
- `tests/`: unittest-style tests with external dependencies (requests, subprocess, os.system, winreg, psutil) mocked; Linux and Windows tests are in separate directories.
- `update-softwares.sh` / `update-softwares.ps1`: wrapper scripts that clone or update the repository and run the tool.
- `.github/workflows/`: CI, plus review-automation workflows (`proxy-review`, `reply-to-review`, `copilot-review-response`).

## Conventions

- Python style: snake_case, 2-space indentation, UTF-8, LF, final newline, no trailing whitespace (`.editorconfig`). `update_scoop_softwares.py` partly uses 4 spaces; follow the surrounding code.
- Docstrings and comments are English; use Google-style `Args` / `Returns` / `Raises` and keep them in sync with the implementation. Comment design intent and constraints, not what the code does.
- Keep the Issue row format and the `<!-- update-softwares#<hostname>#<package_manager> -->` marker compatible: old 6-cell rows and new 7-cell rows (with OS EOL) are both parsed.
- Update the Issue through `GitHubIssue.atomic_update_with_retry`, which re-reads the body to avoid clobbering concurrent updates from other machines.
- Do not put personal data or credentials in logs or Issue comments. The winget report is never posted to the Issue because the Issue repository may be public.
- Add a unit test for every behavior change. Mock external commands and APIs; tests must not touch the network or the real package managers.
- The scoop updater intentionally asks for confirmation (`input()`) before stopping a running app.
- Update `README.md` and this file when behavior, commands or the directory layout change.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/); branches follow [Conventional Branch](https://conventional-branch.github.io) short form (`feat/...`, `fix/...`).
- Do not commit to Renovate PRs (`renovate.json` extends `github>book000/templates//renovate/base-public`). Never commit secrets such as `data/github_token.txt` (`data/` is git-ignored).

## Known issues

These are documented, not fixed:

- `pytest.ini` starts with `[tool:pytest]` (the `setup.cfg` header), which pytest ignores in `pytest.ini`. Its `pythonpath`, `addopts` and `markers` settings therefore do not apply, which is why `PYTHONPATH=.` is needed. The `slow` / `integration` / `unit` markers are not used by any test.
- `src/windows/update_scoop_softwares.py` imports `logger` from `venv` (`from venv import logger`) instead of defining `logging.getLogger(__name__)`.
- `update-softwares.ps1` does not install `requirements.txt`.
- `update-softwares.sh` runs under `set -u`, so a missing `ISSUE_NUMBER` ends with an "unbound variable" error before the friendly message is printed.
- `tests/linux/test_update_apt_softwares.py` defines `test_run_apt_full_upgrade_failure` twice; the second definition shadows the first.
