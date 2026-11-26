"""Tests for port validation in common/config.py."""
import pytest

from common import config


@pytest.mark.parametrize("value, expected", [("1025", 1025), ("5050", 5050), ("65535", 65535), (" 8080 ", 8080)])
def test_valid_ports(value, expected):
    assert config.parse_port(value) == expected


@pytest.mark.parametrize("value", ["1024", "80", "0", "-1", "65536", "70000"])
def test_out_of_range_ports(value):
    with pytest.raises(ValueError, match="between 1025 and 65535"):
        config.parse_port(value)


@pytest.mark.parametrize("value", ["abc", "50.5", "", None, "5o5o"])
def test_non_integer_ports(value):
    with pytest.raises(ValueError, match="whole number"):
        config.parse_port(value)
