from click.testing import CliRunner

from mfs.cli import main


def test_version_command() -> None:
    result = CliRunner().invoke(main, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.0.0"
