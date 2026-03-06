from momentum_companion.llm.service import _normalize_llm_response


def test_normalize_parsed_dict_passthrough():
    resp = {"stock_bias": "HAS_POTENTIAL", "summary": "ok", "setups": []}
    out = _normalize_llm_response(resp)
    assert out is resp


def test_normalize_chat_envelope_content():
    envelope = {
        "id": "x",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"stock_bias":"HAS_POTENTIAL","summary":"ok","setups":[]}'
                }
            }
        ],
    }
    out = _normalize_llm_response(envelope)
    assert out.get("stock_bias") == "HAS_POTENTIAL"
    assert out.get("setups") == []


def test_normalize_code_fence_json():
    envelope = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "```json\n{\"stock_bias\":\"NO_EDGE\",\"summary\":\"none\",\"setups\":[]}\n```"
                }
            }
        ]
    }
    out = _normalize_llm_response(envelope)
    assert out.get("setups") == []
    assert out.get("stock_bias") == "NO_EDGE"


def test_normalize_malformed_returns_no_edge():
    envelope = {"choices": [{"message": {"content": "not json"}}]}
    out = _normalize_llm_response(envelope)
    assert out.get("stock_bias") == "NO_EDGE"
    assert out.get("setups") == []
