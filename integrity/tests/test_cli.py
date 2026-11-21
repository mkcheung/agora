import os
import subprocess
import sys
from pathlib import Path

import pytest

from integrity import cli
from integrity.common import sheets as sh
from integrity.tests.helpers import make_card, make_sheet_dict

ROOT = Path(__file__).resolve().parents[2]

# Every lazily dispatched command and the handler it must resolve to. The test below only checks that the
# handler exists; it never runs a command (running `build` or `quiz` would call real models).
HANDLERS = {
    "corpus": (cli._B, "cmd_corpus"), "build": (cli._B, "cmd_build"),
    "review": (cli._BS, "cmd_review"), "publish": (cli._BS, "cmd_publish"), "retire": (cli._BS, "cmd_retire"),
    "sheet check": (cli._BS, "cmd_sheet_check"),
    "quiz": (cli._Q, "cmd_quiz"), "report": (cli._Q, "cmd_report"), "compare": (cli._Q, "cmd_compare"),
    "regrade": (cli._Q, "cmd_regrade"), "calibrate": (cli._Q, "cmd_calibrate"),
}


def run(argv):
    return cli.main(argv.split())


def test_help_lists_every_command(capsys):
    assert run("--help") == 0
    out = capsys.readouterr().out
    for name in ("corpus", "build", "review", "publish", "retire", "sheet", "quiz", "report", "compare",
                 "regrade", "calibrate"):
        assert name in out


def test_python_dash_m_help_in_subprocess():
    r = subprocess.run([sys.executable, "-m", "integrity", "--help"], cwd=ROOT, capture_output=True, text=True, check=False,
                       env={**os.environ, "INTEGRITY_CONFIG": ""})
    assert r.returncode == 0 and "calibrate" in r.stdout


def test_version(capsys):
    assert run("--version") == 0
    assert "integrity 0.1.0" in capsys.readouterr().out


@pytest.mark.parametrize("command,target", HANDLERS.items())
def test_every_command_has_an_implemented_handler(command, target):
    import importlib

    module, func = target
    assert callable(getattr(importlib.import_module(module), func))


def test_all_flags_parse():
    """Flags are checked at parse time so the test stays valid whichever handlers have landed."""
    p = cli.build_parser()
    p.parse_args(["corpus", "--source", "f.epub", "--excluded", "EL-len", "--show", "3"])
    p.parse_args(["build", "--count", "5", "--false-premise", "2", "--source", "a", "--source", "b", "--author", "X", "--author", "Y", "--seed", "7", "--dry-run"])
    assert p.parse_args(["review", "--batch", "b-1"]).batch == "b-1"
    assert p.parse_args(["publish", "--note", "hi"]).note == "hi"
    assert p.parse_args(["retire", "c-1", "--reason", "x"]).reason == "x"
    assert p.parse_args(["sheet", "check", "--apply"]).apply is True
    p.parse_args(["quiz", "--sheet", "v001", "--limit", "3", "--author", "X", "--cards", "a,b", "--agora", "m:f", "--namespace", "ns", "--mechanical-only", "--resume", "r", "--strict"])
    p.parse_args(["report", "latest", "--format", "md"])
    p.parse_args(["compare", "a", "b", "--force"])
    p.parse_args(["calibrate", "r", "--n", "3"])


def test_usage_errors_exit_1(capsys):
    assert run("") == 1
    assert run("nosuchcommand") == 1
    assert run("retire c-1") == 1  # --reason required
    assert run("report --format xml") == 1
    assert run("sheet") == 1


def test_bad_config_exit_4(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[build]\nbogus = 1\n")
    monkeypatch.setenv("INTEGRITY_CONFIG", str(bad))
    assert run("sheet list") == 4
    assert "configuration error" in capsys.readouterr().err


def test_sheet_list_empty_and_show_no_sheet(capsys):
    assert run("sheet list") == 0
    assert "no published answer sheets" in capsys.readouterr().out
    assert run("sheet show") == 2
    assert "no published answer sheet" in capsys.readouterr().err


def publish_two_cards(data_dir):
    cards = [
        make_card(),
        make_card(card_id="c-hidden", holdout=True, question="SECRET QUESTION?",
                  key_points=[{"id": "kp1", "statement": "SECRET STATEMENT", "quote": "SECRET QUOTE words here ok"}]),
    ]
    sh.write_sheet(data_dir, make_sheet_dict(cards=cards))


def test_sheet_list_and_show_hide_holdout(data_dir, capsys):
    publish_two_cards(data_dir)
    assert run("sheet list") == 0
    out = capsys.readouterr().out
    assert "v001" in out and "n" in out
    assert run("sheet show") == 0
    out = capsys.readouterr().out
    assert "cards: 2  holdout: 1" in out and "How does Locke explain property?" in out
    assert "SECRET" not in out and "holdout: question and key points hidden" in out
    assert run("sheet show v001 --reveal-holdout") == 0
    assert "SECRET QUESTION?" in capsys.readouterr().out


def test_sheet_show_card(data_dir, capsys):
    publish_two_cards(data_dir)
    assert run("sheet show --card c-hidden") == 0
    out = capsys.readouterr().out
    assert "SECRET" not in out and "hidden" in out
    assert run("sheet show --card c-hidden --reveal-holdout") == 0
    assert "SECRET QUOTE" in capsys.readouterr().out
    assert run("sheet show --card c-nope") == 1
    assert run("sheet show v009") == 2


def test_tampered_sheet_exit_2(data_dir, capsys):
    publish_two_cards(data_dir)
    p = data_dir / "sheets" / "sheet-v001.json"
    os.chmod(p, 0o644)
    p.write_text(p.read_text().replace("How does Locke", "How did Locke"))
    assert run("sheet show") == 2
    assert "mismatch" in capsys.readouterr().err
    assert run("sheet list") == 2
