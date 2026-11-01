def collision(role, host, mode, history, actual_code):
    """The published Apple cold smoke was a successful single-rmeta build."""
    if role == "corrected" or mode == "off":
        return False
    if role == "published-22" and host == "aarch64-apple-darwin":
        if history == "cold-doc":
            return False
        if history != "build-doc" or actual_code not in (0, 101):
            raise ValueError("unrecognized published Apple diamond verdict")
        # The full checker also verifies the native nominal value, true leaf
        # shapes and exactly the registered collision or successful HTML.
        return actual_code == 101
    return True
