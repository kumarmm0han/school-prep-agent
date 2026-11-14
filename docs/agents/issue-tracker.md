# Issue tracker: Beads (bd)

Issues and specs for this repo live in beads (`bd`) — dependency-aware issues
stored in a local Dolt database (`.beads/`) and synced to the git remote under
`refs/dolt/data` via `bd dolt push`. Use the `bd` CLI for all operations;
`.beads/issues.jsonl` is a passive export, not the source of truth.

## Conventions

- **Create an issue**: `bd create "Title" --description="detailed context" -t <type> -p <priority>`.
  Types: `bug|feature|task|epic|chore|decision|spike|story|milestone`.
  Priorities: `0` critical … `4` backlog.
  Quality: add `--acceptance "..."` and `--design "..."` where useful.
- **Read an issue**: `bd show <id>`
- **List issues**: `bd list --status=open`; ready (unblocked, unclaimed) work: `bd ready --json`
- **Blocking**: first-class dependencies. `bd dep add <issue> <blocker>` makes `<issue>`
  depend on (be blocked by) `<blocker>`. An issue is ready when all its blockers are
  closed — `bd ready` shows that frontier.
- **Hierarchical children**: `bd create "..." --parent <id>` for epic/map → ticket
  structure; link work discovered from a parent with `--deps discovered-from:<id>`.
- **Labels**: `bd create ... -l "label1,label2"`; `bd update <id> --add-label "..."`.
- **Claim**: `bd update <id> --claim` before working (owner + `in_progress`, atomic).
  Release a stuck claim: `bd unclaim <id>`.
- **Comments / notes**: `bd update <id> --append-notes "..."`.
- **Close**: `bd close <id> --reason "completed: what shipped"`.

## When a skill says "publish to the issue tracker"

Create a beads issue: `bd create ...` with the tightest fitting type and priority;
attach `--parent <id>` or `--deps discovered-from:<id>` when an originating work
item exists; report the issue ID back.

## When a skill says "fetch the relevant ticket"

`bd show <id>`. When only a title or slug is known, look it up in
`bd list --status=all --json` and pick the matching title.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with child issues as tickets.

- **Map**: an epic issue holding the Notes / Decisions-so-far / Fog body.
  `bd create "Map title" -t epic --description="..."`.
- **Child ticket**: hierarchical under the map — `bd create "..." -t <type> --parent <map>`;
  blockers are explicit: `bd dep add <ticket> <blocker>`.
- **Frontier**: the map's open children that `bd ready --json` reports — unblocked and
  unclaimed; first in the list wins.
- **Claim**: `bd update <ticket> --claim` — the session's first write.
- **Resolve**: `bd update <ticket> --append-notes "<answer>"`, then
  `bd close <ticket> --reason "resolved"`, and append a context pointer (gist + link)
  to the map with `bd update <map> --append-notes "..."`.

## Sync

`bd dolt pull` before work; `bd dolt push` after writes — only when the session
policy authorizes a push. Never treat `.beads/issues.jsonl` as the sync protocol.
