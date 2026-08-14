"""
E2E tests for CLI argument parsing and dispatch.
"""

import pytest
import sys
from unittest.mock import patch, MagicMock

from config import settings


pytestmark = pytest.mark.e2e


def _args(**overrides):
    """Build a complete parsed-args stub. Every CLI flag defaults to its
    inactive value so a test only sets the one it cares about — and adding a
    new flag can't accidentally fire (MagicMock would otherwise fabricate a
    truthy attribute)."""
    defaults = dict(
        list_categories=False, quick=None, exam=False, learn=None,
        practice=None, adaptive=False,
        export_code=False, import_code=None, import_mode='replace',
        # Real values, not MagicMocks: main() feeds these to
        # settings.set_exam_version() and the task panel, both of which
        # validate their input rather than accepting anything truthy.
        exam_version=settings.DEFAULT_EXAM_VERSION,
        gui=None, gui_bind='127.0.0.1',
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.fixture(autouse=True)
def mock_subprocess():
    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=mock_result):
        yield


class TestVersionFlag:
    """Test --version output."""

    def test_version_outputs_4_0_0(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            sys.argv = ["rhcsa_simulator.py", "--version"]
            from rhcsa_simulator import parse_args
            parse_args()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "4.0.0" in captured.out


class TestListCategories:
    """Test --list-categories output."""

    def test_list_categories_shows_all(self, capsys, initialized_registry):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args:
            mock_args.return_value = _args(
                list_categories=True,
                quick=None,
                exam=False,
                learn=None,
                practice=None,
                adaptive=False,
            )
            result = main()

        captured = capsys.readouterr()
        assert "Domain 1" in captured.out
        assert "lvm" in captured.out
        assert result == 0


class TestCLIDispatch:
    """Test CLI flag dispatch to correct functions."""

    def test_exam_flag_calls_run_exam_mode(self):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args, \
             patch("utils.helpers.require_root"), \
             patch("core.exam.run_exam_mode") as mock_exam:
            mock_args.return_value = _args(
                list_categories=False,
                quick=None,
                exam=True,
                learn=None,
                practice=None,
                adaptive=False,
            )
            main()
            mock_exam.assert_called_once()

    def test_adaptive_flag_calls_run_adaptive_mode(self):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args, \
             patch("utils.helpers.require_root"), \
             patch("core.adaptive.run_adaptive_mode") as mock_adaptive:
            mock_args.return_value = _args(
                list_categories=False,
                quick=None,
                exam=False,
                learn=None,
                practice=None,
                adaptive=True,
            )
            main()
            mock_adaptive.assert_called_once()

    def test_learn_flag_calls_run_learn_mode(self):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args, \
             patch("utils.helpers.require_root"), \
             patch("core.learn.run_learn_mode") as mock_learn:
            mock_args.return_value = _args(
                list_categories=False,
                quick=None,
                exam=False,
                learn="all",
                practice=None,
                adaptive=False,
            )
            main()
            mock_learn.assert_called_once()

    def test_practice_valid_category(self, initialized_registry):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args, \
             patch("utils.helpers.require_root"), \
             patch("core.practice.PracticeSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            mock_args.return_value = _args(
                list_categories=False,
                quick=None,
                exam=False,
                learn=None,
                practice="lvm",
                adaptive=False,
            )
            result = main()
            assert result == 0
            mock_session.start.assert_called_once()

    def test_practice_invalid_category(self, initialized_registry, capsys):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args, \
             patch("utils.helpers.require_root"):
            mock_args.return_value = _args(
                list_categories=False,
                quick=None,
                exam=False,
                learn=None,
                practice="nonexistent",
                adaptive=False,
            )
            result = main()
            assert result == 1
            captured = capsys.readouterr()
            assert "Unknown category" in captured.out

    def test_quick_flag(self):
        from rhcsa_simulator import main

        with patch("rhcsa_simulator.parse_args") as mock_args, \
             patch("utils.helpers.require_root"), \
             patch("rhcsa_simulator.run_quick_practice") as mock_quick:
            mock_args.return_value = _args(
                list_categories=False,
                quick="all",
                exam=False,
                learn=None,
                practice=None,
                adaptive=False,
            )
            main()
            mock_quick.assert_called_once_with("all", gui_port=8080, gui_bind='0.0.0.0')
