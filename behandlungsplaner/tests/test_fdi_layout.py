from behandlungsplaner import fdi


def test_default_calibration_layout_has_all_32_teeth_within_bounds():
    layout = fdi.default_calibration_layout()
    assert set(layout.keys()) == set(fdi.ALL_FDI_TEETH)
    for tooth, (x, y) in layout.items():
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


def test_default_calibration_layout_upper_and_lower_dont_overlap():
    layout = fdi.default_calibration_layout()
    max_upper_y = max(layout[t][1] for t in fdi.UPPER_ROW_LEFT_TO_RIGHT)
    min_lower_y = min(layout[t][1] for t in fdi.LOWER_ROW_LEFT_TO_RIGHT)
    assert max_upper_y < min_lower_y


def test_row_neighbors():
    assert fdi.row_neighbors(18) == (None, 17)
    assert fdi.row_neighbors(28) == (27, None)
    assert fdi.row_neighbors(11) == (12, 21)
    assert fdi.row_neighbors(41) == (42, 31)


def test_teeth_between_same_row():
    # Q1 (14/15/16) steht im Bild von links nach rechts absteigend (16 15 14),
    # da FDI in Q1 rechts->links im Bild kleiner wird. teeth_between liefert
    # die Bild-Reihenfolge links->rechts, unabhaengig von der Klickrichtung.
    assert fdi.teeth_between(14, 16) == [16, 15, 14]
    assert fdi.teeth_between(16, 14) == [16, 15, 14]
    assert fdi.teeth_between(24, 26) == [24, 25, 26]


def test_teeth_between_different_rows_falls_back_to_pair():
    assert fdi.teeth_between(14, 34) == [14, 34]
