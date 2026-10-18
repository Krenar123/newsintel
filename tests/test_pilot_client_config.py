from scripts.create_pilot_client import validate_payload


def valid_payload():
    return {
        "client": {
            "name": "Pilot Organization",
            "email": "pilot@example.com",
            "client_type": "political_party",
            "plan": "pro",
        },
        "user": {
            "name": "Pilot Operator",
            "email": "operator@example.com",
        },
        "watchlist": [{
            "item_type": "entity",
            "label": "Primary party",
            "value": "Пилот Партија",
        }],
    }


def test_valid_pilot_client_config_passes():
    assert validate_payload(valid_payload()) == []


def test_template_placeholders_are_rejected():
    payload = valid_payload()
    payload["client"]["name"] = "REPLACE WITH CLIENT"

    assert "client.name still contains a template placeholder" in validate_payload(
        payload
    )
