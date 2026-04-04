"""Tests for agent utilities."""
from app.agent import convert_messages
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
import pytest


def test_convert_messages_empty():
    """Empty list returns empty result."""
    result = convert_messages([])
    assert result == []


def test_convert_messages_user_role():
    """User role converts to HumanMessage."""
    raw = [{"role": "user", "content": "Hello"}]
    result = convert_messages(raw)
    assert len(result) == 1
    assert isinstance(result[0], HumanMessage)
    assert result[0].content == "Hello"


def test_convert_messages_assistant_role():
    """Assistant role converts to AIMessage."""
    raw = [{"role": "assistant", "content": "Hi there"}]
    result = convert_messages(raw)
    assert len(result) == 1
    assert isinstance(result[0], AIMessage)
    assert result[0].content == "Hi there"


def test_convert_messages_system_role():
    """System role converts to SystemMessage."""
    raw = [{"role": "system", "content": "You are helpful"}]
    result = convert_messages(raw)
    assert len(result) == 1
    assert isinstance(result[0], SystemMessage)
    assert result[0].content == "You are helpful"


def test_convert_messages_tool_role():
    """Tool role converts to ToolMessage with tool_call_id."""
    raw = [
        {
            "role": "tool",
            "content": "Result from tool",
            "tool_call_id": "call_123",
        }
    ]
    result = convert_messages(raw)
    assert len(result) == 1
    assert isinstance(result[0], ToolMessage)
    assert result[0].content == "Result from tool"
    assert result[0].tool_call_id == "call_123"


def test_convert_messages_tool_role_missing_tool_call_id():
    """Tool role without tool_call_id uses default."""
    raw = [{"role": "tool", "content": "Result"}]
    result = convert_messages(raw)
    assert isinstance(result[0], ToolMessage)
    assert result[0].tool_call_id == "unknown"


def test_convert_messages_unknown_role():
    """Unknown role defaults to HumanMessage."""
    raw = [{"role": "unknown", "content": "Test"}]
    result = convert_messages(raw)
    assert isinstance(result[0], HumanMessage)
    assert result[0].content == "Test"


def test_convert_messages_no_role():
    """Missing role defaults to HumanMessage."""
    raw = [{"content": "Test"}]
    result = convert_messages(raw)
    assert isinstance(result[0], HumanMessage)


def test_convert_messages_no_content():
    """Missing content defaults to empty string."""
    raw = [{"role": "user"}]
    result = convert_messages(raw)
    assert isinstance(result[0], HumanMessage)
    assert result[0].content == ""


def test_convert_messages_mixed_sequence():
    """Mixed message types preserve order."""
    raw = [
        {"role": "system", "content": "Setup"},
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Answer"},
        {"role": "tool", "content": "Tool result", "tool_call_id": "t1"},
    ]
    result = convert_messages(raw)
    assert len(result) == 4
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[1], HumanMessage)
    assert isinstance(result[2], AIMessage)
    assert isinstance(result[3], ToolMessage)


def test_convert_messages_preserves_content_exactly():
    """Content is preserved exactly (no sanitization)."""
    content = "Special chars: @#$%^&*()"
    raw = [{"role": "user", "content": content}]
    result = convert_messages(raw)
    assert result[0].content == content


def test_convert_messages_multiline_content():
    """Multiline content is preserved."""
    content = "Line 1\nLine 2\nLine 3"
    raw = [{"role": "user", "content": content}]
    result = convert_messages(raw)
    assert result[0].content == content


def test_convert_messages_large_list():
    """Large list of messages is converted correctly."""
    raw = [
        {"role": "user", "content": f"Message {i}"}
        for i in range(100)
    ]
    result = convert_messages(raw)
    assert len(result) == 100
    for i, msg in enumerate(result):
        assert isinstance(msg, HumanMessage)
        assert msg.content == f"Message {i}"


def test_convert_messages_background_role():
    """role='background' must become HumanMessage with [Background Update] prefix."""
    from app.agent import convert_messages
    from langchain_core.messages import HumanMessage

    msgs = [{"role": "background", "content": "Some background info"}]
    result = convert_messages(msgs)
    assert len(result) == 1
    assert isinstance(result[0], HumanMessage)
    assert result[0].content.startswith("[Background Update]")
    assert "Some background info" in result[0].content
