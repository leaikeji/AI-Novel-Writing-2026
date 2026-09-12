"""S001 diagnostic only: public APIs in uniquely owned disposable containers.

Reuse the existing isolation/cleanup runner. Never address the long-lived host,
load its configuration, invoke a model, or patch QwenPaw code.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.tts import verify_qwenpaw_plugin_lifecycle as lifecycle

AGENT = "ai-novel-writer"


class SkillDiagnostic(lifecycle.LifecycleGate):
    def snapshot(self, label):
        rows = self._get_list("/api/skills", headers={"X-Agent-Id": AGENT}, step=label)
        state = {row["name"]: row["enabled"] for row in rows
                 if row.get("source") == f"plugin:{lifecycle.APP_ID}"}
        self.evidence.checks[f"S001:{label}"] = state
        print(json.dumps({"step": label, "skills": state}), flush=True)
        return state

    def enable_mixed_state(self, label):
        # Keep one explicitly disabled choice to test more than an all-on case.
        names = sorted(self.config.candidate_skill_ids - {"suspense-writing"})
        self._http_json("POST", "/api/skills/batch-enable", body=names,
                        headers={"X-Agent-Id": AGENT}, expected_statuses=(200,), step=label)
        state = self.snapshot(label + "-readback")
        if state != {name: name in names for name in self.config.candidate_skill_ids}:
            raise lifecycle.GateError("S001_FIXTURE_ENABLE_FAILED")

    def _install(self, *, force, step):
        super()._install(force=force, step=step)
        if step == "initial-install":
            self._http_json("POST", "/api/agents", body={
                "id": AGENT, "name": "S001 isolated diagnostic", "language": "zh",
                "description": "Temporary lifecycle diagnosis; no model calls", "skill_names": [],
            }, expected_statuses=(200, 201), step="S001-create-isolated-agent")
            self.snapshot("initial-disabled")
            self.enable_mixed_state("before-force-reinstall")
        elif step == "force-reinstall":
            self.snapshot("after-force-reinstall")
            self.enable_mixed_state("before-restart")
            self._run_command(["docker", "restart", self.names.qwenpaw_container],
                              step="S001-restart-isolated-host", timeout=60)
            self._wait_for_services()
            self.snapshot("after-restart")
        elif step == "reinstall":
            self.snapshot("after-uninstall-reinstall")


if __name__ == "__main__":
    args = lifecycle._build_parser().parse_args()
    config, digest = lifecycle._validated_config(args)
    names = lifecycle.create_resource_names(config.run_id)
    if config.mode == "dry-run":
        print(json.dumps(lifecycle.build_dry_run_plan(config, names), indent=2))
    else:
        gate = SkillDiagnostic(config, names)
        gate.evidence.checks["candidate-tree-sha256"] = digest
        result = gate.run()
        print(json.dumps({"status": result["status"], "cleanup": result["cleanup"],
                          "S001": {k: v for k, v in result["checks"].items() if k.startswith("S001:")}},
                         indent=2))
