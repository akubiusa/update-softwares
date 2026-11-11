import os
import re
import requests
import time

class GitHubIssue:
  body = None
  software_updates = None
  initial_body_state = None
  pending_updates = None
  RETRY_SLEEP_MULTIPLIER = 0.5  # Sleep multiplier for retry backoff
  status_mapping = {
    "success": "✅",
    "running": "⏳",
    "failed": "🔴",
  }

  row_regex = re.compile(r"(?P<markdown>.*) <!-- update-softwares#(?P<computer_name>.+)#(?P<package_manager>.+) -->")

  def __init__(self, repo_name, issue_number, github_token):
    self.repo_name = repo_name
    self.issue_number = issue_number
    self.github_token = github_token
    self.pending_updates = {}

    self.body = self.__get_issue_body()
    self.initial_body_state = self.body
    self.software_updates = self.__get_software_update_rows()

  def get_package_managers(self, computer_name):
    package_managers = []
    for software_update in self.software_updates:
      if software_update["computer_name"] == computer_name:
        package_managers.append(software_update["package_manager"])

    return package_managers

  def _get_checkmark(self, status, os_eol_critical=False):
    """
    Get the checkmark for a status and EOL state.
    
    Args:
      status: One of "success", "running", "failed"
      os_eol_critical: Whether EOL is critical (already past or less than 90 days away)
      
    Returns:
      str: The checkmark string
    """
    if os_eol_critical:
      return "🔴"
    return self.status_mapping.get(status, status)
  
  def _build_markdown_row(self, software_update):
    """
    Build a Markdown table row from software update information.
    
    Args:
      software_update: Software update information dictionary
      
    Returns:
      str: The formatted Markdown table row
    """
    markdown = software_update["markdown"]
    
    # The row has an OS EOL column only in the new format
    if "os_eol" in markdown:
      return "| " + " | ".join([
        markdown["checkmark"],
        markdown["computer_name"],
        markdown["operation_system"],
        markdown["package_manager"],
        markdown["upgraded"],
        markdown["failed"],
        markdown["os_eol"]
      ]) + " |"
    else:
      return "| " + " | ".join([
        markdown["checkmark"],
        markdown["computer_name"],
        markdown["operation_system"],
        markdown["package_manager"],
        markdown["upgraded"],
        markdown["failed"]
      ]) + " |"

  def update_software_update_row(self, computer_name, package_manager, status, upgraded, failed, os_eol=None, os_eol_critical=False, operation_system=None):
    if status not in self.status_mapping:
      raise Exception(f"Invalid status: {status}. Valid values are {list(self.status_mapping.keys())}")

    checkmark = self._get_checkmark(status, os_eol_critical)

    for software_update in self.software_updates:
      if software_update["computer_name"] == computer_name and software_update["package_manager"] == package_manager:
        software_update["markdown"]["checkmark"] = checkmark
        software_update["markdown"]["upgraded"] = upgraded
        software_update["markdown"]["failed"] = failed

        # Update OS EOL only when given
        if os_eol is not None:
          software_update["markdown"]["os_eol"] = os_eol

        # Update the OS name and version only when given
        if operation_system is not None:
          software_update["markdown"]["operation_system"] = operation_system

        software_update["markdown"]["raw"] = self._build_markdown_row(software_update)

        return True

    return False

  def atomic_update_with_retry(self, computer_name, package_manager, status, upgraded, failed, os_eol=None, os_eol_critical=False, max_retries=3, operation_system=None):
    """
    Atomically update the issue body with retry logic to handle concurrent updates.
    This method combines update processing and GitHub Issue body reflection into a single operation.
    """
    for retry_count in range(max_retries):
      try:
        # Get the latest issue body to check for conflicts
        current_body = self.__get_issue_body()
        
        # Parse the current software updates from the latest body
        current_software_updates = self._get_software_update_rows_from_body(current_body)
        
        # Find and update the specific row
        updated = False
        for software_update in current_software_updates:
          if software_update["computer_name"] == computer_name and software_update["package_manager"] == package_manager:
            # Update the status
            checkmark = self._get_checkmark(status, os_eol_critical)
            
            software_update["markdown"]["checkmark"] = checkmark
            software_update["markdown"]["upgraded"] = upgraded
            software_update["markdown"]["failed"] = failed
            
            # Update OS EOL only when given
            if os_eol is not None:
              software_update["markdown"]["os_eol"] = os_eol

            # Update the OS name and version only when given
            if operation_system is not None:
              software_update["markdown"]["operation_system"] = operation_system

            software_update["markdown"]["raw"] = self._build_markdown_row(software_update)
            updated = True
            break
        
        if not updated:
          raise Exception(f"No matching software update row found for {computer_name}#{package_manager}")
        
        # Build the new body with updated content
        new_body = self._build_updated_body(current_body, current_software_updates)
        
        # Attempt to update the issue
        response = requests.patch(
          f"https://api.github.com/repos/{self.repo_name}/issues/{self.issue_number}",
          headers={
            "Authorization": f"token {self.github_token}"
          },
          json={
            "body": new_body
          }
        )
        
        if response.status_code == 200:
          # Success - update our local state
          self.body = new_body
          self.software_updates = current_software_updates
          return True
        else:
          raise Exception(f"Failed to update issue body: {response.text}")
          
      except Exception as e:
        if retry_count == max_retries - 1:
          # Last retry failed, propagate the exception
          raise e
        else:
          # Wait briefly before retrying to reduce contention
          time.sleep(self.RETRY_SLEEP_MULTIPLIER * (retry_count + 1))
          continue
    
    return False

  def _build_updated_body(self, body, software_updates):
    """Build the updated issue body with the modified software updates."""
    rows = body.split("\n")
    new_rows = []
    for row in rows:
      m = self.row_regex.match(row)
      if m is None:
        new_rows.append(row)
        continue

      computer_name = m.group("computer_name")
      package_manager = m.group("package_manager")
      for software_update in software_updates:
        if software_update["computer_name"] == computer_name and software_update["package_manager"] == package_manager:
          new_rows.append(software_update["markdown"]["raw"] + f" <!-- update-softwares#{computer_name}#{package_manager} -->")
          break

    return "\n".join(new_rows)

  def _get_software_update_rows_from_body(self, body):
    """Parse software update rows from a given body content."""
    software_updates = []
    lines = body.split("\n")

    for line in lines:
      m = self.row_regex.match(line)
      if m is None:
        continue

      # Split on | to get each cell
      markdown = m.group("markdown")
      split_markdown = markdown.split("|")
      
      # Supports 8 columns (old format) and 9 columns (new format with OS EOL)
      if len(split_markdown) == 8:
        # Old format (no OS EOL)
        checkmark = split_markdown[1].strip()
        view_computer_name = split_markdown[2].strip()
        operation_system = split_markdown[3].strip()
        package_manager = split_markdown[4].strip()
        upgraded = split_markdown[5].strip()
        failed = split_markdown[6].strip()
        
        software_updates.append({
          "markdown": {
            "checkmark": checkmark,
            "computer_name": view_computer_name,
            "operation_system": operation_system,
            "package_manager": package_manager,
            "upgraded": upgraded,
            "failed": failed,
            "raw": markdown
          },
          "computer_name": m.group("computer_name"),
          "package_manager": m.group("package_manager")
        })
      elif len(split_markdown) == 9:
        # New format (with OS EOL)
        checkmark = split_markdown[1].strip()
        view_computer_name = split_markdown[2].strip()
        operation_system = split_markdown[3].strip()
        package_manager = split_markdown[4].strip()
        upgraded = split_markdown[5].strip()
        failed = split_markdown[6].strip()
        os_eol = split_markdown[7].strip()
        
        software_updates.append({
          "markdown": {
            "checkmark": checkmark,
            "computer_name": view_computer_name,
            "operation_system": operation_system,
            "package_manager": package_manager,
            "upgraded": upgraded,
            "failed": failed,
            "os_eol": os_eol,
            "raw": markdown
          },
          "computer_name": m.group("computer_name"),
          "package_manager": m.group("package_manager")
        })
      else:
        # Skip rows with an unsupported number of columns
        continue

    return software_updates

  def update_issue_body(self):
    # Fetch the latest Issue body to reduce conflicts with concurrent runs
    self.body = self.__get_issue_body()
    
    # Rewrite the rows of the body from self.software_updates:
    # find the lines ending with <!-- update-softwares#computer_name#package_manager --> and replace them
    rows = self.body.split("\n")
    new_rows = []
    for row in rows:
      m = self.row_regex.match(row)
      if m is None:
        new_rows.append(row)
        continue

      computer_name = m.group("computer_name")
      package_manager = m.group("package_manager")
      for software_update in self.software_updates:
        if software_update["computer_name"] == computer_name and software_update["package_manager"] == package_manager:
          new_rows.append(software_update["markdown"]["raw"] + f" <!-- update-softwares#{computer_name}#{package_manager} -->")
          break

    self.body = "\n".join(new_rows)

    response = requests.patch(
      f"https://api.github.com/repos/{self.repo_name}/issues/{self.issue_number}",
      headers={
        "Authorization" : f"token {self.github_token}"
      },
      json={
        "body": self.body
      }
    )

    if response.status_code != 200:
      raise Exception(f"Failed to update issue body: {response.text}")

    return True

  def get_markdown_computer_name(self, computer_name):
    for software_update in self.software_updates:
      if software_update["computer_name"] == computer_name:
        return software_update["markdown"]["computer_name"]

    raise Exception("Failed to get markdown computer name")

  def comment(self, body):
    response = requests.post(
      f"https://api.github.com/repos/{self.repo_name}/issues/{self.issue_number}/comments",
      headers={
        "Authorization" : f"token {self.github_token}"
      },
      json={
        "body": body
      }
    )
    if response.status_code != 201:
      raise Exception(f"Failed to post comment: {response.text}")

  def __get_issue_body(self):
    url = f"https://api.github.com/repos/{self.repo_name}/issues/{self.issue_number}"
    headers = {
      "Authorization": f"token {self.github_token}"
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
      raise Exception(f"Failed to get issue body: {response.text}")

    return response.json()["body"]

  def __get_software_update_rows(self):
    software_updates = []
    lines = self.body.split("\n")

    for line in lines:
      m = self.row_regex.match(line)
      if m is None:
        continue

      # Split on | to get each cell
      markdown = m.group("markdown")
      split_markdown = markdown.split("|")
      
      # Supports 8 columns (old format) and 9 columns (new format with OS EOL)
      if len(split_markdown) == 8:
        # Old format (no OS EOL)
        checkmark = split_markdown[1].strip()
        view_computer_name = split_markdown[2].strip()
        operation_system = split_markdown[3].strip()
        package_manager = split_markdown[4].strip()
        upgraded = split_markdown[5].strip()
        failed = split_markdown[6].strip()
        
        software_updates.append({
          "markdown": {
            "checkmark": checkmark,
            "computer_name": view_computer_name,
            "operation_system": operation_system,
            "package_manager": package_manager,
            "upgraded": upgraded,
            "failed": failed,
            "raw": markdown
          },
          "computer_name": m.group("computer_name"),
          "package_manager": m.group("package_manager")
        })
      elif len(split_markdown) == 9:
        # New format (with OS EOL)
        checkmark = split_markdown[1].strip()
        view_computer_name = split_markdown[2].strip()
        operation_system = split_markdown[3].strip()
        package_manager = split_markdown[4].strip()
        upgraded = split_markdown[5].strip()
        failed = split_markdown[6].strip()
        os_eol = split_markdown[7].strip()
        
        software_updates.append({
          "markdown": {
            "checkmark": checkmark,
            "computer_name": view_computer_name,
            "operation_system": operation_system,
            "package_manager": package_manager,
            "upgraded": upgraded,
            "failed": failed,
            "os_eol": os_eol,
            "raw": markdown
          },
          "computer_name": m.group("computer_name"),
          "package_manager": m.group("package_manager")
        })
      else:
        # Skip rows with an unsupported number of columns
        continue

    return software_updates


def is_valid_issue_number(issue_number):
  if issue_number is None:
    return False

  if not issue_number.isdigit():
    return False

  return True

def get_real_hostname():
  if os.name == 'nt':
    return os.environ['COMPUTERNAME']
  else:
    return os.uname()[1]

def get_github_token():
  if not os.path.exists("data/github_token.txt"):
    raise Exception("Please create data/github_token.txt")

  with open("data/github_token.txt", "r", encoding="utf-8") as f:
    return f.read().strip()

def is_root():
    return os.geteuid() == 0

def is_windows():
    """Check if the current environment is Windows"""
    return os.name == 'nt'

def is_linux():
    """Check if the current environment is Linux/Unix"""
    return os.name == 'posix'
