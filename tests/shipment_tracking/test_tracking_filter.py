from app.pages.tracking_page import row_matches


def _row(sku: str, name: str, tracking: str = "", fba: str = "") -> list[str]:
    values = [""] * 13
    values[7] = fba
    values[8] = tracking
    values[10] = sku
    values[12] = name
    return values


def test_empty_query_keeps_all():
    row = _row("GP995-4P-BLACK", "Pants")
    assert row_matches(row, "", "")
    assert row_matches(row, "  ", "")


def test_sku_substring_case_insensitive():
    row = _row("GP995-4P-BLACK", "Pants")
    assert row_matches(row, "gp995", "")
    assert not row_matches(row, "GP996", "")


def test_name_substring_and_both_filters():
    pants = _row("GP995-4P-BLACK", "Pants")
    shirt = _row("GP995-TEE", "T-Shirt")
    assert row_matches(pants, "", "pant")
    assert not row_matches(shirt, "", "Pants")
    assert row_matches(pants, "GP995", "Pants")
    assert not row_matches(shirt, "GP995", "Pants")


def test_tracking_substring():
    row = _row("GP995-4P-BLACK", "Pants", "KYD123")
    assert row_matches(row, "", "", "kyd")
    assert not row_matches(row, "", "", "MC999")


def test_fba_substring_case_insensitive():
    row = _row("GP995-4P-BLACK", "Pants", fba="FBA19G251B4H")
    assert row_matches(row, "", "", fba_query="fba19g")
    assert row_matches(row, "", "", fba_query="19G251B4H")
    assert not row_matches(row, "", "", fba_query="FBA19G251B4Z")
