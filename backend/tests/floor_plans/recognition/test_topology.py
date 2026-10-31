from app.floor_plans.recognition.openings import Opening
from app.floor_plans.recognition.topology import (
    drop_small_groups,
    find_parent,
    split_at_junctions,
)
from app.floor_plans.recognition.walls import WallSegment


def _h(offset: float, start: float, end: float) -> WallSegment:
    return WallSegment("horizontal", offset, start, end)


def _v(offset: float, start: float, end: float) -> WallSegment:
    return WallSegment("vertical", offset, start, end)


def test_t_junction_splits_into_three() -> None:
    pieces = split_at_junctions([_h(0, 0, 100), _v(50, 0, 80)])

    assert sorted(pieces, key=lambda s: (s.orientation, s.start)) == [
        _h(0, 0, 50),
        _h(0, 50, 100),
        _v(50, 0, 80),
    ]


def test_crossing_splits_into_four() -> None:
    pieces = split_at_junctions([_h(50, 0, 100), _v(50, 0, 100)])

    assert set(pieces) == {_h(50, 0, 50), _h(50, 50, 100), _v(50, 0, 50), _v(50, 50, 100)}


def test_corner_is_not_split() -> None:
    walls = [_h(0, 0, 100), _v(0, 0, 100)]

    assert split_at_junctions(walls) == walls


def test_parent_contains_opening() -> None:
    walls = split_at_junctions([_h(0, 0, 100), _v(50, 0, 80)])

    parent = find_parent(Opening("door", _h(0, 60, 90)), walls)

    assert parent == _h(0, 50, 100)


def test_no_parent_when_junction_inside_opening() -> None:
    walls = split_at_junctions([_h(0, 0, 100), _v(50, 0, 80)])

    assert find_parent(Opening("door", _h(0, 30, 70)), walls) is None


def test_drops_small_separate_groups() -> None:
    building = [_h(0, 0, 500), _v(0, 0, 500), _h(500, 0, 500), _v(500, 0, 500)]
    plant = [_h(800, 700, 740), _v(720, 780, 820)]

    assert drop_small_groups(building + plant) == building


def test_keeps_all_large_groups() -> None:
    shop = [_h(0, 0, 500), _v(0, 0, 500)]
    annex = [_h(0, 700, 1000), _v(1000, 0, 300)]

    assert drop_small_groups(shop + annex) == shop + annex
