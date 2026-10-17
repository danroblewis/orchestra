"""Test session settings."""

import os

# examples' live feeds play their default-length recordings in tests (fast, and what the tests
# that check where a recording ends expect); a real server plays the long ones
os.environ.setdefault("SDLAB_LIVE_STEPS", "default")
