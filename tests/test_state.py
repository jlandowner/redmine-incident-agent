from redmine_incident_agent.state import (
    extract_tags,
    latest_external_journal_id,
    parse_watermark,
    should_process,
)


def test_extract_tags_strings_and_dicts():
    assert extract_tags({"tags": ["foo", {"name": "bar"}]}) == ["foo", "bar"]
    assert extract_tags({"tag_list": "foo,bar"}) == ["foo", "bar"]


def test_parse_watermark_uses_highest_valid_value():
    tags = ["agent:watermark=10", "x", "agent:watermark=abc", "agent:watermark=12"]
    assert parse_watermark(tags, "agent:watermark=") == 12


def test_latest_external_journal_ignores_agent():
    journals = [
        {"id": 10, "user": {"id": 1}},
        {"id": 11, "user": {"id": 99}},
        {"id": 12, "user": {"id": 1}},
    ]
    assert latest_external_journal_id(journals, agent_user_id=99) == 12


def test_should_process():
    assert should_process(normalized=False, stored_watermark=10, input_watermark=10)
    assert should_process(normalized=True, stored_watermark=None, input_watermark=0)
    assert should_process(normalized=True, stored_watermark=10, input_watermark=11)
    assert not should_process(normalized=True, stored_watermark=10, input_watermark=10)
