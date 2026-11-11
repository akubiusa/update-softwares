# GitHub Copilot review instructions

This repository is a Python tool that updates apt (Linux) and scoop (Windows) packages on multiple machines and tracks the progress in a GitHub Issue. See `AGENTS.md` for the project rules, including the English-only language policy. Review pull requests against the points below.

## Language

- Code comments, docstrings, docs, runtime messages (logs, errors), commit messages and PR titles are in English (Conventional Commits for commits and PR titles).
- The Japanese strings written into the GitHub Issue (OS EOL labels, dpkg repair comments), the Japanese-locale test fixture and the Copilot re-request comment in `copilot-review-response.yml` are intentional exceptions.

## What to check

- **Concurrent updates**: Issue updates go through `GitHubIssue.atomic_update_with_retry`, and the row marker `<!-- update-softwares#<hostname>#<package_manager> -->` and the 6/7-cell row formats stay compatible.
- **Error handling**: failures of `subprocess` / `requests` / `os.system` calls are not swallowed; exit codes and exceptions are checked, and a failure is reflected in the Issue status.
- **Secrets and privacy**: no GitHub token (`data/github_token.txt`) in the diff, and no credentials or personal data in logs or Issue comments. The winget report must not be posted to the Issue.
- **Platform separation**: Linux (apt) and Windows (scoop / winget) logic stay in their own modules, and a change for one does not break the other.
- **Tests**: new behavior or bug fixes come with unit tests, and external dependencies (requests, subprocess, os.system, psutil, winreg) are mocked.
- **Docs**: `README.md` and `AGENTS.md` are updated when behavior, commands or the layout change.

## Known patterns not to flag

- 2-space indentation in Python (defined in `.editorconfig`).
- The interactive `input()` prompt before stopping a running app in the scoop updater.
- The automatic reboot (`shutdown -r 0`) at the end of the apt run, after the final status is written.
- Japanese text written into the GitHub Issue (see Language).
