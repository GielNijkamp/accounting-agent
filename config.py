"""Tax-year configuration: load tax.toml and validate that a year is actually filled in.

Shared by the tax/asset/wealth agents so an unconfigured year fails with a clear message
(pointing at what to add) instead of a bare KeyError. Call these at the top of main(), before
any Moneybird or LLM work, so a bad year fails fast.
"""
import tomllib
from pathlib import Path


def require_year(table: dict, year: int, what: str) -> None:
    """Fail with a clear message if `year` has no entry in a statutory-amount table
    (TAX / KIA / ANNUAL_MARGIN). Raises SystemExit — a clean one-line CLI error, no traceback."""
    if year not in table:
        have = ", ".join(str(y) for y in sorted(table)) or "none"
        raise SystemExit(
            f"No {what} amounts configured for {year} (available: {have}). "
            f"Add a {year} entry to the table in the code — see docs/TODO.md task 6."
        )


def load_tax_config(year: int, path: str = "tax.toml") -> dict:
    """Return the [year] section of tax.toml, with clear errors for a missing file, invalid
    TOML, or a missing year section. Raises SystemExit on any of those."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"{path} not found. Copy tax.example.toml to {path} and fill in your figures "
            f"(see docs/TODO.md task 3)."
        )
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{path} is not valid TOML: {e}")
    try:
        return data[str(year)]
    except KeyError:
        have = ", ".join(sorted(data)) or "none"
        raise SystemExit(
            f"No [{year}] section in {path} (available: {have}). "
            f"Add a [{year}] block — see tax.example.toml and docs/TODO.md task 3."
        )
