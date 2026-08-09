# 2026-08-08 public repo publish tooling

Added `scripts/git_release/`, a standalone tool (separate from
`scripts/build` and `scripts/deploy`) for rebuilding a separate local clone
of the public `dpayne9000/clay` repo from an explicit allowlist of this
repo's tracked files.

The allowlist (`INCLUDE_FILES`/`INCLUDE_PREFIXES` in
[scripts/git_release/publish.py](../../scripts/git_release/publish.py))
replaced an initial denylist draft: a denylist fails open — any newly
tracked private path would leak on the next publish unless someone
remembered to exclude it. The allowlist fails closed instead. Confirmed
public surface: root project/config files, `docs/` install/example/action
reference docs and `docs/release-notes/`, and the whole `clay/` tree except
`clay/data/workflows/dev/`. Confirmed private: `docs/SIGNING.md`,
`docs/RELEASE.md`, `docs/documentation/`, `docs/tasks/`, `docs/plans/`,
`docs/planning/`, `docs/scratch_docs/`, `docs/bugs/`, `scripts/build/`,
`scripts/deploy/`, `scripts/git_release/` itself, and `web/`.

`connectors/gopher` is a git submodule, not a plain tracked file — copying
bytes can't replicate it. `publish.py` reads the submodule's URL from
`.gitmodules` and its pinned commit from this repo's index, and in
`publish` runs `git submodule add`/`fetch`/`checkout` against the pinned
commit inside the public clone only. This is the one place the tool makes a
network call or touches git state beyond plain file writes; it still never
commits or pushes either repo.

Also fixed during review: the original file-copy path
(`dest.write_bytes(...)`) dropped the executable bit on mode-`100755`
tracked files (`clay.py`); switched to `shutil.copy2()` and added an
exec-bit comparison to the `plan` diff, not just content hash.

`plan`/`publish` still never run `git commit`, `git push`, `git clone`, or
`git remote add` against either repo's own history — review and push stay
manual, in the public clone.

`INCLUDE_PREFIXES` now names every `clay/` subdirectory explicitly
(`clay/actions/`, `clay/adapters/`, `clay/auth/`, `clay/channels/`,
`clay/daemon/`, `clay/data/configs/`, `clay/data/skills/`,
`clay/data/workflows/`, `clay/lib/`, `clay/run/`, `clay/tests/`,
`clay/ui/`, `clay/vendor/`) instead of a bare `clay/` prefix, plus the five
top-level files directly under `clay/`.

`clay/data/skills/`'s contents are now excluded from every publish
(`EXCLUDE_PREFIXES`) — this is where the directive-shaped filename flagged
earlier lives, alongside network-recon and person-tracking-shaped scripts
(`celeb-tracker/`, `network-connection-probe/`, `network-explorer/`); none
of it belongs in a public mirror regardless of what it turns out to be. The
directory itself stays present but empty via
[clay/data/skills/README.md](../../clay/data/skills/README.md), listed as
an exact `INCLUDE_FILES` entry that wins over the `EXCLUDE_PREFIXES` match
(`_included()` checks exact matches first). That placeholder is not yet
`git add`ed in this repo — needed before the next `plan` run picks it up.
Whether `clay/data/skills/` belongs in the *private* repo at all is a
separate, still-open question.

See
[docs/tasks/public-repo-publish-tooling.md](../tasks/public-repo-publish-tooling.md)
for the full design.
