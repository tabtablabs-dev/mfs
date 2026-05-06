import click


@click.group()
def main() -> None:
    """Modal Volume filesystem/query CLI for agents."""


@main.command()
def version() -> None:
    """Print version."""
    from mfs import __version__

    click.echo(__version__)
