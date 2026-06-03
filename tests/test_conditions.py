from app.rules.conditions import evaluate


def test_empty_condition_is_true():
    assert evaluate(None, {}) is True
    assert evaluate({}, {"a": 1}) is True


def test_leaf_comparisons():
    payload = {"node_id": 7, "used_percent": 95}
    assert evaluate({"field": "node_id", "op": "eq", "value": 7}, payload) is True
    assert evaluate({"field": "node_id", "op": "ne", "value": 1}, payload) is True
    assert evaluate({"field": "used_percent", "op": "ge", "value": 90}, payload) is True
    assert evaluate({"field": "used_percent", "op": "lt", "value": 90}, payload) is False


def test_dotted_path():
    payload = {"user": {"status": "limited"}}
    assert evaluate({"field": "user.status", "op": "eq", "value": "limited"}, payload) is True


def test_logical_operators():
    payload = {"a": 5, "b": 10}
    assert evaluate({"all": [
        {"field": "a", "op": "eq", "value": 5},
        {"field": "b", "op": "gt", "value": 1},
    ]}, payload) is True
    assert evaluate({"any": [
        {"field": "a", "op": "eq", "value": 0},
        {"field": "b", "op": "eq", "value": 10},
    ]}, payload) is True
    assert evaluate({"not": {"field": "a", "op": "eq", "value": 5}}, payload) is False


def test_unknown_op_is_false():
    assert evaluate({"field": "a", "op": "bogus", "value": 1}, {"a": 1}) is False
