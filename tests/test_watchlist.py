"""Tests for load_watchlist: comments, dedup, case normalization."""
from main import load_watchlist


def test_basic(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("AAPL\nMSFT\nGOOG\n")
    assert load_watchlist(p) == ["AAPL", "MSFT", "GOOG"]


def test_strips_comments(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("AAPL # apple\nMSFT  # microsoft\n# pure comment line\nGOOG\n")
    assert load_watchlist(p) == ["AAPL", "MSFT", "GOOG"]


def test_uppercases(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("aapl\nMsFt\n")
    assert load_watchlist(p) == ["AAPL", "MSFT"]


def test_dedups_preserving_order(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("AAPL\nMSFT\naapl\nGOOG\nMSFT\n")
    assert load_watchlist(p) == ["AAPL", "MSFT", "GOOG"]


def test_skips_blank_lines(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("AAPL\n\n   \nMSFT\n")
    assert load_watchlist(p) == ["AAPL", "MSFT"]


def test_empty_file(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("")
    assert load_watchlist(p) == []


def test_only_comments(tmp_path):
    p = tmp_path / "wl.txt"
    p.write_text("# just\n# comments\n")
    assert load_watchlist(p) == []
