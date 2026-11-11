"""Tests for the OS EOL feature."""
import unittest
from unittest.mock import patch, mock_open, MagicMock
from datetime import datetime, timedelta

from src.os_eol import (
  get_windows_version_info,
  get_linux_version_info,
  get_os_eol_date,
  get_os_eol_date_from_api,
  format_eol_info,
  get_os_eol_info,
  get_os_display_string
)


class TestOSEOL(unittest.TestCase):
  """Test cases for the OS EOL feature."""

  def _mock_windows_registry(self, values):
    """Build a winreg mock that returns the given Windows registry values."""
    winreg = MagicMock()
    winreg.HKEY_LOCAL_MACHINE = object()
    key = MagicMock()
    winreg.OpenKey.return_value.__enter__.return_value = key

    def query_value(_key, name):
      if name not in values:
        raise FileNotFoundError(name)
      return values[name], 1

    winreg.QueryValueEx.side_effect = query_value
    return winreg

  @patch('os.name', 'nt')
  def test_get_windows_version_info_windows_10(self):
    """Get Windows 10 version info."""
    winreg = self._mock_windows_registry({"CurrentBuildNumber": "19045"})

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "10")

  @patch('os.name', 'nt')
  def test_get_windows_version_info_windows_11(self):
    """Get Windows 11 version info."""
    winreg = self._mock_windows_registry({"CurrentBuildNumber": "22621"})

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "11")

  @patch('os.name', 'nt')
  def test_get_windows_version_info_by_build_number(self):
    """Detect the Windows version from the build number."""
    winreg = self._mock_windows_registry({"CurrentBuildNumber": "22000"})

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "11")  # Build 22000 and later is Windows 11

  @patch('os.name', 'nt')
  def test_get_windows_version_info_with_display_version_22h2(self):
    """Get the detailed Windows 10 22H2 version."""
    winreg = self._mock_windows_registry({
      "CurrentBuildNumber": "19045",
      "DisplayVersion": "22H2",
    })

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "10-22H2")

  @patch('os.name', 'nt')
  def test_get_windows_version_info_with_display_version_24h2(self):
    """Get the detailed Windows 11 24H2 version."""
    winreg = self._mock_windows_registry({
      "CurrentBuildNumber": "26100",
      "DisplayVersion": "24H2",
    })

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "11-24H2")

  @patch('os.name', 'nt')
  def test_get_windows_version_info_without_display_version(self):
    """Return the major version even without DisplayVersion."""
    winreg = self._mock_windows_registry({"CurrentBuildNumber": "19045"})

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "10")

  @patch('os.name', 'nt')
  def test_get_windows_version_info_current_build_fallback(self):
    """Fall back to CurrentBuild when CurrentBuildNumber is missing."""
    winreg = self._mock_windows_registry({"CurrentBuild": "26100"})

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "11")

  @patch('os.name', 'nt')
  def test_get_windows_version_info_registry_error(self):
    """Return Unknown when the registry cannot be read."""
    winreg = self._mock_windows_registry({})
    winreg.OpenKey.side_effect = OSError("registry unavailable")

    with patch.dict('sys.modules', {'winreg': winreg}):
      os_name, version = get_windows_version_info()

    self.assertEqual(os_name, "Windows")
    self.assertEqual(version, "Unknown")

  @patch('os.path.exists')
  @patch('builtins.open', mock_open(read_data='NAME="Ubuntu"\nVERSION_ID="22.04"\n'))
  def test_get_linux_version_info_ubuntu(self, mock_exists):
    """Get Ubuntu version info."""
    mock_exists.return_value = True
        
    os_name, version = get_linux_version_info()
        
    self.assertEqual(os_name, "Ubuntu")
    self.assertEqual(version, "22.04")
    
  @patch('os.path.exists')
  @patch('builtins.open', mock_open(read_data='NAME="Debian GNU/Linux"\nVERSION_ID="12"\n'))
  def test_get_linux_version_info_debian(self, mock_exists):
    """Get Debian version info."""
    mock_exists.return_value = True
        
    os_name, version = get_linux_version_info()
        
    # Debian returns the NAME field as is
    self.assertIn("Debian", os_name)
    self.assertEqual(version, "12")
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_windows_10(self, mock_get):
    """Get the Windows 10 EOL date (mocked API)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'eol': '2025-10-14'}
    mock_get.return_value = mock_response
        
    eol_date = get_os_eol_date("Windows", "10")
        
    self.assertIsNotNone(eol_date)
    self.assertEqual(eol_date, datetime(2025, 10, 14))
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_windows_11(self, mock_get):
    """Get the Windows 11 EOL date (mocked API)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'eol': '2031-10-14'}
    mock_get.return_value = mock_response
        
    eol_date = get_os_eol_date("Windows", "11")
        
    self.assertIsNotNone(eol_date)
    self.assertEqual(eol_date, datetime(2031, 10, 14))
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_ubuntu_2204(self, mock_get):
    """Get the Ubuntu 22.04 EOL date (mocked API)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'eol': '2027-04-30'}
    mock_get.return_value = mock_response
        
    eol_date = get_os_eol_date("Ubuntu", "22.04")
        
    self.assertIsNotNone(eol_date)
    self.assertEqual(eol_date, datetime(2027, 4, 30))
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_debian_12(self, mock_get):
    """Get the Debian 12 EOL date (mocked API)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'eol': '2028-06-30'}
    mock_get.return_value = mock_response
        
    eol_date = get_os_eol_date("Debian", "12")
        
    self.assertIsNotNone(eol_date)
    self.assertEqual(eol_date, datetime(2028, 6, 30))
    
  def test_get_os_eol_date_unknown(self):
    """Get the EOL date of an unknown OS."""
    eol_date = get_os_eol_date("UnknownOS", "1.0")
        
    self.assertIsNone(eol_date)
    
  def test_format_eol_info_unknown(self):
    """Format an unknown EOL date."""
    formatted, is_critical = format_eol_info(None)
        
    self.assertEqual(formatted, "不明")
    self.assertFalse(is_critical)
    
  def test_format_eol_info_expired(self):
    """Format an EOL date in the past."""
    past_date = datetime.now() - timedelta(days=30)
    formatted, is_critical = format_eol_info(past_date)
        
    self.assertIn("期限切れ", formatted)
    self.assertTrue(is_critical)
    self.assertIn("**", formatted)  # emphasized
    
  def test_format_eol_info_critical(self):
    """Format an EOL date less than 90 days away."""
    near_future_date = datetime.now() + timedelta(days=50)
    formatted, is_critical = format_eol_info(near_future_date)
        
    # The day count depends on when the test runs, so match a pattern
    self.assertRegex(formatted, r"\d+ 日後")
    self.assertTrue(is_critical)
    self.assertIn("**", formatted)  # emphasized
    
  def test_format_eol_info_safe(self):
    """Format an EOL date 90 or more days away."""
    future_date = datetime.now() + timedelta(days=200)
    formatted, is_critical = format_eol_info(future_date)
        
    # The day count depends on when the test runs, so match a pattern
    self.assertRegex(formatted, r"\d+ 日後")
    self.assertFalse(is_critical)
    self.assertNotIn("**", formatted)  # not emphasized
    
  @patch('os.name', 'nt')
  @patch('src.os_eol.get_windows_version_info')
  def test_get_os_eol_info_windows(self, mock_get_version):
    """Get OS EOL info on Windows."""
    mock_get_version.return_value = ("Windows", "10")
        
    eol_info, is_critical = get_os_eol_info()
        
    self.assertIsNotNone(eol_info)
    self.assertIsInstance(eol_info, str)
    self.assertIsInstance(is_critical, bool)
    
  @patch('os.name', 'posix')
  @patch('src.os_eol.get_linux_version_info')
  def test_get_os_eol_info_linux(self, mock_get_version):
    """Get OS EOL info on Linux."""
    mock_get_version.return_value = ("Ubuntu", "22.04")
        
    eol_info, is_critical = get_os_eol_info()
        
    self.assertIsNotNone(eol_info)
    self.assertIsInstance(eol_info, str)
    self.assertIsInstance(is_critical, bool)
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_from_api_success(self, mock_get):
    """Fetch the EOL date from the API successfully."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      'eol': '2027-04-30'
    }
    mock_get.return_value = mock_response
        
    eol_date = get_os_eol_date_from_api("Ubuntu", "22.04")
        
    self.assertIsNotNone(eol_date)
    self.assertEqual(eol_date, datetime(2027, 4, 30))
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_from_api_not_found(self, mock_get):
    """The API does not know the product."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response
        
    eol_date = get_os_eol_date_from_api("Ubuntu", "99.99")
        
    self.assertIsNone(eol_date)
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_from_api_timeout(self, mock_get):
    """The API times out."""
    mock_get.side_effect = Exception("Timeout")
        
    eol_date = get_os_eol_date_from_api("Ubuntu", "22.04")
        
    self.assertIsNone(eol_date)
    
  @patch('src.os_eol.requests.get')
  def test_get_os_eol_date_from_api_retry(self, mock_get):
    """The API request is retried."""
    # The first 2 attempts fail and the 3rd succeeds
    mock_response_fail = MagicMock()
    mock_response_fail.status_code = 500
        
    mock_response_success = MagicMock()
    mock_response_success.status_code = 200
    mock_response_success.json.return_value = {'eol': '2027-04-30'}
        
    mock_get.side_effect = [mock_response_fail, mock_response_fail, mock_response_success]
        
    with patch('time.sleep'):  # skip sleeping
      eol_date = get_os_eol_date_from_api("Ubuntu", "22.04")
        
    self.assertIsNotNone(eol_date)
    self.assertEqual(eol_date, datetime(2027, 4, 30))
    self.assertEqual(mock_get.call_count, 3)
    
  @patch('os.path.exists')
  @patch('builtins.open', mock_open(read_data='NAME="Fedora Linux"\nVERSION_ID="40"\n'))
  def test_get_linux_version_info_fedora(self, mock_exists):
    """Get Fedora version info."""
    mock_exists.return_value = True
        
    os_name, version = get_linux_version_info()
        
    self.assertEqual(os_name, "Fedora")
    self.assertEqual(version, "40")
    
  @patch('os.path.exists')
  @patch('builtins.open', mock_open(read_data='NAME="CentOS Linux"\nVERSION_ID="7"\n'))
  def test_get_linux_version_info_centos(self, mock_exists):
    """Get CentOS version info."""
    mock_exists.return_value = True
        
    os_name, version = get_linux_version_info()
        
    self.assertEqual(os_name, "CentOS")
    self.assertEqual(version, "7")

  @patch('os.name', 'posix')
  @patch('os.path.exists')
  @patch('builtins.open', mock_open(read_data='NAME="Ubuntu"\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.5 LTS"\n'))
  def test_get_os_display_string_linux_pretty_name(self, mock_exists):
    """On Linux, return PRETTY_NAME as is when available."""
    mock_exists.return_value = True

    result = get_os_display_string()

    self.assertEqual(result, "Ubuntu 22.04.5 LTS")

  @patch('os.name', 'posix')
  @patch('os.path.exists')
  @patch('src.os_eol.get_linux_version_info')
  def test_get_os_display_string_linux_no_os_release(self, mock_get_version, mock_exists):
    """Fall back to (os_name, version) when /etc/os-release does not exist."""
    mock_exists.return_value = False
    mock_get_version.return_value = ("Ubuntu", "22.04")

    result = get_os_display_string()

    self.assertEqual(result, "Ubuntu 22.04")

  @patch('os.name', 'posix')
  @patch('os.path.exists')
  @patch('builtins.open', mock_open(read_data='NAME="Ubuntu"\nVERSION_ID="22.04"\n'))
  @patch('src.os_eol.get_linux_version_info')
  def test_get_os_display_string_linux_no_pretty_name(self, mock_get_version, mock_exists):
    """Fall back to (os_name, version) when /etc/os-release has no PRETTY_NAME."""
    mock_exists.return_value = True
    mock_get_version.return_value = ("Ubuntu", "22.04")

    result = get_os_display_string()

    self.assertEqual(result, "Ubuntu 22.04")

  @patch('os.name', 'nt')
  @patch('src.os_eol.get_windows_version_info')
  def test_get_os_display_string_windows(self, mock_get_version):
    """On Windows, return (os_name, version) joined."""
    mock_get_version.return_value = ("Windows", "11-24H2")

    result = get_os_display_string()

    self.assertEqual(result, "Windows 11-24H2")

  @patch('os.name', 'posix')
  @patch('os.path.exists', side_effect=Exception("boom"))
  def test_get_os_display_string_exception_fallback(self, mock_exists):
    """Return Unknown when an exception is raised."""
    result = get_os_display_string()

    self.assertEqual(result, "Unknown")


if __name__ == "__main__":
  unittest.main()
