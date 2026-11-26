
import pytest

from app.core.errors import ValidationFailed


def test_set_ranker_to_ml_persists(container):
    result = container.config.set_ranker("ml")

    assert result == "ml"
    assert container.config.get("ranker") == "ml"


def test_set_ranker_to_rule_based_persists(container):
    container.config.set_ranker("ml")

    result = container.config.set_ranker("rule_based")

    assert result == "rule_based"
    assert container.config.get("ranker") == "rule_based"


def test_set_ranker_rejects_invalid_value(container):
    with pytest.raises(ValidationFailed):
        container.config.set_ranker("unknown")

    assert container.config.get("ranker") == "rule_based"
