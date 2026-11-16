import unittest
from unittest.mock import patch, MagicMock
from src import GitHubIssue


def wire_fake_issue(mock_get, mock_patch, initial_body, patch_results=None):
  """
  Make the mocked GET/PATCH behave like a GitHub Issue that stores its body.

  Args:
    mock_get: Mock for requests.get.
    mock_patch: Mock for requests.patch.
    initial_body: Body returned until a PATCH is applied.
    patch_results: Per-PATCH outcomes in call order; calls beyond the list apply normally.
      None applies the PATCH body, ("status", code) fails with that status code,
      ("overwrite", body) returns 200 but leaves `body` stored (a concurrent host's PATCH won).

  Returns:
    dict: {"body": current stored body}
  """
  state = {"body": initial_body}
  results = list(patch_results or [])

  def fake_get(*args, **kwargs):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"body": state["body"]}
    return response

  def fake_patch(*args, **kwargs):
    result = results.pop(0) if results else None
    response = MagicMock()
    response.status_code = 200
    if result is None:
      state["body"] = kwargs["json"]["body"]
    elif result[0] == "status":
      response.status_code = result[1]
      response.text = "error"
    else:
      state["body"] = result[1]
    return response

  mock_get.side_effect = fake_get
  mock_patch.side_effect = fake_patch
  return state


class TestGitHubIssueAtomic(unittest.TestCase):
  def setUp(self):
    self.repo_name = "test/repo"
    self.issue_number = "123"
    self.github_token = "test_token"

  @patch('src.requests.get')
  def test_github_issue_initialization(self, mock_get):
    """Test GitHubIssue initialization with atomic update support."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "body": "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->\n"
                                      "| ✅ | Computer2 | Windows | scoop | 5 | 0 | <!-- update-softwares#Computer2#scoop -->"
    }
    mock_get.return_value = mock_response

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    self.assertEqual(github_issue.repo_name, self.repo_name)
    self.assertEqual(github_issue.issue_number, self.issue_number)
    self.assertEqual(github_issue.github_token, self.github_token)
    self.assertIsNotNone(github_issue.pending_updates)
    self.assertIsNotNone(github_issue.initial_body_state)
    self.assertEqual(len(github_issue.software_updates), 2)

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_retry_success(self, mock_get, mock_patch):
    """Test successful atomic update without retry."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    result = github_issue.atomic_update_with_retry(
      computer_name="Computer1",
      package_manager="apt",
      status="success",
      upgraded="5",
      failed="0"
    )

    self.assertTrue(result)
    mock_patch.assert_called_once()
    self.assertEqual(mock_get.call_count, 3)  # constructor, read, verify

    updated_body = mock_patch.call_args[1]['json']['body']
    self.assertEqual(
      updated_body,
      "| ✅ | Computer1 | Linux | apt | 5 | 0 | <!-- update-softwares#Computer1#apt -->"
    )

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_retry_overwrites_operation_system(self, mock_get, mock_patch):
    """The OS column is overwritten when operation_system is passed."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    result = github_issue.atomic_update_with_retry(
      computer_name="Computer1",
      package_manager="apt",
      status="success",
      upgraded="5",
      failed="0",
      operation_system="Ubuntu 22.04.5 LTS",
    )

    self.assertTrue(result)
    updated_body = mock_patch.call_args[1]['json']['body']
    self.assertIn("Ubuntu 22.04.5 LTS", updated_body)
    self.assertNotIn("| Linux |", updated_body)

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_retry_keeps_operation_system_when_none(self, mock_get, mock_patch):
    """The existing OS column value is kept when operation_system is omitted."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    github_issue.atomic_update_with_retry(
      computer_name="Computer1",
      package_manager="apt",
      status="success",
      upgraded="5",
      failed="0",
    )

    updated_body = mock_patch.call_args[1]['json']['body']
    self.assertIn("| Linux |", updated_body)

  @patch('src.requests.get')
  def test_update_software_update_row_overwrites_operation_system(self, mock_get):
    """update_software_update_row() overwrites operation_system."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
      "body": "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    }
    mock_get.return_value = mock_response

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    result = github_issue.update_software_update_row(
      computer_name="Computer1",
      package_manager="apt",
      status="success",
      upgraded="5",
      failed="0",
      operation_system="Ubuntu 22.04.5 LTS",
    )

    self.assertTrue(result)
    updated_row = next(
      su for su in github_issue.software_updates
      if su["computer_name"] == "Computer1" and su["package_manager"] == "apt"
    )
    self.assertEqual(updated_row["markdown"]["operation_system"], "Ubuntu 22.04.5 LTS")
    self.assertIn("Ubuntu 22.04.5 LTS", updated_row["markdown"]["raw"])

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_retry_overwrites_operation_system_new_format(self, mock_get, mock_patch):
    """operation_system is overwritten for rows in the new format (with an os_eol column) as well."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | 不明 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    github_issue.atomic_update_with_retry(
      computer_name="Computer1",
      package_manager="apt",
      status="success",
      upgraded="5",
      failed="0",
      os_eol="2027-04-30 (300 日後)",
      operation_system="Ubuntu 22.04.5 LTS",
    )

    updated_body = mock_patch.call_args[1]['json']['body']
    self.assertIn("Ubuntu 22.04.5 LTS", updated_body)
    self.assertIn("2027-04-30", updated_body)

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_retry_on_failure(self, mock_get, mock_patch):
    """Test atomic update with retry on API failure."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    # Fail first (409 Conflict), succeed second
    wire_fake_issue(mock_get, mock_patch, initial_body, patch_results=[("status", 409)])

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    with patch('time.sleep'):
      result = github_issue.atomic_update_with_retry(
        computer_name="Computer1",
        package_manager="apt",
        status="failed",
        upgraded="3",
        failed="2"
      )

    self.assertTrue(result)
    self.assertEqual(mock_patch.call_count, 2)  # Should retry once

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_max_retries_exceeded(self, mock_get, mock_patch):
    """Test atomic update when max retries are exceeded."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body, patch_results=[("status", 500)] * 2)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    with patch('time.sleep'):
      with self.assertRaises(Exception) as context:
        github_issue.atomic_update_with_retry(
          computer_name="Computer1",
          package_manager="apt",
          status="failed",
          upgraded="0",
          failed="1",
          max_retries=2
        )

    self.assertIn("Failed to update issue body", str(context.exception))
    self.assertEqual(mock_patch.call_count, 2)  # Should retry max_retries times

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_retries_when_own_row_was_overwritten(self, mock_get, mock_patch):
    """A 200 PATCH whose row was reverted by a concurrent PATCH is retried."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    state = wire_fake_issue(mock_get, mock_patch, initial_body, patch_results=[("overwrite", initial_body)])

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    with patch('time.sleep'):
      result = github_issue.atomic_update_with_retry(
        computer_name="Computer1",
        package_manager="apt",
        status="success",
        upgraded="5",
        failed="0"
      )

    self.assertTrue(result)
    self.assertEqual(mock_patch.call_count, 2)
    self.assertEqual(
      state["body"],
      "| ✅ | Computer1 | Linux | apt | 5 | 0 | <!-- update-softwares#Computer1#apt -->"
    )

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_raises_when_own_row_never_reflected(self, mock_get, mock_patch):
    """Verification failure on every attempt raises after max_retries PATCH calls."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body, patch_results=[("overwrite", initial_body)] * 2)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    with patch('time.sleep'):
      with self.assertRaises(Exception) as context:
        github_issue.atomic_update_with_retry(
          computer_name="Computer1",
          package_manager="apt",
          status="success",
          upgraded="5",
          failed="0",
          max_retries=2
        )

    self.assertIn("Verification failed: row for Computer1#apt was not reflected", str(context.exception))
    self.assertEqual(mock_patch.call_count, 2)

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_retry_keeps_other_hosts_row(self, mock_get, mock_patch):
    """The retried attempt rebuilds from the latest body and keeps the other host's row."""
    row_a_before = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->"
    row_b_before = "| ⏳ | Computer2 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer2#apt -->"
    row_b_after = "| ✅ | Computer2 | Linux | apt | 7 | 0 | <!-- update-softwares#Computer2#apt -->"
    row_a_after = "| ✅ | Computer1 | Linux | apt | 5 | 0 | <!-- update-softwares#Computer1#apt -->"
    # Host B's stale-base PATCH lands right after host A's PATCH and reverts A's row.
    state = wire_fake_issue(
      mock_get,
      mock_patch,
      row_a_before + "\n" + row_b_before,
      patch_results=[("overwrite", row_a_before + "\n" + row_b_after)],
    )

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    with patch('time.sleep'):
      result = github_issue.atomic_update_with_retry(
        computer_name="Computer1",
        package_manager="apt",
        status="success",
        upgraded="5",
        failed="0"
      )

    self.assertTrue(result)
    self.assertEqual(mock_patch.call_count, 2)
    self.assertEqual(mock_patch.call_args[1]['json']['body'], row_a_after + "\n" + row_b_after)
    self.assertEqual(state["body"], row_a_after + "\n" + row_b_after)

  @patch('src.requests.get')
  def test_get_software_update_rows_from_body(self, mock_get):
    """Test parsing software update rows from body content."""
    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {"body": "test"}
    mock_get.return_value = mock_get_response

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    test_body = (
      "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->\n"
      "| ✅ | Computer2 | Windows | scoop | 5 | 0 | <!-- update-softwares#Computer2#scoop -->"
    )

    software_updates = github_issue._get_software_update_rows_from_body(test_body)

    self.assertEqual(len(software_updates), 2)

    # Check first entry
    self.assertEqual(software_updates[0]["computer_name"], "Computer1")
    self.assertEqual(software_updates[0]["package_manager"], "apt")
    self.assertEqual(software_updates[0]["markdown"]["checkmark"], "⏳")
    self.assertEqual(software_updates[0]["markdown"]["computer_name"], "Computer1")
    self.assertEqual(software_updates[0]["markdown"]["operation_system"], "Linux")

    # Check second entry
    self.assertEqual(software_updates[1]["computer_name"], "Computer2")
    self.assertEqual(software_updates[1]["package_manager"], "scoop")
    self.assertEqual(software_updates[1]["markdown"]["checkmark"], "✅")
    self.assertEqual(software_updates[1]["markdown"]["upgraded"], "5")

  @patch('src.requests.get')
  def test_build_updated_body(self, mock_get):
    """Test building updated issue body with modified software updates."""
    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {"body": "test"}
    mock_get.return_value = mock_get_response

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    original_body = (
      "# Update Status\n"
      "| ⏳ | Computer1 | Linux | apt | 0 | 0 | <!-- update-softwares#Computer1#apt -->\n"
      "| ✅ | Computer2 | Windows | scoop | 5 | 0 | <!-- update-softwares#Computer2#scoop -->\n"
      "End of document"
    )

    # Parse and modify software updates
    software_updates = github_issue._get_software_update_rows_from_body(original_body)
    software_updates[0]["markdown"]["checkmark"] = "✅"
    software_updates[0]["markdown"]["upgraded"] = "3"
    software_updates[0]["markdown"]["failed"] = "1"
    software_updates[0]["markdown"]["raw"] = "| ✅ | Computer1 | Linux | apt | 3 | 1 |"

    updated_body = github_issue._build_updated_body(original_body, software_updates)

    # Verify the updated body contains the new values
    self.assertIn("| ✅ | Computer1 | Linux | apt | 3 | 1 | <!-- update-softwares#Computer1#apt -->", updated_body)
    self.assertIn("| ✅ | Computer2 | Windows | scoop | 5 | 0 | <!-- update-softwares#Computer2#scoop -->", updated_body)
    self.assertIn("# Update Status", updated_body)
    self.assertIn("End of document", updated_body)

  @patch('src.requests.get')
  def test_parse_body_with_os_eol_column(self, mock_get):
    """Test parsing issue body with OS EOL column."""
    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get_response.json.return_value = {"body": "test"}
    mock_get.return_value = mock_get_response

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    # New format (with an OS EOL column)
    body_with_eol = (
      "| ⏳ | Computer1 | Linux | apt | 0 | 0 | 2027/04/30 (500 日後) | <!-- update-softwares#Computer1#apt -->\n"
      "| 🔴 | Computer2 | Windows | scoop | 5 | 0 | **2025/10/14 (50 日後)** | <!-- update-softwares#Computer2#scoop -->"
    )

    software_updates = github_issue._get_software_update_rows_from_body(body_with_eol)

    self.assertEqual(len(software_updates), 2)

    # First entry (with OS EOL)
    self.assertEqual(software_updates[0]["computer_name"], "Computer1")
    self.assertEqual(software_updates[0]["package_manager"], "apt")
    self.assertEqual(software_updates[0]["markdown"]["os_eol"], "2027/04/30 (500 日後)")

    # Second entry (with OS EOL, critical)
    self.assertEqual(software_updates[1]["computer_name"], "Computer2")
    self.assertEqual(software_updates[1]["package_manager"], "scoop")
    self.assertEqual(software_updates[1]["markdown"]["os_eol"], "**2025/10/14 (50 日後)**")

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_os_eol(self, mock_get, mock_patch):
    """Test atomic update with OS EOL information."""
    initial_body = "| ⏳ | Computer1 | Linux | apt | 0 | 0 | 不明 | <!-- update-softwares#Computer1#apt -->"
    wire_fake_issue(mock_get, mock_patch, initial_body)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    result = github_issue.atomic_update_with_retry(
      computer_name="Computer1",
      package_manager="apt",
      status="success",
      upgraded="5",
      failed="0",
      os_eol="2027/04/30 (800 日後)",
      os_eol_critical=False
    )

    self.assertTrue(result)
    mock_patch.assert_called_once()

    updated_body = mock_patch.call_args[1]['json']['body']
    self.assertEqual(
      updated_body,
      "| ✅ | Computer1 | Linux | apt | 5 | 0 | 2027/04/30 (800 日後) | <!-- update-softwares#Computer1#apt -->"
    )

  @patch('src.requests.patch')
  @patch('src.requests.get')
  def test_atomic_update_with_critical_os_eol(self, mock_get, mock_patch):
    """Test atomic update with critical OS EOL (less than 90 days)."""
    initial_body = "| ⏳ | Computer1 | Windows | scoop | 0 | 0 | 不明 | <!-- update-softwares#Computer1#scoop -->"
    wire_fake_issue(mock_get, mock_patch, initial_body)

    github_issue = GitHubIssue(self.repo_name, self.issue_number, self.github_token)

    # Critical EOL turns the checkmark into 🔴
    result = github_issue.atomic_update_with_retry(
      computer_name="Computer1",
      package_manager="scoop",
      status="success",
      upgraded="13",
      failed="0",
      os_eol="**2025/12/31 (20 日後)**",
      os_eol_critical=True
    )

    self.assertTrue(result)
    mock_patch.assert_called_once()

    updated_body = mock_patch.call_args[1]['json']['body']
    self.assertEqual(
      updated_body,
      "| 🔴 | Computer1 | Windows | scoop | 13 | 0 | **2025/12/31 (20 日後)** | <!-- update-softwares#Computer1#scoop -->"
    )

if __name__ == "__main__":
  unittest.main()
