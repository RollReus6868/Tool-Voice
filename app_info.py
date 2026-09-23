"""Single source of truth for the version and the GitHub repo used by the updater.

The release workflow refuses to publish when the git tag does not match
APP_VERSION, so bump it here (only here) for every release.
"""

APP_NAME = "TTS Clone Studio"
APP_ID = "TTSCloneStudio"          # file / asset prefix, no spaces
APP_VERSION = "2.1.0"
GITHUB_REPO = "OWNER/TTS-Clone-Studio"   # "owner/repo" — repo must be Public for updates
