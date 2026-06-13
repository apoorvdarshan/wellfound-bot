"""Offline integration test for run.py's control flow — no Wellfound, no
login. It serves local HTML for wellfound.com URLs via request
interception, then drives the real functions from run.py to prove:

  * collect_job_links keeps scrolling until it has enough cards
    (infinite-scroll feed) and filters out non-job "/jobs/" chrome,
  * ensure_logged_in treats a feed with no password field as logged in,
  * apply_to_job detects the apply MODAL, finds the message box and a
    submit control distinct from the Apply button, and stops on DRY_RUN.

Run:  .venv/bin/python flow_test.py
"""
import re
import sys

from playwright.sync_api import sync_playwright

import config
import run as R
from wellfound.browser import launch_context
from wellfound.capture import FlowRecorder

RESULTS = []


def check(name, ok, info=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({info})" if info else ""))


# Feed starts with 3 job cards + nav chrome; scrolling appends 3 more,
# so collecting 5 forces collect_job_links to scroll at least once.
FEED = """<!doctype html><html><body>
<h1>Jobs feed</h1>
<a href="/about">nav</a>
<a href="/jobs/">browse all</a>
<div id="list">
  <a href="/jobs/101-alpha">Alpha</a>
  <a href="/jobs/102-beta">Beta</a>
  <a href="/jobs/103-gamma">Gamma</a>
</div>
<div style="height:1500px"></div>
<script>
let added = false;
addEventListener('scroll', () => {
  if (added) return; added = true;
  const l = document.getElementById('list');
  [104, 105, 106].forEach(n => {
    const a = document.createElement('a');
    a.href = '/jobs/' + n + '-extra'; a.textContent = 'X' + n; l.appendChild(a);
  });
});
</script>
</body></html>"""

# Job page: Apply button reveals a role=dialog modal with a message box
# and a "Send application" submit — i.e. the real Wellfound shape.
JOB = """<!doctype html><html><body>
<h1>Job</h1>
<button id="apply">Apply</button>
<div id="modal" role="dialog" style="display:none">
  <textarea name="message"></textarea>
  <button type="submit">Send application</button>
</div>
<script>
document.getElementById('apply').onclick = () => {
  document.getElementById('modal').style.display = 'block';
};
</script>
</body></html>"""

JOBID = re.compile(r"/jobs/\d")


def handler(route):
    url = route.request.url
    if JOBID.search(url):
        body = JOB
    elif url.rstrip("/").endswith("/jobs"):
        body = FEED
    else:
        body = "<!doctype html><html><body>ok</body></html>"
    route.fulfill(status=200, content_type="text/html", body=body)


def main():
    config.DRY_RUN = True
    with sync_playwright() as p:
        ctx = launch_context(p, headless=True)
        ctx.route("**/*", handler)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        rec = FlowRecorder(run_name="flowtest")

        print("\nensure_logged_in:")
        check("returns True when no password field present", R.ensure_logged_in(page, rec))

        print("\ncollect_job_links (infinite scroll + chrome filtering):")
        links = R.collect_job_links(page, 5)
        check("collected exactly 5 links", len(links) == 5, str(links))
        check("every link is a real job id (chrome filtered out)",
              all(JOBID.search(l) for l in links))
        check("the '/jobs/' browse-all chrome link was excluded", "/jobs/" not in links)

        print("\napply_to_job (modal scope + submit-identity guard + dry-run):")
        res = R.apply_to_job(page, rec, links[0])
        check("dry-run returned True (modal, message box, distinct submit found)", res is True)

        log = (rec.dir / "flow.jsonl").read_text()
        check("recorded apply_modal_opened", "apply_modal_opened" in log)
        check("recorded message_box_found", "message_box_found" in log)
        check("recorded dry_run_stop_before_submit", "dry_run_stop_before_submit" in log)
        check("did NOT record a false 'submitted'", "\"submitted\"" not in log)

        ctx.close()

    passed, total = sum(RESULTS), len(RESULTS)
    print(f"\n{passed}/{total} flow checks passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
