"""Errors raised while building a forwarder."""


class BuildError(RuntimeError):
    """A forwarder could not be built; the message is meant for the user."""
