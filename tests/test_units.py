import numpy as np
import pandas as pd
import pytest

from energy_pipeline.clean import apply_bounds, assert_plausible_scale, flag_outliers


def test_values_outside_bounds_become_nan_and_flagged():
    df = pd.DataFrame({"price_eur_mwh": [40.0, -900.0, 3500.0, -50.0]})
    out, counts = apply_bounds(df)
    assert counts["price_eur_mwh"] == 2
    assert out.price_eur_mwh_unit_error.tolist() == [False, True, True, False]
    assert np.isnan(out.price_eur_mwh.iloc[1])
    assert out.price_eur_mwh.iloc[3] == -50.0   # negative prices are real, keep them


def test_load_in_gw_is_rejected():
    df = pd.DataFrame({"load_mw": [55.2, 60.1, 58.3], "price_eur_mwh": [40.0, 42.0, 39.0]})
    with pytest.raises(ValueError, match="GW"):
        assert_plausible_scale(df)


def test_spike_is_flagged_not_removed():
    values = np.full(200, 40.0) + np.sin(np.arange(200))
    values[100] = 400.0
    out = flag_outliers(pd.DataFrame({"p": values}), ["p"], window=48, z=6)
    assert out.p_outlier.sum() == 1 and out.p_outlier.iloc[100]
    assert out.p.iloc[100] == 400.0
