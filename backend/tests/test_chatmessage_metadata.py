from app.models import ChatMessage
import uuid


def test_chatmessage_has_metadata_column():
    """ChatMessage must have a metadata DB column (JSON nullable).
    SQLAlchemy reserves the Python attribute name 'metadata' on declarative
    models, so the Python attribute is named msg_metadata and maps to the
    'metadata' column in the database.
    """
    msg = ChatMessage(
        conversation_id=uuid.uuid4(),
        role="background",
        content="test",
        msg_metadata={"variant": "info"},
    )
    assert msg.msg_metadata == {"variant": "info"}
    # Verify the DB column is actually named 'metadata'
    assert "metadata" in msg.__table__.columns
