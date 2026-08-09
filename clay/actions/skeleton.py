"""
Deterministic workflow skeleton generator.

Builds clay/data/workflows/system/registry/ — an example workflow tree that
teaches an LLM the JSON authoring conventions (workflow.steps, actionSets,
loadContext, loop, includedData id-chaining, examples.override) using the live
action registry, instead of the raw JSON Schema dump previously injected as
__schema__. clay/actions/registry.py is not modified by this module.

Under workflows/system/ because it is clay's own operating content rather than
anything a user edits: it is generated from the action schemas, so it has to
update with the program. It is committed, and `clay build` is what re-renders
it — the destination is chosen there (clay/cli.py:build), not here.

    from clay.actions.skeleton import WorkflowSkeleton

    WorkflowSkeleton().write(config.data_path('workflows', 'system', 'registry'))
"""
from __future__ import annotations

import json
import os
import typing
from dataclasses import MISSING, fields

from .registry import _REGISTRY, _json_type


class WorkflowSkeleton:
    """Builds the registry tree from the fields flagged skeleton=True in _REGISTRY."""

    def action(self, type_name: str) -> dict:
        """One fully-instrumented action for `type_name`.

        Required fields, and optional fields whose declared default is None,
        render a type marker ("<string>", "<integer>", ...). Optional fields
        with a non-None default render that literal default. Field order
        follows dataclasses.fields() declaration order, with 'type' inserted
        right after 'id' to match real workflow JSON (id then type).
        """
        cls = _REGISTRY[type_name]
        hints = typing.get_type_hints(cls)
        result: dict = {}
        for f in fields(cls):
            if not f.metadata.get("skeleton", True):
                continue
            result[f.name] = self._field_value(f, hints)
            if f.name == "id":
                result["type"] = type_name
        if "type" not in result:
            result["type"] = type_name
        return result

    @staticmethod
    def _field_value(f, hints):
        if f.default is MISSING or f.default is None:
            json_type = _json_type(hints.get(f.name)) or "string"
            return f"<{json_type}>"
        return f.default

    def build(self) -> dict[str, dict]:
        """filename -> parsed JSON document, for every file in the tree."""
        return {
            "goal.json": self._goal(),
            "context.json": self._context(),
            "training.json": self._training(),
            "main.json": self._main(),
            "iteration.json": self._iteration(),
        }

    def write(self, dest: str) -> list[str]:
        """Write the tree to `dest`, overwriting existing files. Returns paths written."""
        os.makedirs(dest, exist_ok=True)
        written = []
        for name, doc in self.build().items():
            path = os.path.join(dest, name)
            with open(path, "w") as f:
                json.dump(doc, f, indent=2)
                f.write("\n")
            written.append(path)
        return written

    # ── data files ────────────────────────────────────────────────────────

    def _goal(self) -> dict:
        return {"topic": "example topic this workflow should focus on"}

    def _context(self) -> dict:
        return {"reference": "example supplementary context available alongside goal.json"}

    def _training(self) -> dict:
        return {
            "training_example": [
                {
                    "question": "example question demonstrating the few-shot format",
                    "answer": "example answer demonstrating the few-shot format",
                }
            ]
        }

    # ── workflow files ────────────────────────────────────────────────────

    def _load_context(self, id_: str, file_: str) -> dict:
        entry = self.action("loadContext")
        entry.update({"id": id_, "file": file_})
        return entry

    def _main(self) -> dict:
        focus = self.action("humanDecision")
        focus.update({
            "id": "focus",
            "prompt": "Enter the prompt to show a human, or to send to the AI when running in --auto mode.",
        })

        loop_action = self.action("loop")
        loop_action.update({
            "id": "session_log",
            "file": "./iteration.json",
            "outputKey": "final",
            "includedData": ["topic", "reference", "training_example", "focus"],
        })

        return {
            "autoContext": (
                "Persistent instructions shown to the AI on every scramda2 and "
                "humanDecision call in this workflow. Describe the agent's role "
                "and behavior here."
            ),
            "workflow": {"steps": ["setup", "run_loop"]},
            "actionSets": {
                "setup": [
                    self._load_context("goal", "./goal.json"),
                    self._load_context("context", "./context.json"),
                    self._load_context("training", "./training.json"),
                    focus,
                ],
                "run_loop": [loop_action],
            },
        }

    def _iteration(self) -> dict:
        read_input = self.action("readFile")
        read_input["id"] = "input_read"

        scramda2 = self.action("scramda2")
        scramda2.update({
            "id": "scramda2_actions_result",
            "prompt": "<string> {topic} {focus} {input_read}",
            "examples": {"override": "training_example"},
            "includedData": ["topic", "focus", "input_read"],
        })

        write_output = self.action("writeFile")
        write_output.update({
            "id": "output_write",
            "content": "scramda2_actions_result",
            "includedData": ["scramda2_actions_result"],
        })

        human_decision = self.action("humanDecision")
        human_decision.update({
            "id": "human_decision_response",
            "prompt": "Enter the prompt to show a human, or to send to the AI when running in --auto mode. (iteration {iteration})",
            "includedData": ["iteration"],
        })

        workflow_action = self.action("workflow")
        workflow_action.update({
            "id": "workflow_actions_result",
            "outputKey": "final",
        })

        return {
            "workflow": {
                "steps": [
                    "read_input", "scramda2_actions", "write_output",
                    "human_decision", "workflow_actions",
                ]
            },
            "actionSets": {
                "read_input": [read_input],
                "scramda2_actions": [scramda2],
                "write_output": [write_output],
                "human_decision": [human_decision],
                "workflow_actions": [workflow_action],
            },
        }


def workflow_template_json(indent: int = 2) -> str:
    """The skeleton tree as one JSON document keyed by filename.

    Seeded into every workflow run as the __workflow_template__ engine global
    (clay/cli.py:_load_config), so prompt-authoring workflows can pull a worked
    example of clay's JSON conventions through includedData.

    Generated live rather than read back from the committed tree: no file I/O,
    nothing to go stale, and no dependency on having run `clay build`. The
    committed tree is asserted identical to build() by test_skeleton.py.

    discover() is called here so the function is safe to use standalone; it is
    a no-op once the registry is populated.
    """
    from .registry import discover
    discover()
    return json.dumps(WorkflowSkeleton().build(), indent=indent)
