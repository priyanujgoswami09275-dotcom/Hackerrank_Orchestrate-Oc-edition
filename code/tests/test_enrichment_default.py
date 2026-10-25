from __future__ import annotations

import pytest
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pramaantrace.loader import enrich_enabled


def test_enrichment_is_enabled_when_environment_variable_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRAMAANTRACE_ENRICH", raising=False)

    assert enrich_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_explicit_false_like_values_disable_enrichment(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PRAMAANTRACE_ENRICH", value)

    assert enrich_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_explicit_true_like_values_enable_enrichment(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PRAMAANTRACE_ENRICH", value)

    assert enrich_enabled() is True
