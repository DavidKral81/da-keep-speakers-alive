"""Facts about the project that more than one program needs.

The app (keep_alive.py) imports from here, and the installer build script will
read VERSION out of this one line as well - so the version shown in the
window, in the file properties and in "Installed apps" can never disagree.

To release a new version change it HERE ONLY.
"""

VERSION = "1.2"

# Where the releases live.
PROJECT_URL = "https://github.com/DavidKral81/da-keep-speakers-alive"
