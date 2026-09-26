import pytest

from petroleum_openserver.units import SimpleUnitConverter, UnitConversionError, ipt_unit_conv


def test_identity_conversion_returns_value_unchanged():
    c = SimpleUnitConverter()
    assert c.convert("psi", "psi", 123.4) == 123.4


def test_bar_to_psi():
    c = SimpleUnitConverter()
    assert c.convert("bar", "psi", 1.0) == pytest.approx(14.5037738)


def test_psi_to_bar_is_inverse_of_bar_to_psi():
    c = SimpleUnitConverter()
    value = 250.0
    round_tripped = c.convert("psi", "bar", c.convert("bar", "psi", value))
    assert round_tripped == pytest.approx(value)


def test_fahrenheit_to_celsius():
    c = SimpleUnitConverter()
    assert c.convert("degF", "degC", 212) == pytest.approx(100.0)


def test_unknown_conversion_raises():
    c = SimpleUnitConverter()
    with pytest.raises(UnitConversionError):
        c.convert("furlongs", "psi", 1.0)


def test_module_level_helper_uses_default_converter():
    assert ipt_unit_conv("stb/d", "stb/d", 999) == 999
