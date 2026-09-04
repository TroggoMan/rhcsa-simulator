"""
E2E tests for MenuSystem - dispatch, dashboard, help.
"""

import pytest
from unittest.mock import patch, MagicMock
from core.menu import MenuSystem


pytestmark = pytest.mark.e2e


class TestMenuDispatch:
    """Test menu returns correct action strings."""

    @pytest.mark.parametrize("key,expected", [
        ("q", "quick_practice"),
        ("e", "exam"),
        ("1", "learn"),
        ("2", "practice"),
        ("3", "adaptive"),
        ("4", "dashboard"),
        ("5", "export"),
        ("s", "setup"),
        ("?", "help"),
        ("0", "exit"),
    ])
    def test_menu_key_dispatch(self, key, expected):
        menu = MenuSystem()
        with patch("builtins.input", return_value=key), \
             patch("core.menu.fmt"):
            result = menu.display_main_menu()
        assert result == expected

    def test_invalid_key_reprompts(self):
        menu = MenuSystem()
        # Invalid -> press enter on error prompt -> repaint menu -> exit
        with patch("builtins.input", side_effect=["x", "", "0"]), \
             patch("core.menu.fmt"):
            result = menu.display_main_menu()
        assert result == "exit"


class TestDashboard:
    """Test dashboard display."""

    def test_dashboard_empty_db(self, tmp_db):
        menu = MenuSystem()
        with patch("core.menu.fmt") as mock_fmt, \
             patch("builtins.input", return_value=""), \
             patch("core.results_db.get_results_db", return_value=tmp_db):
            mock_fmt.bold.side_effect = lambda x: x
            mock_fmt.info.side_effect = lambda x: x
            mock_fmt.success.side_effect = lambda x: x
            mock_fmt.error.side_effect = lambda x: x
            mock_fmt.dim.side_effect = lambda x: x
            mock_fmt.format_category_name.side_effect = lambda x: x
            menu.show_dashboard()

    def test_dashboard_with_data(self, tmp_db):
        tmp_db.save_exam_result(
            exam_id="exam-001",
            start_time="2025-01-01T10:00:00",
            end_time="2025-01-01T13:00:00",
            duration_seconds=10800,
            total_score=250,
            max_score=300,
            passed=True,
            reboot_passed=True,
        )
        tmp_db.save_practice_attempt(
            task_id="t1", category="lvm", difficulty="exam", domain=4,
            score=10, max_score=10, passed=True,
        )

        menu = MenuSystem()
        with patch("core.menu.fmt") as mock_fmt, \
             patch("builtins.input", return_value=""), \
             patch("core.results_db.get_results_db", return_value=tmp_db):
            mock_fmt.bold.side_effect = lambda x: x
            mock_fmt.info.side_effect = lambda x: x
            mock_fmt.success.side_effect = lambda x: x
            mock_fmt.error.side_effect = lambda x: x
            mock_fmt.dim.side_effect = lambda x: x
            mock_fmt.format_category_name.side_effect = lambda x: x
            menu.show_dashboard()


class TestHelp:
    """Test help display."""

    def test_help_mentions_version(self, capsys):
        menu = MenuSystem()
        with patch("builtins.input", return_value=""), \
             patch("core.menu.fmt") as mock_fmt:
            mock_fmt.bold.side_effect = lambda x: x
            mock_fmt.dim.side_effect = lambda x: x
            menu.show_help()
        captured = capsys.readouterr()
        assert "4.0.0" in captured.out


class TestSnapshotImport:
    """Import should accept a pasted code or, per issue #102, an absolute
    path to a file holding the code — pasting a long code can be silently
    truncated by the terminal's paste buffer, but a file never is."""

    def _make_code(self, tmp_db):
        from core import progress_code
        tmp_db.save_practice_attempt(
            task_id="t1", category="lvm", difficulty="exam", domain=4,
            score=10, max_score=10, passed=True,
        )
        return progress_code.export_code(tmp_db)

    def test_import_from_pasted_code(self, tmp_db, tmp_path):
        from core import progress_code
        from utils.helpers import confirm_action

        src_db_path = tmp_path / "src.db"
        from core.results_db import ResultsDB
        src_db = ResultsDB(db_path=src_db_path)
        code = self._make_code(src_db)

        menu = MenuSystem()
        with patch("builtins.input", side_effect=[code, "", ""]), \
             patch("core.menu.fmt") as mock_fmt:
            mock_fmt.bold.side_effect = lambda x: x
            mock_fmt.dim.side_effect = lambda x: x
            mock_fmt.success.side_effect = lambda x: x
            mock_fmt.error.side_effect = lambda x: x
            mock_fmt.warning.side_effect = lambda x: x
            menu._snapshot_import(progress_code, tmp_db, confirm_action)

        assert tmp_db.get_practice_count() == 1

    def test_import_from_file_path(self, tmp_db, tmp_path):
        from core import progress_code
        from utils.helpers import confirm_action
        from core.results_db import ResultsDB

        src_db = ResultsDB(db_path=tmp_path / "src.db")
        code = self._make_code(src_db)
        code_file = tmp_path / "progress_code.txt"
        code_file.write_text(code + "\n")

        menu = MenuSystem()
        with patch("builtins.input", side_effect=[str(code_file), "", ""]), \
             patch("core.menu.fmt") as mock_fmt:
            mock_fmt.bold.side_effect = lambda x: x
            mock_fmt.dim.side_effect = lambda x: x
            mock_fmt.success.side_effect = lambda x: x
            mock_fmt.error.side_effect = lambda x: x
            mock_fmt.warning.side_effect = lambda x: x
            menu._snapshot_import(progress_code, tmp_db, confirm_action)

        assert tmp_db.get_practice_count() == 1

    def test_import_from_missing_file_path_reports_error(self, tmp_db, tmp_path):
        from core import progress_code
        from utils.helpers import confirm_action

        missing = tmp_path / "does-not-exist.txt"

        menu = MenuSystem()
        with patch("builtins.input", side_effect=[str(missing), "", ""]), \
             patch("core.menu.fmt") as mock_fmt:
            mock_fmt.bold.side_effect = lambda x: x
            mock_fmt.dim.side_effect = lambda x: x
            mock_fmt.success.side_effect = lambda x: x
            mock_fmt.error.side_effect = lambda x: x
            mock_fmt.warning.side_effect = lambda x: x
            menu._snapshot_import(progress_code, tmp_db, confirm_action)

        assert tmp_db.get_practice_count() == 0
        assert any("Invalid code" in str(c.args[0]) for c in mock_fmt.error.call_args_list)
