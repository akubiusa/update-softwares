import logging
import os
from pathlib import Path
import re
import subprocess
import textwrap
import time
import json

import psutil
import traceback

from ..os_eol import get_os_eol_info, get_os_display_string
from .winget_outdated import report_winget_outdated

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_INTERVAL_SECONDS = 5

def run_scoop_with_retry(args, description):
  """Run a scoop command, retrying when it exits non-zero or fails to launch.

  Args:
    args: Arguments passed to scoop (for example ["update", "app"]).
    description: Description of the operation, used in console messages.

  Returns:
    bool: True if any attempt exits with 0, False if every attempt fails.
  """
  for attempt in range(1, MAX_RETRIES + 1):
    try:
      result = subprocess.run(["scoop"] + args, shell=True)
      failure = f"exit code {result.returncode}" if result.returncode != 0 else None
    except OSError as e:
      failure = str(e)

    if failure is None:
      return True

    print(f"An error occurred during {description} ({failure}). ({attempt}/{MAX_RETRIES})")
    if attempt < MAX_RETRIES:
      time.sleep(RETRY_INTERVAL_SECONDS)

  print(f"Failed {description} after {MAX_RETRIES} attempts.")
  return False

def update_scoop_repos():
  """Run scoop update to refresh the buckets, retrying up to MAX_RETRIES times.

  Returns:
    bool: True if the update succeeded, False if every attempt failed.
  """
  return run_scoop_with_retry(["update"], "Scoop update")

def get_scoop_status():
    raw_output = os.popen("scoop status").read()

    cleaned_output = re.sub(r'\x1b\[[0-9;]*m', '', raw_output)

    lines = cleaned_output.strip().splitlines()

    header_index = None
    for i, line in enumerate(lines):
        if 'Name' in line and 'Installed Version' in line:
            header_index = i
            break

    if header_index is None:
        return []

    header_line = lines[header_index]
    data_lines = lines[header_index + 2:]

    # Take each column's start position from the header row
    columns = ['Name', 'Installed Version', 'Latest Version', 'Missing Dependencies', 'Info']
    col_positions = []
    for col in columns:
        match = re.search(re.escape(col), header_line)
        if match:
            col_positions.append(match.start())
        else:
            col_positions.append(None)

    # The last column has no following column, so its end is None
    col_positions.append(None)

    # Parse the data rows
    results = []
    for line in data_lines:
        if not line.strip():
            continue
        values = []
        for i in range(len(columns)):
            start = col_positions[i]
            end = col_positions[i + 1]
            if start is None:
                values.append('')
                continue
            segment = line[start:end].rstrip() if end else line[start:].rstrip()
            values.append(segment.strip())

        entry = dict(zip(['name', 'installed', 'latest', 'missing', 'info'], values))
        results.append(entry)

    return results

def post_github_comment(github_issue, hostname, status_results):
  comment_body = textwrap.dedent("""
  ## {markdown_computer_name} : scoop upgrade

  ### Upgrades

  {upgrade_list}
  """).strip()

  upgrade_lists = []
  if status_results:
    upgrade_lists.append("| Name | Installed Version | Latest Version | Missing Dependencies | Info |")
    upgrade_lists.append("| --- | --- | --- | --- | --- |")
    for app in status_results:
      upgrade_lists.append(f"| {app['name']} | {app['installed']} | {app['latest']} | {app['missing']} | {app['info']} |")
  else:
    upgrade_lists.append("No upgrades available.")
  comment_body = comment_body.format(
      markdown_computer_name=github_issue.get_markdown_computer_name(hostname),
      upgrade_list="\n".join(upgrade_lists),
  )
  github_issue.comment(comment_body)


def get_processes():
    results = []
    for pid in psutil.pids():
        try:
            process = psutil.Process(pid)
            process_info = {
                "pid": pid,
                "name": process.name(),
                "exe": process.exe(),
                "status": process.status(),
            }

            results.append(process_info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return results

def get_running_apps(app_names):
    # Return the running processes of the apps to be upgraded, keyed by app name
    running_app_pids = {}
    scoop_path = Path(os.getenv("SCOOP"))
    apps_path = scoop_path / "apps"

    running_processes = get_processes()

    for app_name in app_names:
        app_dir = apps_path / app_name
        if not app_dir.exists():
            continue

        # A process belongs to the app if its exe is under the app directory
        app_running_processes = [
            {"pid": process["pid"], "name": process["name"], "exe": process["exe"]}
            for process in running_processes
            if process["exe"].lower().startswith(str(app_dir).lower())
        ]

        if app_running_processes:
            running_app_pids[app_name] = app_running_processes

    return running_app_pids

def update_scoop_apps(app_names):
    results = {}
    for app_name in app_names:
        print(f"Updating {app_name}...")
        results[app_name] = run_scoop_with_retry(["update", app_name], f"updating {app_name}")
        if results[app_name]:
            print(f"Successfully updated {app_name}.")

    return results

def stop_app(app_processes):
    stopped_processes = []
    for process in app_processes:
        pid = process["pid"]
        process_name = process.get("name", f"PID-{pid}")  # fallback when the dict has no name
        try:
            psutil_process = psutil.Process(pid)
            process_name = psutil_process.name()
            psutil_process.terminate()
            stopped_processes.append(process_name)
            print(f"Stopped {process_name}.")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            print(f"Failed to stop {process_name}.")

    return stopped_processes

def get_app_startup_command(app_name, process_name):
    """
    Get the startup command from the shortcuts definition in manifest.json.
    
    Args:
        app_name: Application name
        process_name: Process name (executable file name)
    
    Returns:
        tuple: (executable path, argument list), or (None, None) if not found
    """
    scoop_path_str = os.getenv("SCOOP")
    if not scoop_path_str:
        logger.error("SCOOP environment variable is not set")
        return None, None
    
    scoop_path = Path(scoop_path_str)
    manifest_path = scoop_path / "apps" / app_name / "current" / "manifest.json"
    
    if not manifest_path.exists():
        return None, None
    
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        shortcuts = manifest.get("shortcuts")
        if not shortcuts:
            return None, None
        
        # Find the shortcut that matches process_name
        for shortcut in shortcuts:
            if not isinstance(shortcut, list) or len(shortcut) < 2:
                continue
            
            # Shortcut format: [exe_path, shortcut_name, arguments...]
            exe_path_str = shortcut[0]
            if not exe_path_str or not isinstance(exe_path_str, str):
                continue
            
            # Normalize Windows path separators
            exe_path_normalized = exe_path_str.replace('\\', os.sep)
            exe_name = Path(exe_path_normalized).name
            
            if exe_name.lower() == process_name.lower():
                full_exe_path = scoop_path / "apps" / app_name / "current" / exe_path_normalized
                # Arguments are the elements after the shortcut name
                args = shortcut[2:] if len(shortcut) > 2 else []
                return full_exe_path, args
        
        return None, None
    except Exception as e:
        logger.error(f"Failed to read manifest for {app_name}: {e}")
        return None, None

def start_app(app_name, app_processes):
    # Restart the app using the shortcuts definition in manifest.json (with arguments)
    scoop_path = Path(os.getenv("SCOOP"))
    apps_path = scoop_path / "apps"
    app_dir = apps_path / app_name
    current_dir = app_dir / "current"
    if not current_dir.exists():
        print(f"Current directory not found for {app_name}.")
        return

    for process in app_processes:
        process_name = process["name"]
        
        exe_path, args = get_app_startup_command(app_name, process_name)
        
        # No definition in the manifest: fall back to the executable in current/
        if exe_path is None:
            exe_path = current_dir / process_name
            args = []
        
        exe_path_str = str(exe_path)
        
        if not os.path.exists(exe_path_str):
            print(f"Executable not found: {exe_path_str}")
            continue

        try:
            command = [exe_path_str] + args
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if args:
                print(f"Started {exe_path_str} with arguments: {' '.join(args)}")
            else:
                print(f"Started {exe_path_str}.")
        except Exception as e:
            print(f"Failed to start {exe_path_str}: {e}")

def cleanup_scoop() -> list[tuple[str, int | None]]:
    """Run scoop cleanup and remove the scoop cache.

    Returns:
        list[tuple[str, int | None]]: Failed commands with their exit codes.
            Empty if everything succeeded. The exit code is None when the command failed to launch.
    """
    commands = [
        ["scoop", "cleanup", "*"],
        ["scoop", "cache", "rm", "*"],
    ]
    failures = []
    for command in commands:
        command_line = " ".join(command)
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
        except OSError as e:
            failures.append((command_line, None))
            logger.error(f"Command failed to launch via cmd.exe (shell=True): {command_line} ({e})")
            continue
        if result.returncode != 0:
            failures.append((command_line, result.returncode))
            logger.error(f"Command failed: {command_line} (exit code {result.returncode})")
            if result.stderr:
                logger.error(f"stderr: {result.stderr}")
    return failures

def post_cleanup_warning(github_issue, hostname, cleanup_failures):
  """Comment the scoop cleanup failures on the GitHub Issue.

  Failures are usually caused by files in use, so they are reported as a warning, without stderr or app names.

  Args:
    github_issue: The GitHubIssue to comment on.
    hostname: Host name of the running machine.
    cleanup_failures: Return value of cleanup_scoop() (failed commands with exit codes).
  """
  rows = ["| Command | Exit code |", "| --- | --- |"]
  for command_line, returncode in cleanup_failures:
    rows.append(f"| `{command_line}` | {'failed to launch' if returncode is None else returncode} |")
  comment_body = textwrap.dedent("""
  ## {markdown_computer_name} : scoop cleanup

  Cleanup finished with warnings. The upgrade status above is not affected.

  {failure_list}
  """).strip().format(
      markdown_computer_name=github_issue.get_markdown_computer_name(hostname),
      failure_list="\n".join(rows),
  )
  github_issue.comment(comment_body)

def run(github_issue, hostname) -> None:
    try:
        os_eol_info, is_critical = get_os_eol_info()
        os_display = get_os_display_string()

        # Set initial status to running
        github_issue.atomic_update_with_retry(
            computer_name=hostname,
            package_manager="scoop",
            upgraded="",
            failed="",
            status="running",
            os_eol=os_eol_info,
            os_eol_critical=is_critical,
            operation_system=os_display,
        )

        repos_updated = update_scoop_repos()

        status_results = get_scoop_status()
        post_github_comment(github_issue, hostname, status_results)
        upgrade_app_names = [app["name"] for app in status_results]

        running_app_processes = get_running_apps(upgrade_app_names)
        not_running_apps = [app for app in upgrade_app_names if app not in running_app_processes]

        print(f"Running applications: {len(running_app_processes)}")
        print(f"Not running applications: {len(not_running_apps)}")

        # Update status before starting upgrades
        github_issue.atomic_update_with_retry(
            computer_name=hostname,
            package_manager="scoop",
            upgraded=str(len(not_running_apps)),
            failed="",
            status="running",
            os_eol=os_eol_info,
            os_eol_critical=is_critical,
            operation_system=os_display,
        )

        print("Updating not running applications...")
        not_running_apps_results = update_scoop_apps(not_running_apps)

        running_apps_results = {}
        print("Updating running applications...")
        for app_name, app_processes in running_app_processes.items():
            print(f"The following applications are running: {app_name}")
            print(app_processes)
            response = input("Do you want to update? [Y/n]: ")
            if response.lower() in ["y", ""]:
                stop_app(app_processes)
                result = update_scoop_apps([app_name])
                start_app(app_name, app_processes)
                running_apps_results[app_name] = result[app_name]

        merged_results = {**not_running_apps_results, **running_apps_results}

        # scoop can exit with 0 even on errors, so an app we tried to update that is still outdated counts as failed
        remaining_status_results = get_scoop_status()
        remaining_app_names = {app["name"] for app in remaining_status_results}
        for app_name in merged_results:
            if app_name in remaining_app_names:
                merged_results[app_name] = False

        success_count = sum(1 for result in merged_results.values() if result)
        failed_count = len(merged_results) - success_count

        status = "success" if repos_updated and failed_count == 0 else "failed"

        # Set final status atomically
        github_issue.atomic_update_with_retry(
            computer_name=hostname,
            package_manager="scoop",
            upgraded=str(success_count),
            failed=str(failed_count),
            status=status,
            os_eol=os_eol_info,
            os_eol_critical=is_critical,
            operation_system=os_display,
        )

        # Cleanup runs after the final status is set so a hang cannot leave the Issue as running; failures only produce a warning and do not affect the status
        cleanup_failures = cleanup_scoop()
        if cleanup_failures:
            try:
                post_cleanup_warning(github_issue, hostname, cleanup_failures)
            except Exception as e:
                logger.warning(f"Failed to post scoop cleanup warning: {e}")

        print("Failed upgrade applications:")
        for app in remaining_status_results:
              print(f" - {app['name']}")
        print("Scoop update completed.")

        try:
            report_winget_outdated()
        except Exception as e:
            logger.warning(f"Failed to report outdated winget packages: {e}")
    except Exception as e:
        logger.error(f"An error occurred during the upgrade: {e}")
        logger.error(traceback.format_exc())
        
        try:
            os_eol_info, is_critical = get_os_eol_info()
        except Exception:
            os_eol_info = "不明"
            is_critical = False
        os_display = get_os_display_string()

        # Set error status atomically
        github_issue.atomic_update_with_retry(
            computer_name=hostname,
            package_manager="scoop",
            upgraded="",
            failed="",
            status="failed",
            os_eol=os_eol_info,
            os_eol_critical=is_critical,
            operation_system=os_display,
        )
