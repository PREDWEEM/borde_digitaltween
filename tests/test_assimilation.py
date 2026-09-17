import numpy as np
import pandas as pd

from predweem_twin.assimilation import assimilate_observations, kalman_gain


def sample_trajectory():
    dates = pd.date_range("2026-03-01", periods=10)
    accumulated = np.linspace(0, 1, 10)
    return pd.DataFrame({"Fecha": dates, "EMERAC_NORMALIZADA": accumulated})


def test_kalman_gain_responds_to_uncertainty():
    assert kalman_gain(0.12, 0.03) > kalman_gain(0.12, 0.20)


def test_assimilation_is_bounded_monotonic_and_audited():
    observations = pd.DataFrame(
        {"Fecha": ["2026-03-05"], "Observado": [0.30], "Incertidumbre": [0.05]}
    )
    adjusted, audit = assimilate_observations(sample_trajectory(), observations)
    assert adjusted["EMERAC_TWIN"].between(0, 1).all()
    assert (adjusted["EMERAC_TWIN"].diff().fillna(0) >= -1e-12).all()
    assert len(audit) == 1
    assert audit.iloc[0]["Estado_posterior"] < audit.iloc[0]["Pronostico_previo"]
    assert np.isclose(adjusted.iloc[-1]["EMERAC_TWIN"], 1.0)

