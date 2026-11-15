"""Verb dispatch (DESIGN.md S8): python -m pipeline <verb>.

S8 contract: `python -m pipeline {convert,index,summary,kb,verify}`.
`convert` is the orchestrator ENGINE (ticket agp, Q5 scope); `doctor`/`status` are live;
the remaining verbs are explicit pending stubs with their owning tickets (mirrors
rag/__main__.py, spec review a1).
"""
import sys

_PENDING = {
    "index": "pending ticket school-prep-agent-plq (DESIGN.md S6.1)",
    "summary": "pending ticket school-prep-agent-bso (DESIGN.md S6.2)",
    "kb": "pending ticket school-prep-agent-t6u (DESIGN.md S6.3)",
    "verify": "pending ticket school-prep-agent-hur (DESIGN.md S6.4)",
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"doctor", "status", "convert", *_PENDING}:
        print("usage: python -m pipeline <doctor|status|convert|index|summary|kb|verify>")
        return 2
    if argv[0] == "doctor":
        from .doctor import cli

        return cli(["doctor"])
    if argv[0] == "status":
        from .status import run

        return run(argv[1:])
    if argv[0] == "convert":
        from .convert import run

        return run(argv[1:])
    print(f"pipeline {argv[0]}: not implemented yet — {_PENDING[argv[0]]}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
