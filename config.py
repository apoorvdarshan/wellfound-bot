"""Tune these to your search. run.py reads them at startup."""

# Where to start browsing jobs. Best practice: apply your filters on the
# Wellfound site, then copy the resulting URL here so the run starts
# already narrowed to roles you care about.
JOBS_URL = "https://wellfound.com/jobs"

# Stop after this many jobs in one run. Keep it modest — blasting through
# hundreds of applications in minutes is the single fastest way to get
# flagged. Small batches, run a few times a day, looks human.
MAX_JOBS_PER_RUN = 5

# DRY_RUN=True walks the entire flow and captures every step, but does
# NOT click the final submit. Leave it True until the captures look
# right, then flip to False to actually apply.
DRY_RUN = True

# Headless browsers are easier to fingerprint, so the default is a real
# visible window. You can only flip this to True AFTER `login.py` has
# saved your session (you can't log in by hand to an invisible window).
HEADLESS = False

# Seconds to wait between jobs, picked randomly inside this range.
DELAY_BETWEEN_JOBS = (25, 70)

# Optional default text for the application message box. Left empty by
# default, and only ever typed when DRY_RUN is False.
DEFAULT_MESSAGE = ""
