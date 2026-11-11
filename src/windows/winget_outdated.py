import json
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT_SECONDS = 120

POWERSHELL_SCRIPT = (
  "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
  "$ErrorActionPreference = 'Stop'\n"
  "Import-Module Microsoft.WinGet.Client -ErrorAction Stop\n"
  "$rows = @(Get-WinGetPackage -Source winget"
  " | Where-Object { $_.AvailableVersions.Count -gt 0"
  " -and $_.CompareToVersion($_.AvailableVersions[0]) -eq 'Lesser' }"
  " | ForEach-Object { [pscustomobject]@{ Id = $_.Id; Name = $_.Name;"
  " Installed = $_.InstalledVersion; Latest = $_.AvailableVersions[0];"
  " AutoUpdatable = [bool]$_.IsUpdateAvailable } })\n"
  "if ($rows.Count -gt 0) { ConvertTo-Json -InputObject $rows -Compress }"
)


class WingetPinListError(Exception):
  """Raised when winget pin list fails."""


def get_winget_outdated():
  """Get the winget-managed apps whose installed version is older than the latest.

  Returns:
    list[dict] | None: Dictionaries with Id / Name / Installed / Latest / AutoUpdatable.
      Logs a warning and returns None if pwsh or the module is missing, the command fails, or the output is invalid.
  """
  try:
    result = subprocess.run(
      ["pwsh", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_SCRIPT],
      stdin=subprocess.DEVNULL,
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      timeout=COMMAND_TIMEOUT_SECONDS,
    )
  except (OSError, subprocess.TimeoutExpired) as e:
    logger.warning("Skipped winget outdated check: failed to run pwsh (%s)", e)
    return None

  if result.returncode != 0:
    logger.warning(
      "Skipped winget outdated check: pwsh exited with code %s "
      "(is PowerShell 7 and the Microsoft.WinGet.Client module installed?): %s",
      result.returncode,
      result.stderr.strip(),
    )
    return None

  output = result.stdout.strip()
  if not output:
    return []

  try:
    packages = json.loads(output)
  except json.JSONDecodeError as e:
    logger.warning("Skipped winget outdated check: invalid JSON from pwsh (%s)", e)
    return None

  if isinstance(packages, dict):
    return [packages]
  return packages


def get_winget_pinned_ids(package_ids):
  """Get the package IDs pinned in winget.

  The table printed by winget pin list has locale-dependent column widths, so columns are not parsed;
  each ID in package_ids is matched as a whitespace-separated token of the output.

  Args:
    package_ids: Package IDs to check.

  Returns:
    set[str]: The IDs in package_ids that are pinned.

  Raises:
    WingetPinListError: If winget pin list fails.
  """
  try:
    result = subprocess.run(
      ["winget", "pin", "list"],
      stdin=subprocess.DEVNULL,
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      timeout=COMMAND_TIMEOUT_SECONDS,
    )
  except (OSError, subprocess.TimeoutExpired) as e:
    raise WingetPinListError(f"Failed to run winget pin list: {e}") from e

  if result.returncode != 0:
    raise WingetPinListError(f"winget pin list exited with code {result.returncode}")

  return set(package_ids) & set(result.stdout.split())


def classify(outdated, pinned_ids):
  """Exclude pinned packages and split the rest into auto-updatable and manual.

  Args:
    outdated: Return value of get_winget_outdated().
    pinned_ids: Set of pinned package IDs.

  Returns:
    tuple[list[dict], list[dict]]: (auto-updatable, manual).
  """
  targets = [p for p in outdated if p["Id"] not in pinned_ids]
  auto_updatable = [p for p in targets if p["AutoUpdatable"]]
  manual = [p for p in targets if not p["AutoUpdatable"]]
  return auto_updatable, manual


def _safe_print(line):
  """Print one line to the console, replacing characters the stdout encoding cannot represent.

  Args:
    line: The line to print.
  """
  try:
    print(line)
  except UnicodeEncodeError:
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding))

def _report_section(title, packages):
  """Build the heading line and one line per package.

  Args:
    title: Section heading; the package count is appended.
    packages: Package dictionaries to show.

  Returns:
    list[str]: The heading line and the package lines.
  """
  lines = [f"{title}: {len(packages)}"]
  for p in packages:
    lines.append(f" - {p['Name']} ({p['Id']}): {p['Installed']} -> {p['Latest']}")
  return lines


def report_winget_outdated():
  """Show outdated winget apps on the console and in the log. Nothing is updated.

  Failures are only logged as warnings; no exception propagates to the caller.
  """
  try:
    outdated = get_winget_outdated()
    if outdated is None:
      return

    if not outdated:
      _safe_print("No outdated winget packages.")
      logger.debug("No outdated winget packages.")
      return

    try:
      pinned_ids = get_winget_pinned_ids({p["Id"] for p in outdated})
    except WingetPinListError as e:
      logger.warning("Pinned packages are not excluded: %s", e)
      pinned_ids = set()

    auto_updatable, manual = classify(outdated, pinned_ids)
    lines = ["Outdated winget packages (update manually, not updated by this tool):"]
    lines += _report_section("auto-updatable (winget upgrade)", auto_updatable)
    lines += _report_section("manual (reinstall may be required)", manual)
    # print to the console and log at DEBUG for the log file (INFO would show up twice on the console)
    for line in lines:
      _safe_print(line)
      logger.debug(line)
  except Exception as e:
    logger.warning("Failed to report outdated winget packages: %s", e)
