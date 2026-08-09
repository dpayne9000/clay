# Interactive seeded workflow upgrades

`clay build --upgrade` now compares the template workflows originally seeded
from Clay with the copies in `$CLAY_HOME`. New workflows are installed, changed
workflows show complete per-file unified diffs, and one confirmation controls
replacement of the whole workflow.

Accepted workflows are backed up under `$CLAY_HOME/backups` and replaced from a
staged copy. Declined workflows remain untouched. Custom and system workflows
are outside the command's scope, and ordinary `clay build` retains its existing
checkout-oriented schema and registry behavior.
