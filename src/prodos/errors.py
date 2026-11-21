class ProDOSError(Exception):
    """
    A user-facing error: bad input, a missing or existing file, a full volume,
    or a malformed disk image.  Internal invariants still use assert.
    """
