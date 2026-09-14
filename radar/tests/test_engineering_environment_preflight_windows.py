from __future__ import annotations

import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "windows"
    / "crt_engineering_environment_preflight_windows.ps1"
)


class EngineeringEnvironmentPreflightWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_fails_fast_before_git_on_non_windows(self) -> None:
        environment_check = self.text.index('$env:OS -ne "Windows_NT"')
        first_git_operation = self.text.index("git rev-parse")

        self.assertLess(environment_check, first_git_operation)
        self.assertIn("WRONG_EXECUTION_ENVIRONMENT", self.text)

    def test_locks_the_canonical_repo_root(self) -> None:
        self.assertIn(
            '"C:\\Users\\maxwe\\OneDrive\\文件\\GitHub\\CRT_Master"',
            self.text,
        )
        self.assertIn("git rev-parse --show-toplevel", self.text)
        self.assertIn("WRONG_REPO_ROOT", self.text)

    def test_checks_required_read_only_git_surfaces(self) -> None:
        self.assertIn("git worktree list --porcelain", self.text)
        self.assertIn("git stash list", self.text)
        self.assertNotIn("git stash apply", self.text)
        self.assertNotIn("git stash pop", self.text)
        self.assertNotIn("git stash drop", self.text)
        self.assertIn("git remote get-url origin", self.text)

    def test_checks_push_readiness_without_writing_a_remote_ref(self) -> None:
        self.assertIn("git config --get-all credential.helper", self.text)
        self.assertIn("if (-not $credentialHelper)", self.text)
        self.assertIn("git ls-remote --exit-code --heads origin", self.text)
        self.assertIn("git push --dry-run origin", self.text)

    def test_outputs_only_pass_and_required_summary_after_success(self) -> None:
        self.assertIn('Write-Output "PASS"', self.text)
        self.assertIn("stash_count=", self.text)
        self.assertIn("worktree_capability=available", self.text)
        self.assertNotIn("Dashboard", self.text)


if __name__ == "__main__":
    unittest.main()
