# Publish as an independent repository

Create a new repository under your GitHub account. It will be independent
of the upstream repository. The repository is published at `s1mb1o/uvrcast`. Original author
credit and license notices remain in README.md, CREDITS.md, COPYING.GPL,
LICENSE, source headers and docs/PROVENANCE.json.

This directory contains a complete source snapshot, the Linux port changes,
build/conversion tools, the streaming service, Docker deployment, and documentation. Its Git history starts with a new
import commit; the original driver's history remains accessible through the
upstream source link. GitHub fork status is not required for GPL compliance.

## Create and publish

1. Open https://github.com/new, choose `s1mb1o` as owner, name the repository
   `uvrcast`, and select Public. Leave README, .gitignore and
   license initialization disabled because the local project already has them.
2. On the Ubuntu host, enter the prepared source directory. If it has not
   already been initialized, run `git init -b main`:

```sh
cd ~/blackmagic-recorder-github
git init -b main
git status --short
```

Confirm your local Git author identity uses a verified or GitHub noreply email
before committing. Keep private email addresses out of public commits if that
is your preference.

3. Review and publish the source:

```sh
git add .
git diff --cached --stat
git diff --cached --name-only
git commit -m "Import crusher264-based Linux recorder port; preserve upstream credits"
git remote add origin https://github.com/s1mb1o/uvrcast.git
git push -u origin main
```

Replace `s1mb1o` if publishing under a different account. If GitHub CLI is
installed and authenticated, it can create the new repository and push an
already committed local project instead of the browser/remote steps:

```sh
gh repo create s1mb1o/uvrcast --public --source=. --remote=origin --push
```

Use either creation workflow once. A future source-only release can point to
a tag after more hardware tests.

## Preserve attribution and license

Retain COPYING.GPL, LICENSE, CREDITS.md, original source notices and vendored
dependency licenses. GPLv2 section 2 calls for dated modification notices;
the nine modified upstream files already carry them. New port scripts/tests
are marked GPL-2.0-only. Publish the modified driver under the GPLv2 terms,
with the separately licensed dependency notices intact.

Credit tipok / piratfm for the original driver and describe this project as
an independent continuation based on crusher264. The initial import records
the imported source and does not claim original driver authorship.

Firmware, the Mac application, recordings, private research/logs, binaries and
build outputs are excluded. Publish this prepared directory; the research
workspace contains material outside the public source package.

Official references:

- https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
- https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
