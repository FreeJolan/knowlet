from knowlet.chat.sediment import _parse_json_object


def test_parse_plain_json():
    out = _parse_json_object('{"a": 1, "b": "x"}')
    assert out == {"a": 1, "b": "x"}


def test_parse_json_in_markdown_fence():
    text = '```json\n{"a": 1}\n```'
    assert _parse_json_object(text) == {"a": 1}


def test_parse_json_with_prose_around():
    text = 'Here is the note:\n{"title": "T", "tags": [], "body": "x"}\nThanks!'
    out = _parse_json_object(text)
    assert out["title"] == "T"
    assert out["body"] == "x"
