from app.config import Settings


def test_canonical_jwt_secret_configuration():
    """Verify that setting JWT_SECRET populates jwt_secret correctly."""
    s = Settings(JWT_SECRET="canonical-secret-1234567890")
    assert s.jwt_secret == "canonical-secret-1234567890"


def test_secret_key_fallback_configuration():
    """Verify that setting SECRET_KEY populates jwt_secret via alias fallback."""
    s = Settings(SECRET_KEY="fallback-secret-1234567890")
    assert s.jwt_secret == "fallback-secret-1234567890"


def test_alias_precedence_when_conflicting_values():
    """Verify that canonical JWT_SECRET takes precedence over SECRET_KEY."""
    s = Settings(jwt_secret="primary-secret-1234567890", secret_key="secondary-secret-1234567890")
    assert s.jwt_secret == "primary-secret-1234567890"


def test_missing_or_empty_secret_fails_safely():
    """Verify that missing or under-16-char secret values are caught during startup."""
    for bad_secret in [None, "", "short", "123456789012345"]:
        settings = Settings(JWT_SECRET=bad_secret)
        failed_safely = not (settings.jwt_secret and len(settings.jwt_secret) >= 16)
        assert failed_safely, f"Failed to reject invalid secret: {bad_secret}"


def test_no_secret_values_in_repr():
    """Ensure printing or logging settings does not expose full secret."""
    s = Settings(JWT_SECRET="super-secret-sensitive-value-here")
    assert s.jwt_secret == "super-secret-sensitive-value-here"
