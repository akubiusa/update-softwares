import json
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from src.windows.winget_outdated import (
  POWERSHELL_SCRIPT,
  WingetPinListError,
  classify,
  get_winget_outdated,
  get_winget_pinned_ids,
  report_winget_outdated,
)


def _completed(stdout="", returncode=0):
  return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _pkg(package_id, auto_updatable):
  return {
    "Id": package_id,
    "Name": f"name-{package_id}",
    "Installed": "1.0",
    "Latest": "2.0",
    "AutoUpdatable": auto_updatable,
  }


PIN_LIST_EN = (
  "Name      Id           Version  Source  Pin type\n"
  "--------------------------------------------------\n"
  "Pinned A  Vendor.PinA  1.0      winget  Pinning\n"
)

# Real-world fixture: `winget pin list` output on a Japanese-locale system
PIN_LIST_JA = (
  "名前        ID           バージョン  ソース  ピンの種類\n"
  "--------------------------------------------------------\n"
  "ピン済み B  Vendor.PinB  1.0         winget  Pinning\n"
)


class TestGetWingetOutdated(unittest.TestCase):
  def test_script_forces_utf8_output(self):
    # When redirected, pwsh writes in the console code page (cp932 on Japanese Windows), so UTF-8 must be forced explicitly
    self.assertTrue(POWERSHELL_SCRIPT.startswith("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"))

  def test_script_stops_on_cmdlet_errors(self):
    # Non-terminating errors would exit with code 0 and make a failed lookup look like "nothing outdated"
    self.assertIn("$ErrorActionPreference = 'Stop'\n", POWERSHELL_SCRIPT)

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_parses_json_list(self, mock_run):
    packages = [_pkg("Vendor.A", True), _pkg("Vendor.B", False)]
    mock_run.return_value = _completed(json.dumps(packages))
    self.assertEqual(get_winget_outdated(), packages)
    args = mock_run.call_args[0][0]
    self.assertEqual(args[:4], ["pwsh", "-NoProfile", "-NonInteractive", "-Command"])
    self.assertEqual(mock_run.call_args[1]["timeout"], 120)
    self.assertIs(mock_run.call_args[1]["stdin"], subprocess.DEVNULL)

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_wraps_single_object_into_list(self, mock_run):
    package = _pkg("Vendor.A", True)
    mock_run.return_value = _completed(json.dumps(package))
    self.assertEqual(get_winget_outdated(), [package])

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_empty_output_means_no_packages(self, mock_run):
    mock_run.return_value = _completed("  \n")
    self.assertEqual(get_winget_outdated(), [])

  @patch("src.windows.winget_outdated.subprocess.run", side_effect=FileNotFoundError("pwsh"))
  def test_returns_none_when_pwsh_missing(self, mock_run):
    self.assertIsNone(get_winget_outdated())

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_returns_none_on_nonzero_exit(self, mock_run):
    mock_run.return_value = _completed("", returncode=1)
    self.assertIsNone(get_winget_outdated())

  @patch("src.windows.winget_outdated.subprocess.run", side_effect=subprocess.TimeoutExpired("pwsh", 120))
  def test_returns_none_on_timeout(self, mock_run):
    self.assertIsNone(get_winget_outdated())

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_returns_none_on_invalid_json(self, mock_run):
    mock_run.return_value = _completed("not json")
    self.assertIsNone(get_winget_outdated())


class TestGetWingetPinnedIds(unittest.TestCase):
  @patch("src.windows.winget_outdated.subprocess.run")
  def test_matches_ids_in_english_output(self, mock_run):
    mock_run.return_value = _completed(PIN_LIST_EN)
    ids = get_winget_pinned_ids({"Vendor.PinA", "Vendor.Other"})
    self.assertEqual(ids, {"Vendor.PinA"})

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_matches_ids_in_japanese_output(self, mock_run):
    mock_run.return_value = _completed(PIN_LIST_JA)
    ids = get_winget_pinned_ids({"Vendor.PinB", "Vendor.Other"})
    self.assertEqual(ids, {"Vendor.PinB"})

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_pin_list_does_not_wait_for_stdin(self, mock_run):
    mock_run.return_value = _completed(PIN_LIST_EN)
    get_winget_pinned_ids({"Vendor.PinA"})
    self.assertIs(mock_run.call_args[1]["stdin"], subprocess.DEVNULL)

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_does_not_match_partial_id(self, mock_run):
    mock_run.return_value = _completed(PIN_LIST_EN)
    self.assertEqual(get_winget_pinned_ids({"Vendor.Pin"}), set())

  @patch("src.windows.winget_outdated.subprocess.run", side_effect=FileNotFoundError("winget"))
  def test_raises_when_winget_missing(self, mock_run):
    with self.assertRaises(WingetPinListError):
      get_winget_pinned_ids({"Vendor.PinA"})

  @patch("src.windows.winget_outdated.subprocess.run")
  def test_raises_on_nonzero_exit(self, mock_run):
    mock_run.return_value = _completed("", returncode=1)
    with self.assertRaises(WingetPinListError):
      get_winget_pinned_ids({"Vendor.PinA"})

  @patch("src.windows.winget_outdated.subprocess.run", side_effect=subprocess.TimeoutExpired("winget", 120))
  def test_raises_on_timeout(self, mock_run):
    with self.assertRaises(WingetPinListError):
      get_winget_pinned_ids({"Vendor.PinA"})


class TestClassify(unittest.TestCase):
  def test_excludes_pinned_and_splits_by_auto_updatable(self):
    outdated = [_pkg("Vendor.A", True), _pkg("Vendor.B", False), _pkg("Vendor.Pin", True)]
    auto, manual = classify(outdated, {"Vendor.Pin"})
    self.assertEqual([p["Id"] for p in auto], ["Vendor.A"])
    self.assertEqual([p["Id"] for p in manual], ["Vendor.B"])


class TestReportWingetOutdated(unittest.TestCase):
  @patch("src.windows.winget_outdated.get_winget_pinned_ids", return_value={"Vendor.Pin"})
  @patch("src.windows.winget_outdated.get_winget_outdated")
  def test_prints_both_sections_without_pinned(self, mock_outdated, mock_pinned):
    mock_outdated.return_value = [_pkg("Vendor.A", True), _pkg("Vendor.B", False), _pkg("Vendor.Pin", True)]
    with patch("builtins.print") as mock_print:
      report_winget_outdated()
    output = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
    self.assertIn("name-Vendor.A", output)
    self.assertIn("name-Vendor.B", output)
    self.assertNotIn("name-Vendor.Pin", output)
    self.assertIn("auto-updatable", output)
    self.assertIn("manual", output)

  @patch("src.windows.winget_outdated.get_winget_outdated", return_value=None)
  def test_skips_when_outdated_unavailable(self, mock_outdated):
    with patch("builtins.print") as mock_print:
      report_winget_outdated()
    mock_print.assert_not_called()

  @patch("src.windows.winget_outdated.get_winget_pinned_ids", side_effect=WingetPinListError("fail"))
  @patch("src.windows.winget_outdated.get_winget_outdated")
  def test_continues_without_pin_exclusion_when_pin_list_fails(self, mock_outdated, mock_pinned):
    mock_outdated.return_value = [_pkg("Vendor.A", True)]
    with patch("builtins.print") as mock_print:
      report_winget_outdated()
    output = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
    self.assertIn("name-Vendor.A", output)

  @patch("src.windows.winget_outdated.get_winget_outdated", return_value=[])
  def test_prints_none_message_when_empty(self, mock_outdated):
    with patch("builtins.print") as mock_print:
      report_winget_outdated()
    mock_print.assert_called_once_with("No outdated winget packages.")

  @patch("src.windows.winget_outdated.get_winget_outdated", side_effect=RuntimeError("boom"))
  def test_does_not_propagate_unexpected_errors(self, mock_outdated):
    report_winget_outdated()

  @patch("src.windows.winget_outdated.sys.stdout", MagicMock(encoding="cp932"))
  @patch("src.windows.winget_outdated.get_winget_pinned_ids", return_value=set())
  @patch("src.windows.winget_outdated.get_winget_outdated")
  def test_unencodable_name_does_not_drop_remaining_lines(self, mock_outdated, mock_pinned):
    unencodable = _pkg("Vendor.A", True)
    unencodable["Name"] = "name™"
    mock_outdated.return_value = [unencodable, _pkg("Vendor.B", False)]
    printed = []

    def fake_print(line):
      if "™" in line:
        raise UnicodeEncodeError("cp932", line, 0, 1, "unencodable")
      printed.append(line)

    with patch("builtins.print", side_effect=fake_print):
      report_winget_outdated()

    output = "\n".join(printed)
    self.assertIn("name? (Vendor.A)", output)
    self.assertIn("name-Vendor.B", output)


if __name__ == "__main__":
  unittest.main()
