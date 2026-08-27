from datetime import datetime, timezone

from ai_investing.learning.nn_v2 import align_on_common_dates, purged_walk_forward_splits
from ai_investing.models import Bar


def _bar(day):
    return Bar(datetime(2026, 1, day, tzinfo=timezone.utc), 1, 1, 1, 1, 1)


def test_align_on_common_dates_never_pairs_by_position():
    aligned, dates = align_on_common_dates({"a": [_bar(1), _bar(2)], "b": [_bar(2), _bar(3)]})
    assert dates == [datetime(2026, 1, 2, tzinfo=timezone.utc).date()]
    assert len(aligned["a"]) == len(aligned["b"]) == 1


def test_purged_splits_reserve_an_untouched_final_block():
    splits, final_test = purged_walk_forward_splits(list(range(160)), horizon=5)
    assert splits
    assert min(final_test) > max(validation[-1] for _, validation in splits)
    for train, validation in splits:
        assert validation[0] - train[-1] > 5
