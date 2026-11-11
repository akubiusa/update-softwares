"""Look up OS End-of-Life (EOL) information."""
import os
import platform
import requests
import time
from datetime import datetime
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def get_os_version_info() -> Tuple[str, str]:
  """
  Get the OS name and version.
    
  Returns:
    Tuple[str, str]: (OS name, version)
  """
  if os.name == 'nt':
    # Windows
    return get_windows_version_info()
  else:
    # Linux/Unix
    return get_linux_version_info()


def get_windows_version_info() -> Tuple[str, str]:
  """
  Get the Windows version.

  Read the build number and DisplayVersion from the Windows registry
  to determine the Windows version.
  A detailed version (for example 21H2, 22H2, 23H2, 24H2, 25H2) is included when available.

  Returns:
    Tuple[str, str]: ("Windows", version)
    The version looks like "10-22H2" or "11-24H2"
    and is "10" or "11" when the detailed version is unknown.
    Returns ("Windows", "Unknown") if the registry cannot be read.
  """
  try:
    import winreg

    registry_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path) as key:
      try:
        build = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
      except FileNotFoundError:
        build = winreg.QueryValueEx(key, "CurrentBuild")[0]

      try:
        display_version = winreg.QueryValueEx(key, "DisplayVersion")[0]
      except FileNotFoundError:
        display_version = None

    build_num = int(build)
    major_version = "11" if build_num >= 22000 else "10"
    if display_version:
      return ("Windows", f"{major_version}-{display_version}")
    return ("Windows", major_version)
  except Exception as e:
    logger.warning(f"Failed to read Windows version from registry: {e}")
    return ("Windows", "Unknown")


def get_linux_version_info() -> Tuple[str, str]:
  """
  Get the Linux distribution name and version.
    
  Read NAME and VERSION_ID from /etc/os-release.
  Fall back to the platform module when the file does not exist.
    
  Returns:
    Tuple[str, str]: (distribution name, version)
    For example ("Ubuntu", "22.04") or ("Debian", "12").
    Returns ("Linux", "Unknown") if reading the information fails.
    
  Raises:
  """
  try:
    if os.path.exists('/etc/os-release'):
      with open('/etc/os-release', 'r') as f:
        lines = f.readlines()
                
      os_info = {}
      for line in lines:
        if '=' in line:
          key, value = line.strip().split('=', 1)
          os_info[key] = value.strip('"')
            
      name = os_info.get('NAME', '')
      version = os_info.get('VERSION_ID', '')
            
      # Identify major distributions
      if 'Ubuntu' in name:
        return ("Ubuntu", version)
      elif 'Debian' in name:
        return ("Debian", version)
      elif 'Fedora' in name:
        return ("Fedora", version)
      elif 'CentOS' in name:
        return ("CentOS", version)
      elif 'Red Hat' in name or 'RHEL' in name:
        return ("RHEL", version)
      elif 'Rocky' in name:
        return ("Rocky Linux", version)
      elif 'AlmaLinux' in name:
        return ("AlmaLinux", version)
      elif 'openSUSE' in name:
        return ("openSUSE", version)
      else:
        # Other distributions
        return (name, version)
        
    # No /etc/os-release: use the platform module
    return (platform.system(), platform.release())
  except Exception:
    return ("Linux", "Unknown")


def get_os_eol_date_from_api(os_name: str, version: str, max_retries: int = 3) -> Optional[datetime]:
  """
  Fetch the OS EOL date from the endoflife.date API.
    
  Args:
    os_name: OS name
    version: OS version
    max_retries: Maximum number of attempts (default: 3)
        
  Returns:
    Optional[datetime]: EOL date, or None if it cannot be determined
  """
  # Map OS names to endoflife.date product names
  product_mapping = {
    "Windows": "windows",
    "Ubuntu": "ubuntu",
    "Debian": "debian",
    "Fedora": "fedora",
    "CentOS": "centos",
    "RHEL": "rhel",
    "Rocky Linux": "rocky-linux",
    "AlmaLinux": "almalinux",
    "openSUSE": "opensuse",
  }
    
  product = product_mapping.get(os_name)
  if product is None:
    return None
    
  for retry in range(max_retries):
    try:
      url = f"https://endoflife.date/api/{product}/{version}.json"
      response = requests.get(url, timeout=30)
            
      if response.status_code == 200:
        data = response.json()
        eol_str = data.get('eol')

        # eol is either a YYYY-MM-DD string or a boolean
        if isinstance(eol_str, bool):
          if not eol_str:
            # False means the product has not reached EOL (no date available)
            return None
          logger.warning(f"Unexpected boolean EOL value: {eol_str}")
          return None
        if not eol_str:
          return None
        if isinstance(eol_str, str):
          try:
            return datetime.strptime(eol_str, '%Y-%m-%d')
          except ValueError:
            logger.warning(f"Failed to parse EOL date: {eol_str}")
            return None
        logger.warning(f"Unexpected EOL value type: {type(eol_str)}")
        return None
      elif response.status_code == 404:
        # 404 means the API has no data for this version, so retrying is pointless
        return None
            
      # Retry on any other status code
      if retry < max_retries - 1:
        logger.debug(f"API request failed with status {response.status_code}, retrying... (attempt {retry + 1}/{max_retries})")
        time.sleep(1 * (retry + 1))  # linear backoff
        continue
            
      return None
    except requests.Timeout:
      if retry < max_retries - 1:
        logger.debug(f"API request timed out, retrying... (attempt {retry + 1}/{max_retries})")
        time.sleep(1 * (retry + 1))
        continue
      logger.debug(f"Failed to fetch EOL date from API for {os_name} {version}: Timeout after {max_retries} retries")
      return None
    except Exception as e:
      if retry < max_retries - 1:
        logger.debug(f"API request failed with error: {e}, retrying... (attempt {retry + 1}/{max_retries})")
        time.sleep(1 * (retry + 1))
        continue
      logger.debug(f"Failed to fetch EOL date from API for {os_name} {version}: {e}")
      return None


def get_os_eol_date(os_name: str, version: str) -> Optional[datetime]:
  """
  Get the EOL date of the OS.
    
  The date comes from the endoflife.date API.
  Returns None when the API does not provide it.
    
  Args:
    os_name: OS name
    version: OS version
        
  Returns:
    Optional[datetime]: EOL date, or None if the API does not provide it
  """
  return get_os_eol_date_from_api(os_name, version)



def format_eol_info(eol_date: Optional[datetime]) -> Tuple[str, bool]:
  """
  Format the EOL information for the Issue table.
    
  Args:
    eol_date: EOL date, or None if unknown
        
  Returns:
    Tuple[str, bool]: (formatted string, whether EOL is already past or less than 90 days away)
  """
  if eol_date is None:
    return ("不明", False)
    
  now = datetime.now()
  days_until_eol = (eol_date - now).days
    
  # EOL has already passed
  if days_until_eol < 0:
    return (f"**{eol_date.strftime('%Y/%m/%d')} (期限切れ)**", True)
    
  # Less than 90 days until EOL
  is_critical = days_until_eol < 90
    
  if is_critical:
    return (f"**{eol_date.strftime('%Y/%m/%d')} ({days_until_eol} 日後)**", True)
  else:
    return (f"{eol_date.strftime('%Y/%m/%d')} ({days_until_eol} 日後)", False)


def get_os_eol_info() -> Tuple[str, bool]:
  """
  Get the EOL information of the current OS.
    
  Returns:
    Tuple[str, bool]: (EOL information string, whether EOL is already past or less than 90 days away)
  """
  os_name, version = get_os_version_info()
  eol_date = get_os_eol_date(os_name, version)
  return format_eol_info(eol_date)


def get_os_display_string() -> str:
  """
  Get the OS name and version string shown in the "OS" column.

  On Linux, return PRETTY_NAME from /etc/os-release as is.
  When it is unavailable, or on Windows, return the (os_name, version) pair from
  get_linux_version_info() / get_windows_version_info()
  formatted as "{os_name} {version}".

  Returns:
    str: The display string, or "Unknown" if it cannot be obtained
  """
  try:
    if os.name == 'nt':
      os_name, version = get_windows_version_info()
      return f"{os_name} {version}"

    # Linux: prefer PRETTY_NAME from /etc/os-release
    if os.path.exists('/etc/os-release'):
      with open('/etc/os-release', 'r') as f:
        lines = f.readlines()

      os_info = {}
      for line in lines:
        if '=' in line:
          key, value = line.strip().split('=', 1)
          os_info[key] = value.strip('"')

      pretty_name = os_info.get('PRETTY_NAME', '')
      if pretty_name:
        return pretty_name

    # No PRETTY_NAME: format (os_name, version) instead
    os_name, version = get_linux_version_info()
    return f"{os_name} {version}"
  except Exception:
    return "Unknown"
