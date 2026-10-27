"""For versioning the FastAPI app."""

import os

version = "0.7.1"

# The release image sets this from a build arg; a source checkout leaves it unset.
git_sha = os.environ.get("R9CAM_GIT_SHA") or None
