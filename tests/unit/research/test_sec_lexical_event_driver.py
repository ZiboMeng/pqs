import pandas as pd

from dev.scripts.mining_v4.run_sec_lexical_event_mining import (
    _shuffle_feature_bundles,
)


def test_shuffled_negative_control_preserves_same_document_bundle():
    date = pd.Timestamp("2024-01-02")
    columns = ["A", "B", "C"]
    features = {
        "tone": pd.DataFrame([[1.0, 2.0, 3.0]], index=[date], columns=columns),
        "length": pd.DataFrame(
            [[10.0, 20.0, 30.0]], index=[date], columns=columns),
    }
    eligibility = pd.DataFrame(True, index=[date], columns=columns)
    shuffled = _shuffle_feature_bundles(features, eligibility, seed=42)
    assert sorted(shuffled["tone"].loc[date]) == [1.0, 2.0, 3.0]
    assert (
        shuffled["length"].loc[date].to_numpy()
        == shuffled["tone"].loc[date].to_numpy() * 10
    ).all()
