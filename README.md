# update-softwares

Automates package updates on multiple Linux (apt) and Windows (scoop) machines, and tracks and reports the progress in a GitHub Issue.

## How it works

Each machine runs `python3 -m src <ISSUE_NUMBER>`. The tool reads the Issue body, finds the table rows that belong to the current host, and updates the rows and posts comments on the Issue while it works.

- Linux (`apt`): requires root. Repairs an interrupted dpkg (`dpkg --configure -a`) if needed, runs `apt-get update`, simulates `apt-get -s -V dist-upgrade`, comments the packages to upgrade, install and remove, runs `apt-get -y dist-upgrade`, and then **reboots the machine** (`shutdown -r 0`, 10 seconds after the final status is written). Nothing is upgraded and no reboot happens when there is nothing to do.
- Windows (`scoop`): updates the buckets (`scoop update`), comments the outdated apps (`scoop status`), updates apps that are not running, and asks `Do you want to update? [Y/n]` for each running app. When you accept, the app's processes are terminated, the app is updated, and it is started again. Finally it runs `scoop cleanup *` and `scoop cache rm *`. Cleanup failures are reported as a warning comment and do not affect the status.
- The OS name and version, and the OS end-of-life (EOL) date from [endoflife.date](https://endoflife.date/), are written to the row. When EOL is already past or less than 90 days away, the status mark becomes 🔴 and the EOL date is shown in bold.
- Concurrent runs on different machines are handled by re-reading the latest Issue body before every update and retrying (up to 3 times) when the update fails.

## Requirements

- Python 3 with the packages in `requirements.txt` (`requests`, `psutil`). CI runs the tests on Python 3.10 to 3.13 on Windows.
- A GitHub token that can read and edit the Issue and post comments on it, saved in `data/github_token.txt` (relative to the directory you run the tool from).
- Linux: root privileges and `apt-get`.
- Windows: [scoop](https://scoop.sh/) and the `SCOOP` environment variable (set by the scoop installer). The tool must be run in an interactive console because it prompts for running apps.

### Issue format

The Issue body must contain a Markdown table with one row per machine and package manager. Each row ends with an HTML comment that identifies the host and the package manager. `<hostname>` is the host name the tool sees (`COMPUTERNAME` on Windows, the node name from `uname` on Linux), and `<package_manager>` is `apt` or `scoop`.

```markdown
| Status | Computer | OS | Package manager | Upgraded | Failed | OS EOL |
| --- | --- | --- | --- | --- | --- | --- |
| ⏳ | pc01 | Ubuntu 24.04 LTS | apt | 0 | 0 | - | <!-- update-softwares#pc01#apt -->
```

Rows with 6 or 7 cells are supported (the 7th cell, OS EOL, is optional); other rows are ignored. Status marks are ✅ (success), ⏳ (running) and 🔴 (failed or EOL critical). Hosts that have no row are skipped with a warning.

## Usage

```bash
pip install -r requirements.txt
python3 -m src <ISSUE_NUMBER>
```

The Issue is looked up in `book000/book000` by default. Set `GITHUB_REPOSITORY` (`owner/repo`) to use another repository.

### Environment variables

| Variable | Description |
| --- | --- |
| `GITHUB_REPOSITORY` | Repository that holds the Issue (`owner/repo`). Default: `book000/book000`. |
| `UPDATE_SOFTWARES_LOG_DIR` | Log directory. Default: `/opt/update-softwares/logs` on Linux, `%USERPROFILE%\update-softwares\logs` on Windows. |
| `SCOOP` | scoop installation directory (Windows). Set by the scoop installer. |
| `ISSUE_NUMBER` | Issue number. Only read by the wrapper scripts below. |

A log file `YYYY-MM-DD.log` is written to the log directory (DEBUG level). INFO and above are also printed to the console.

### Wrapper scripts

Both scripts need `ISSUE_NUMBER` to be set, clone or update this repository on each run, set `UPDATE_SOFTWARES_LOG_DIR`, and then run `python -m src`.

- `update-softwares.sh` (Linux, run as root): clones into `/opt/update-softwares`, offers to install `git` and `python3`, creates a virtual environment, installs `requirements.txt`, and runs the tool.
- `update-softwares.ps1` (Windows): clones into `%USERPROFILE%\update-softwares` and runs the tool with `python`. It does not install `requirements.txt`, so install the dependencies beforehand.

## Windows: outdated winget apps

After the scoop update, the tool prints the apps managed by winget that are outdated to the console and the log. **It does not update them with winget.** Update the ones you need manually.

Outdated apps are shown in two sections.

- auto-updatable: can be updated with `winget upgrade`
- manual: outdated but not eligible for `winget upgrade` (for example when the installer type changed; a reinstall may be required)

The names and versions are not posted to the Issue, because the Issue may be in a public repository.

### Requirements

Both are required. When either is missing, the tool logs a warning and skips the report; the scoop / apt update and the Issue result are not affected. Neither is installed automatically.

1. PowerShell 7 (`pwsh`)

   ```powershell
   winget install --id Microsoft.PowerShell --source winget
   ```

2. The `Microsoft.WinGet.Client` module (installed in PowerShell 7)

   ```powershell
   Install-Module -Name Microsoft.WinGet.Client -Repository PSGallery -Scope CurrentUser
   ```

### Excluding apps

Pin an app with `winget pin` to stop it from being reported.

```powershell
winget pin add --id <package ID>
```

List the pins with `winget pin list`.

## Development

```bash
pip install -r requirements.txt pytest
PYTHONPATH=. pytest tests/
```

`PYTHONPATH=.` is required because `pytest.ini` starts with a `[tool:pytest]` header (the `setup.cfg` form), which pytest ignores in `pytest.ini`, so its `pythonpath = .` setting does not apply. The same tests also run with `python3 -m unittest discover -s tests -p "test_*.py"`.
