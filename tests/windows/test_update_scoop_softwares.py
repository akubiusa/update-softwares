import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.windows.update_scoop_softwares import (
  update_scoop_repos,
  get_scoop_status,
  post_github_comment,
  get_processes,
  get_running_apps,
  update_scoop_apps,
  stop_app,
  start_app,
  get_app_startup_command,
  cleanup_scoop,
  post_cleanup_warning,
  run,
)


class DummyGitHubIssue:
  def __init__(self):
    self.comments = []

  def get_markdown_computer_name(self, hostname):
    return f"dummy-{hostname}"

  def comment(self, body):
    self.comments.append(body)


class TestUpdateScoopSoftwares(unittest.TestCase):
  @patch('src.windows.update_scoop_softwares.subprocess.run', return_value=MagicMock(returncode=0))
  def test_update_scoop_repos_success(self, mock_run):
    result = update_scoop_repos()
    self.assertTrue(result)
    mock_run.assert_called_once_with(["scoop", "update"], shell=True)

  @patch('src.windows.update_scoop_softwares.time.sleep', return_value=None)
  @patch('src.windows.update_scoop_softwares.subprocess.run', return_value=MagicMock(returncode=1))
  def test_update_scoop_repos_nonzero_exit_retries_and_fails(self, mock_run, mock_sleep):
    result = update_scoop_repos()
    self.assertFalse(result)
    self.assertEqual(mock_run.call_count, 5)
    self.assertEqual(mock_sleep.call_count, 4)

  @patch('src.windows.update_scoop_softwares.time.sleep', return_value=None)
  @patch('src.windows.update_scoop_softwares.subprocess.run', side_effect=[MagicMock(returncode=1), MagicMock(returncode=0)])
  def test_update_scoop_repos_succeeds_after_retry(self, mock_run, mock_sleep):
    self.assertTrue(update_scoop_repos())
    self.assertEqual(mock_run.call_count, 2)

  @patch('src.windows.update_scoop_softwares.time.sleep', return_value=None)
  @patch('src.windows.update_scoop_softwares.subprocess.run', side_effect=OSError("fail"))
  def test_update_scoop_repos_oserror_retries_and_fails(self, mock_run, mock_sleep):
    self.assertFalse(update_scoop_repos())
    self.assertEqual(mock_run.call_count, 5)

  @patch('src.windows.update_scoop_softwares.os.popen')
  def test_get_scoop_status_empty(self, mock_popen):
    popen = MagicMock()
    popen.read.return_value = ""
    mock_popen.return_value = popen
    self.assertEqual(get_scoop_status(), [])

  @patch('src.windows.update_scoop_softwares.os.popen')
  def test_get_scoop_status_parses(self, mock_popen):
    header = "Name   Installed Version   Latest Version   Missing Dependencies   Info"
    line = "app1   1.0                 2.0                 none                   OK"
    popen = MagicMock()
    popen.read.return_value = header + "\n\n" + line + "\n"
    mock_popen.return_value = popen
    result = get_scoop_status()
    self.assertEqual(len(result), 1)
    entry = result[0]
    self.assertEqual(entry['name'], 'app1')
    self.assertEqual(entry['installed'], '1.0')
    self.assertEqual(entry['latest'], '2.0')
    self.assertEqual(entry['missing'], 'none')
    self.assertEqual(entry['info'], 'OK')

  def test_post_github_comment(self):
    issue = DummyGitHubIssue()
    status = [{'name': 'app', 'installed': '1', 'latest': '2', 'missing': 'x', 'info': 'i'}]
    post_github_comment(issue, 'host', status)
    self.assertEqual(len(issue.comments), 1)
    body = issue.comments[0]
    self.assertIn('scoop upgrade', body)
    self.assertIn('| Name | Installed Version |', body)
    self.assertIn('| app | 1 | 2 | x | i |', body)

  @patch('src.windows.update_scoop_softwares.psutil.pids', return_value=[123, 456])
  @patch('src.windows.update_scoop_softwares.psutil.Process')
  def test_get_processes(self, mock_process, mock_pids):
    p1 = MagicMock()
    p1.name.return_value = 'p1'
    p1.exe.return_value = 'e1'
    p1.status.return_value = 's1'
    p2 = MagicMock()
    p2.name.return_value = 'p2'
    p2.exe.return_value = 'e2'
    p2.status.return_value = 's2'
    mock_process.side_effect = [p1, p2]
    procs = get_processes()
    self.assertEqual(len(procs), 2)
    self.assertEqual(procs[0]['name'], 'p1')

  @patch('src.windows.update_scoop_softwares.get_processes')
  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_running_apps(self, mock_getenv, mock_getprocs):
    with tempfile.TemporaryDirectory() as tmpdir:
      base = Path(tmpdir) / 'apps'
      (base / 'app1').mkdir(parents=True)
      mock_getenv.return_value = tmpdir
      # create current/exe structure
      cur = base / 'app1' / 'current'
      cur.mkdir(parents=True)
      exe_path = cur / 'x.exe'
      exe_path.write_text('')
      proc = {'pid': 1, 'name': 'x.exe', 'exe': str(exe_path)}
      mock_getprocs.return_value = [proc]
      result = get_running_apps(['app1', 'app2'])
      self.assertIn('app1', result)
      self.assertNotIn('app2', result)

  @patch('src.windows.update_scoop_softwares.subprocess.run', return_value=MagicMock(returncode=0))
  def test_update_scoop_apps_success(self, mock_run):
    result = update_scoop_apps(['a', 'b'])
    self.assertEqual(result, {'a': True, 'b': True})
    self.assertEqual(mock_run.call_count, 2)
    mock_run.assert_any_call(["scoop", "update", "a"], shell=True)
    mock_run.assert_any_call(["scoop", "update", "b"], shell=True)

  @patch('src.windows.update_scoop_softwares.subprocess.run', return_value=MagicMock(returncode=1))
  @patch('src.windows.update_scoop_softwares.time.sleep', return_value=None)
  def test_update_scoop_apps_failure(self, mock_sleep, mock_run):
    result = update_scoop_apps(['a'])
    self.assertEqual(result, {'a': False})
    self.assertEqual(mock_run.call_count, 5)

  @patch('src.windows.update_scoop_softwares.subprocess.run', side_effect=[MagicMock(returncode=1)] * 5 + [MagicMock(returncode=0)])
  @patch('src.windows.update_scoop_softwares.time.sleep', return_value=None)
  def test_update_scoop_apps_failure_does_not_stop_next_app(self, mock_sleep, mock_run):
    result = update_scoop_apps(['a', 'b'])
    self.assertEqual(result, {'a': False, 'b': True})

  @patch('src.windows.update_scoop_softwares.psutil.Process')
  def test_stop_app(self, mock_process):
    mp = MagicMock()
    mp.name.return_value = 'n'
    mock_process.return_value = mp
    result = stop_app([{'pid': 1}])
    self.assertEqual(result, ['n'])
    mp.terminate.assert_called()

  @patch('src.windows.update_scoop_softwares.psutil.Process')
  def test_stop_app_no_such_process(self, mock_process):
    # The process no longer exists
    import psutil
    mock_process.side_effect = psutil.NoSuchProcess(1)
        
    # No UnboundLocalError even when the exception is raised
    try:
      result = stop_app([{'pid': 1, 'name': 'test.exe'}])
      self.assertEqual(result, [])
    except UnboundLocalError:
      self.fail("UnboundLocalError should not be raised")

  @patch('src.windows.update_scoop_softwares.os.getenv')
  @patch('src.windows.update_scoop_softwares.os.path.exists', return_value=True)
  @patch('src.windows.update_scoop_softwares.subprocess.Popen')
  def test_start_app(self, mock_popen, mock_exists, mock_getenv):
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      # create apps/app1/current/app.exe
      app_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      app_path.mkdir(parents=True)
      exe = app_path / 'app.exe'
      exe.write_text('')
      start_app('app1', [{'name': 'app.exe'}])
      # subprocess.Popen should be called with the exe path
      mock_popen.assert_called_with([str(exe)], stdout=unittest.mock.ANY, stderr=unittest.mock.ANY)

  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_app_startup_command_no_manifest(self, mock_getenv):
    """manifest.json does not exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      exe_path, args = get_app_startup_command('app1', 'test.exe')
      self.assertIsNone(exe_path)
      self.assertIsNone(args)

  @patch('src.windows.update_scoop_softwares.os.getenv', return_value=None)
  def test_get_app_startup_command_no_scoop_env(self, mock_getenv):
    """The SCOOP environment variable is not set."""
    exe_path, args = get_app_startup_command('app1', 'test.exe')
    self.assertIsNone(exe_path)
    self.assertIsNone(args)

  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_app_startup_command_no_shortcuts(self, mock_getenv):
    """The manifest has no shortcuts definition."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      manifest_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      manifest_path.mkdir(parents=True)
      manifest_file = manifest_path / 'manifest.json'
      manifest_file.write_text('{"version": "1.0"}')
            
      exe_path, args = get_app_startup_command('app1', 'test.exe')
      self.assertIsNone(exe_path)
      self.assertIsNone(args)

  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_app_startup_command_with_arguments(self, mock_getenv):
    """A shortcuts definition with arguments."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      manifest_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      manifest_path.mkdir(parents=True)
      manifest_file = manifest_path / 'manifest.json'
            
      # Create a shortcuts definition with arguments
      manifest_data = {
        "version": "1.0",
        "shortcuts": [
          ["bin\\test.exe", "Test App", "--arg1", "--arg2"]
        ]
      }
      with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f)
            
      exe_path, args = get_app_startup_command('app1', 'test.exe')
      expected_path = Path(tmpdir) / 'apps' / 'app1' / 'current' / 'bin' / 'test.exe'
      self.assertEqual(exe_path, expected_path)
      self.assertEqual(args, ['--arg1', '--arg2'])

  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_app_startup_command_without_arguments(self, mock_getenv):
    """A shortcuts definition without arguments."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      manifest_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      manifest_path.mkdir(parents=True)
      manifest_file = manifest_path / 'manifest.json'
            
      # Create a shortcuts definition without arguments
      manifest_data = {
        "version": "1.0",
        "shortcuts": [
          ["test.exe", "Test App"]
        ]
      }
      with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f)
            
      exe_path, args = get_app_startup_command('app1', 'test.exe')
      expected_path = Path(tmpdir) / 'apps' / 'app1' / 'current' / 'test.exe'
      self.assertEqual(exe_path, expected_path)
      self.assertEqual(args, [])

  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_app_startup_command_multiple_shortcuts(self, mock_getenv):
    """Multiple shortcuts."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      manifest_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      manifest_path.mkdir(parents=True)
      manifest_file = manifest_path / 'manifest.json'
            
      # Create multiple shortcuts definitions
      manifest_data = {
        "version": "1.0",
        "shortcuts": [
          ["bin\\other.exe", "Other App"],
          ["bin\\test.exe", "Test App", "--config", "settings.ini"],
          ["bin\\another.exe", "Another App"]
        ]
      }
      with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f)
            
      # Look up test.exe
      exe_path, args = get_app_startup_command('app1', 'test.exe')
      expected_path = Path(tmpdir) / 'apps' / 'app1' / 'current' / 'bin' / 'test.exe'
      self.assertEqual(exe_path, expected_path)
      self.assertEqual(args, ['--config', 'settings.ini'])

  @patch('src.windows.update_scoop_softwares.get_app_startup_command')
  @patch('src.windows.update_scoop_softwares.os.getenv')
  @patch('src.windows.update_scoop_softwares.os.path.exists', return_value=True)
  @patch('src.windows.update_scoop_softwares.subprocess.Popen')
  def test_start_app_with_manifest_arguments(self, mock_popen, mock_exists, mock_getenv, mock_get_command):
    """Start the app with the arguments taken from the manifest."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      app_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      app_path.mkdir(parents=True)
      exe = app_path / 'bin' / 'app.exe'
      exe.parent.mkdir(parents=True)
      exe.write_text('')
            
      # Make the manifest lookup return arguments
      mock_get_command.return_value = (exe, ['--arg1', '--arg2'])
            
      start_app('app1', [{'name': 'app.exe'}])
            
      # Started with arguments
      mock_popen.assert_called_with([str(exe), '--arg1', '--arg2'], stdout=unittest.mock.ANY, stderr=unittest.mock.ANY)

  @patch('src.windows.update_scoop_softwares.get_app_startup_command')
  @patch('src.windows.update_scoop_softwares.os.getenv')
  @patch('src.windows.update_scoop_softwares.os.path.exists', return_value=True)
  @patch('src.windows.update_scoop_softwares.subprocess.Popen')
  def test_start_app_fallback_without_manifest(self, mock_popen, mock_exists, mock_getenv, mock_get_command):
    """Fall back to starting the executable directly when there is no manifest."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      app_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      app_path.mkdir(parents=True)
      exe = app_path / 'app.exe'
      exe.write_text('')
            
      # The manifest is not found
      mock_get_command.return_value = (None, None)
            
      start_app('app1', [{'name': 'app.exe'}])
            
      # Started without arguments
      mock_popen.assert_called_with([str(exe)], stdout=unittest.mock.ANY, stderr=unittest.mock.ANY)

  @patch('src.windows.update_scoop_softwares.os.getenv')
  def test_get_app_startup_command_invalid_shortcuts(self, mock_getenv):
    """Invalid shortcuts data."""
    with tempfile.TemporaryDirectory() as tmpdir:
      mock_getenv.return_value = tmpdir
      manifest_path = Path(tmpdir) / 'apps' / 'app1' / 'current'
      manifest_path.mkdir(parents=True)
      manifest_file = manifest_path / 'manifest.json'
            
      # Invalid shortcuts definitions (including a string)
      manifest_data = {
        "version": "1.0",
        "shortcuts": [
          "invalid",  # not a list
          ["", "Empty Path"],  # empty exe_path
          [123, "Number Path"],  # numeric exe_path
          ["valid.exe", "Valid App"]  # valid entry
        ]
      }
      with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f)
            
      # valid.exe is found
      exe_path, args = get_app_startup_command('app1', 'valid.exe')
      expected_path = Path(tmpdir) / 'apps' / 'app1' / 'current' / 'valid.exe'
      self.assertEqual(exe_path, expected_path)
      self.assertEqual(args, [])
            
      # Invalid entries are ignored
      exe_path, args = get_app_startup_command('app1', 'test.exe')
      self.assertIsNone(exe_path)
      self.assertIsNone(args)

  @patch('src.windows.update_scoop_softwares.subprocess.run')
  def test_cleanup_scoop_success(self, mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr='')
    result = cleanup_scoop()
    self.assertEqual(result, [])
    self.assertEqual(mock_run.call_count, 2)
    mock_run.assert_any_call(['scoop', 'cleanup', '*'], shell=True, capture_output=True, text=True)
    mock_run.assert_any_call(['scoop', 'cache', 'rm', '*'], shell=True, capture_output=True, text=True)

  @patch('src.windows.update_scoop_softwares.subprocess.run')
  def test_cleanup_scoop_failure(self, mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr='error')
    result = cleanup_scoop()
    self.assertEqual(result, [('scoop cleanup *', 1), ('scoop cache rm *', 1)])
    self.assertEqual(mock_run.call_count, 2)

  @patch('src.windows.update_scoop_softwares.subprocess.run')
  def test_cleanup_scoop_partial_failure(self, mock_run):
    mock_run.side_effect = [MagicMock(returncode=0, stderr=''), MagicMock(returncode=2, stderr='')]
    self.assertEqual(cleanup_scoop(), [('scoop cache rm *', 2)])

  @patch('src.windows.update_scoop_softwares.subprocess.run', side_effect=OSError('cmd.exe not found'))
  def test_cleanup_scoop_cmd_exe_launch_failure(self, mock_run):
    # Even with shell=True, OSError can be raised when cmd.exe itself fails to launch.
    # It must not raise and is returned as a failure with exit code None (a missing scoop is reported as returncode != 0, the same path as test_cleanup_scoop_failure).
    result = cleanup_scoop()
    self.assertEqual(result, [('scoop cleanup *', None), ('scoop cache rm *', None)])
    self.assertEqual(mock_run.call_count, 2)

  def test_post_cleanup_warning_lists_commands_and_exit_codes_only(self):
    issue = DummyGitHubIssue()
    post_cleanup_warning(issue, 'host', [('scoop cleanup *', 1), ('scoop cache rm *', None)])
    self.assertEqual(len(issue.comments), 1)
    body = issue.comments[0]
    self.assertIn('## dummy-host : scoop cleanup', body)
    self.assertIn('| `scoop cleanup *` | 1 |', body)
    self.assertIn('| `scoop cache rm *` | failed to launch |', body)

  @patch('src.windows.update_scoop_softwares.get_os_display_string', return_value="Windows 11-24H2")
  @patch('src.windows.update_scoop_softwares.get_os_eol_info', return_value=("2030-01-01 (1000 日後)", False))
  @patch('src.windows.update_scoop_softwares.report_winget_outdated')
  @patch('src.windows.update_scoop_softwares.cleanup_scoop', return_value=[])
  @patch('src.windows.update_scoop_softwares.get_running_apps', return_value={})
  @patch('src.windows.update_scoop_softwares.get_scoop_status', return_value=[])
  @patch('src.windows.update_scoop_softwares.update_scoop_repos', return_value=True)
  def test_run_success_passes_operation_system(self, mock_update_repos, mock_get_status, mock_get_running_apps, mock_cleanup, mock_report_winget, mock_get_eol, mock_get_display):
    """run() passes operation_system to every call.

    get_running_apps() calls os.getenv("SCOOP") unconditionally, even when app_names is empty.
    Without mocking it, a missing SCOOP variable raises TypeError and run() falls into its except block,
    so the success path would not be exercised.
    """
    github_issue = MagicMock()

    run(github_issue, "test-host")

    github_issue.atomic_update_with_retry.assert_called()
    for call_args in github_issue.atomic_update_with_retry.call_args_list:
      self.assertEqual(call_args.kwargs["operation_system"], "Windows 11-24H2")

  @patch('src.windows.update_scoop_softwares.get_os_display_string', return_value="Windows 11-24H2")
  @patch('src.windows.update_scoop_softwares.get_os_eol_info', side_effect=Exception("boom"))
  @patch('src.windows.update_scoop_softwares.update_scoop_repos', side_effect=Exception("update failed"))
  def test_run_exception_passes_operation_system(self, mock_update_repos, mock_get_eol, mock_get_display):
    """run() passes operation_system on the error path too."""
    github_issue = MagicMock()

    run(github_issue, "test-host")

    call_args = github_issue.atomic_update_with_retry.call_args
    self.assertEqual(call_args.kwargs["operation_system"], "Windows 11-24H2")


class TestRunStatusFlow(unittest.TestCase):
  """The relation between the final status, the warning comment and the winget report in run()."""

  MODULE = 'src.windows.update_scoop_softwares'

  def setUp(self):
    self.calls = MagicMock()
    self.issue = MagicMock()
    self.issue.get_markdown_computer_name.return_value = "dummy-host"
    self.issue.atomic_update_with_retry.side_effect = lambda **kwargs: self.calls.atomic(kwargs["status"])
    self.mocks = {
      'get_os_display_string': MagicMock(return_value="Windows 11-24H2"),
      'get_os_eol_info': MagicMock(return_value=("2030-01-01", False)),
      'update_scoop_repos': MagicMock(return_value=True),
      'get_scoop_status': MagicMock(return_value=[]),
      'get_running_apps': MagicMock(return_value={}),
      'update_scoop_apps': MagicMock(return_value={}),
      'cleanup_scoop': MagicMock(return_value=[]),
      'report_winget_outdated': MagicMock(),
    }
    self.mocks['cleanup_scoop'].side_effect = lambda: (self.calls.cleanup(), self.cleanup_result)[1]
    self.cleanup_result = []
    self.patchers = [patch(f'{self.MODULE}.{name}', mock) for name, mock in self.mocks.items()]
    for patcher in self.patchers:
      patcher.start()
      self.addCleanup(patcher.stop)

  def final_status(self):
    return self.issue.atomic_update_with_retry.call_args.kwargs["status"]

  def test_cleanup_runs_after_final_status_update(self):
    run(self.issue, "host")
    names = [c[0] for c in self.calls.mock_calls if c[0] in ("cleanup", "atomic")]
    self.assertEqual(names, ["atomic", "atomic", "atomic", "cleanup"])

  def test_app_still_outdated_after_zero_exit_marks_failed(self):
    outdated = {'name': 'a', 'installed': '1', 'latest': '2', 'missing': '', 'info': ''}
    self.mocks['get_scoop_status'].side_effect = [[outdated], [outdated]]
    self.mocks['update_scoop_apps'].return_value = {'a': True}
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "failed")
    self.assertEqual(self.issue.atomic_update_with_retry.call_args.kwargs["failed"], "1")
    self.assertEqual(self.issue.atomic_update_with_retry.call_args.kwargs["upgraded"], "0")

  def test_app_no_longer_outdated_after_update_is_success(self):
    outdated = {'name': 'a', 'installed': '1', 'latest': '2', 'missing': '', 'info': ''}
    self.mocks['get_scoop_status'].side_effect = [[outdated], []]
    self.mocks['update_scoop_apps'].return_value = {'a': True}
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "success")
    self.assertEqual(self.issue.atomic_update_with_retry.call_args.kwargs["upgraded"], "1")

  def test_other_outdated_app_not_attempted_does_not_fail_status(self):
    other = {'name': 'other', 'installed': '1', 'latest': '2', 'missing': '', 'info': ''}
    self.mocks['get_scoop_status'].side_effect = [[], [other]]
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "success")

  def test_cleanup_failure_posts_one_comment_and_keeps_success(self):
    self.cleanup_result = [("scoop cleanup *", 1)]
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "success")
    comments = [c.args[0] for c in self.issue.comment.call_args_list if "scoop cleanup" in c.args[0]]
    self.assertEqual(len(comments), 1)
    self.assertIn("| `scoop cleanup *` | 1 |", comments[0])

  def test_no_cleanup_comment_when_cleanup_succeeds(self):
    run(self.issue, "host")
    comments = [c.args[0] for c in self.issue.comment.call_args_list if "scoop cleanup" in c.args[0]]
    self.assertEqual(comments, [])

  def test_cleanup_comment_failure_does_not_change_status(self):
    self.cleanup_result = [("scoop cleanup *", 1)]
    def fail_on_cleanup_comment(body):
      if "scoop cleanup" in body:
        raise Exception("api down")
    self.issue.comment.side_effect = fail_on_cleanup_comment
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "success")
    self.mocks['report_winget_outdated'].assert_called_once()

  def test_repos_update_failure_marks_failed(self):
    self.mocks['update_scoop_repos'].return_value = False
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "failed")

  def test_app_update_failure_marks_failed(self):
    self.mocks['get_scoop_status'].side_effect = [[{'name': 'a', 'installed': '1', 'latest': '2', 'missing': '', 'info': ''}], []]
    self.mocks['update_scoop_apps'].return_value = {'a': False}
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "failed")

  def test_winget_report_failure_does_not_change_status(self):
    self.mocks['report_winget_outdated'].side_effect = Exception("boom")
    run(self.issue, "host")
    self.assertEqual(self.final_status(), "success")

  def test_winget_report_runs_after_final_status(self):
    self.mocks['report_winget_outdated'].side_effect = lambda: self.calls.winget()
    run(self.issue, "host")
    names = [c[0] for c in self.calls.mock_calls if c[0] in ("atomic", "winget")]
    self.assertEqual(names[-1], "winget")
    self.assertEqual(names.count("winget"), 1)


if __name__ == '__main__':
  unittest.main()
