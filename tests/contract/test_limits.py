from __future__ import annotations

from app.api.limits import SlidingWindow


def test_requests_inside_the_limit_are_allowed():
    window = SlidingWindow(limit=3, window=60)

    assert [window.allows("a", moment=0) for _ in range(3)] == [True, True, True]


def test_the_limit_refuses_the_next_request():
    window = SlidingWindow(limit=2, window=60)
    window.allows("a", moment=0)
    window.allows("a", moment=1)

    assert not window.allows("a", moment=2)


def test_the_window_slides():
    window = SlidingWindow(limit=1, window=10)
    window.allows("a", moment=0)

    assert not window.allows("a", moment=5)
    assert window.allows("a", moment=11)


def test_clients_are_counted_separately():
    window = SlidingWindow(limit=1, window=60)
    window.allows("a", moment=0)

    assert window.allows("b", moment=0)
