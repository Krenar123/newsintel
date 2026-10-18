#!/usr/bin/env python3
"""Run a live provider check for evidence-only NewsIntel generation."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.intelligence.grounded_ai import GroundedAI


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify configured AI grounding")
    parser.add_argument("--require-provider", action="store_true")
    args = parser.parse_args()

    ai = GroundedAI()
    if not ai.available:
        print(json.dumps({
            "status": "not_configured",
            "provider": ai.provider,
            "model": ai.model,
            "message": (
                "Set AI_API_KEY and ENABLE_AI_INTELLIGENCE=true, then rerun. "
                "No key was read from or written to source control."
            ),
        }, indent=2))
        return 2 if args.require_provider else 0

    evidence = [{
        "label": "S1",
        "source_name": "Grounding fixture",
        "title": "Council delays vote",
        "claim": "The council postponed the vote until Friday.",
        "content": (
            "The council postponed the vote until Friday. "
            "No contract value or final decision was reported."
        ),
    }]
    result = ai.generate_json(
        task="Explain what happened and identify what remains unknown.",
        instructions=(
            "Do not claim that a contract was approved or assign a monetary value. "
            "Use exact evidence quotes for every claim."
        ),
        evidence=evidence,
    )
    payload = {
        "status": "passed" if result.accepted else "failed",
        "metadata": result.metadata(),
        "payload": result.payload,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
