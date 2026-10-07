from __future__ import annotations

import unittest
from pathlib import Path

from vfat_report.cli import parse_args


class HistoryCliTests(unittest.TestCase):
    def test_history_root_is_explicit_and_disabled_by_default(self) -> None:
        defaults = parse_args(["--input", "input.json"])
        enabled = parse_args(
            ["--input", "input.json", "--history-root", "saved-reports"]
        )

        self.assertIsNone(defaults.history_root)
        self.assertEqual(enabled.history_root, Path("saved-reports"))


if __name__ == "__main__":
    unittest.main()
