"""Self-check for config.py, no API/CLI calls. Run: python tests/test_config.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import require_year, load_tax_config


def test_require_year_present():
    require_year({2026: {"x": 1}}, 2026, "test")  # no raise


def test_require_year_missing():
    try:
        require_year({2026: {}}, 2027, "KIA scale")
        assert False, "expected SystemExit"
    except SystemExit as e:
        msg = str(e)
        assert "2027" in msg and "2026" in msg  # names the bad year and what's available


def test_load_config_present(path):
    cfg = load_tax_config(2026, path)
    assert cfg["wage"] == 100


def test_load_config_missing_year(path):
    try:
        load_tax_config(2099, path)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "2099" in str(e)


def test_load_config_missing_file():
    try:
        load_tax_config(2026, "/no/such/dir/tax.toml")
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "not found" in str(e)


def test_load_config_bad_toml(path):
    try:
        load_tax_config(2026, path)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "valid TOML" in str(e)


if __name__ == "__main__":
    test_require_year_present()
    test_require_year_missing()
    test_load_config_missing_file()

    good = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    good.write("[2026]\nwage = 100\n")
    good.close()
    bad = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    bad.write("[2026]\nwage = \n")  # invalid TOML (no value)
    bad.close()
    try:
        test_load_config_present(good.name)
        test_load_config_missing_year(good.name)
        test_load_config_bad_toml(bad.name)
    finally:
        os.unlink(good.name)
        os.unlink(bad.name)

    print("all checks OK")
