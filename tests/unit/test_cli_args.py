"""
Tests for the CLI argument surface.

The exam task panel is ON by default — the real exam presents its questions
in a browser window, so that is the honest default for a simulator — and
--no-gui opts out. These are the flags people reach for under time pressure,
so the combinations need to resolve predictably.
"""

import sys

import pytest

import rhcsa_simulator
from core.task_gui import DEFAULT_PORT


def parse(*argv):
    saved = sys.argv
    try:
        sys.argv = ['rhcsa-simulator'] + list(argv)
        return rhcsa_simulator.parse_args()
    finally:
        sys.argv = saved


def test_panel_is_on_by_default():
    assert parse('--exam').gui == DEFAULT_PORT


def test_no_gui_turns_it_off():
    assert parse('--exam', '--no-gui').gui is None


def test_bare_gui_uses_the_default_port():
    assert parse('--exam', '--gui').gui == DEFAULT_PORT


def test_gui_takes_a_port():
    assert parse('--exam', '--gui', '9000').gui == 9000


@pytest.mark.parametrize('argv,expected', [
    (('--gui', '9000', '--no-gui'), None),
    (('--no-gui', '--gui', '9000'), 9000),
    (('--no-gui', '--gui'), DEFAULT_PORT),
])
def test_last_flag_wins(argv, expected):
    """Both flags write the same dest, so a later one overrides an earlier
    one rather than erroring or being silently ignored."""
    assert parse('--exam', *argv).gui == expected


def test_bind_defaults_to_all_interfaces():
    """The exam VM is usually headless, so the browser is on another machine.
    On a stock RHEL/Alma box firewalld still gates who can actually reach it."""
    assert parse('--exam').gui_bind == '0.0.0.0'


def test_bind_can_be_restricted():
    assert parse('--exam', '--gui-bind', '127.0.0.1').gui_bind == '127.0.0.1'


def test_port_must_be_numeric():
    with pytest.raises(SystemExit):
        parse('--exam', '--gui', 'eight-thousand')
