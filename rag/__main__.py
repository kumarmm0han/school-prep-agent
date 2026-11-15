"""Verb dispatch (DESIGN.md S7.5): python -m rag <verb> — skeletons until their tickets."""
import sys

_SKEL = {
    "ingest": "pending ticket school-prep-agent-6vy (DESIGN.md S7.2)",
    "retrieve": "pending ticket school-prep-agent-uoy (DESIGN.md S7.3)",
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _SKEL:
        print("usage: python -m rag <ingest|retrieve>")
        return 2
    print(f"rag {argv[0]}: not implemented yet — {_SKEL[argv[0]]}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
