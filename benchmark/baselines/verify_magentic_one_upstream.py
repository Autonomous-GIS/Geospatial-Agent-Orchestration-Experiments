"""Verify the installed Magentic-One implementation comes from Microsoft AutoGen.

Does not require an OpenAI key and makes no API requests.
Run: python -m benchmark.baselines.verify_magentic_one_upstream
"""
from __future__ import annotations

import importlib.metadata as metadata
import inspect
import json

EXPECTED_COMMIT = "83afbf5857aac683340d4c692194e548b1e8edda"
from pathlib import Path


def main() -> None:
    from autogen_agentchat.teams import MagenticOneGroupChat
    from autogen_agentchat.teams._group_chat._magentic_one._magentic_one_orchestrator import (
        MagenticOneOrchestrator,
    )

    print("Upstream class:", MagenticOneGroupChat.__module__ + "." + MagenticOneGroupChat.__name__)
    print("Orchestrator class:", MagenticOneOrchestrator.__module__ + "." + MagenticOneOrchestrator.__name__)
    print("Team implementation:", inspect.getfile(MagenticOneGroupChat))
    print("Orchestrator implementation:", inspect.getfile(MagenticOneOrchestrator))
    for name in ("autogen-agentchat", "autogen-ext", "autogen-core"):
        pkg = metadata.distribution(name)
        print(f"{name} installed version: {pkg.version}")
        direct_url = pkg.read_text("direct_url.json")
        if name in {"autogen-agentchat", "autogen-ext"} and not direct_url:
            raise RuntimeError(f"{name} was not installed from GitHub as requested")
        if direct_url:
            origin = json.loads(direct_url)
            print(f"{name} install provenance:", json.dumps(origin, sort_keys=True))
            if name in {"autogen-agentchat", "autogen-ext"}:
                if "github.com/microsoft/autogen" not in origin.get("url", ""):
                    raise RuntimeError(f"{name} source URL is not Microsoft AutoGen GitHub")
                actual = origin.get("vcs_info", {}).get("commit_id")
                if actual != EXPECTED_COMMIT:
                    raise RuntimeError(f"{name} source commit {actual!r} != pinned {EXPECTED_COMMIT}")
    # This verifies the source imports, not where historical trajectories originated.
    assert "_magentic_one" in inspect.getfile(MagenticOneOrchestrator)
    assert "MagenticOneOrchestrator" in inspect.getsource(MagenticOneGroupChat)
    print("PASS: genuine upstream MagenticOneGroupChat/MagenticOneOrchestrator imported")


if __name__ == "__main__":
    main()
