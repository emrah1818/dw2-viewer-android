"""Create-only publication of a finished temporary file.

Hard links give an atomic "never overwrite" on normal Linux/Windows file
systems, but Android's SELinux policy forbids apps from creating hard links
in their private storage (os.link -> EACCES/EPERM). There we fall back to a
rename after re-checking that the target is still free. The export folders
are private to the app, so nothing else can race to create the same name.
"""
import errno
import os
from pathlib import Path

_NO_LINK = {errno.EACCES, errno.EPERM, errno.EXDEV, errno.ENOTSUP,
            getattr(errno, 'EOPNOTSUPP', errno.ENOTSUP), errno.EMLINK}


def publish_new(temporary, destination):
    """Move *temporary* to *destination*; raise FileExistsError if it exists."""
    temporary, destination = Path(temporary), Path(destination)
    if os.name == 'nt':
        os.rename(temporary, destination)  # Windows rename refuses existing targets
        return destination
    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise
    except OSError as error:
        if error.errno not in _NO_LINK:
            raise
        if destination.exists():
            raise FileExistsError(errno.EEXIST, 'Zieldatei existiert bereits.', str(destination))
        os.rename(temporary, destination)
        return destination
    temporary.unlink(missing_ok=True)
    return destination
