from multistream_revenue_tracker.ui.routes import user_facing_error_message


def test_user_facing_error_message_strips_windows_path():
    exc = FileNotFoundError(r"Missing C:\Users\secret\config.json")
    msg = user_facing_error_message(exc)
    assert "C:\\Users" not in msg
    assert "[path]" in msg


def test_user_facing_error_message_strips_token():
    # sk_*-shaped placeholder only — avoid Stripe-like sk_live_* strings (GitHub push protection).
    exc = RuntimeError("auth failed sk_prodabcdefghijklmnop")
    msg = user_facing_error_message(exc)
    assert "sk_prod" not in msg
    assert "[token]" in msg
