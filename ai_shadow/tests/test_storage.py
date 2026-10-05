import pytest

from ai_shadow.storage import ShadowStorage


def test_genesis_cannot_overwrite(tmp_path):
    store = ShadowStorage(tmp_path)
    store.create_genesis({"experiment_id": "one", "nav": 20000})
    with pytest.raises(ValueError, match="GENESIS_ALREADY_EXISTS"):
        store.create_genesis({"experiment_id": "one", "nav": 999})
    assert store.genesis()["nav"] == 20000


def test_duplicate_decision_id_no_trade(tmp_path):
    store = ShadowStorage(tmp_path)
    store.create_genesis({"experiment_id": "one", "nav": 20000})
    record = {"decision_id": "first", "day": "2026-10-05", "orders": [{"asset": "BTC"}]}
    assert store.commit_cycle(record) is True
    assert store.commit_cycle(record) is False
    assert len(store.cycles()) == 1
    assert store.verify_chain()
