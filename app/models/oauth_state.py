from sqlalchemy import Column, Float, String, Text

from app.config.database import Base


class OAuthState(Base):
    """Single-use OAuth nonces (see app/utils/oauth_state.py). In the DB
    rather than process memory so a flow that starts on one Cloud Run
    instance can finish on another, or after a scale-to-zero restart."""
    __tablename__ = "oauth_states"

    # sha256 of the nonce, never the nonce itself — a DB read alone can't be
    # replayed as a valid state / exchange code.
    nonce_hash = Column(String(64), primary_key=True)
    # Fernet-encrypted JSON: one payload kind is a live access token.
    payload = Column(Text, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)  # unix epoch seconds
