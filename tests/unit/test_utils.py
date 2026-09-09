from esocial_noise.utils import mask_cpf, normalize_cpf, normalize_text


def test_normalize_cpf_preserves_leading_zeroes() -> None:
    assert normalize_cpf("001.234.567-89") == "00123456789"
    assert normalize_cpf(123456789.0) == "00123456789"


def test_mask_and_normalize_text() -> None:
    assert mask_cpf("00123456789") == "***.***.***-89"
    assert normalize_text("  RuÍDO\n Ocupacional ") == "ruído ocupacional"
