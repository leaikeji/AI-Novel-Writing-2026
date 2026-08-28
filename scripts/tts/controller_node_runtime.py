#!/usr/bin/env python3
"""Fixed import boundary for the hyphenated controller-node bootstrap."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Final, Mapping


_BOOTSTRAP_PATH: Final = (
    Path(__file__).resolve().parent
    / "controller-node"
    / "bootstrap_node_runtime.py"
)


def _load_bootstrap() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "_ai_novel_t4k_controller_node_bootstrap",
        _BOOTSTRAP_PATH,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("CONTROLLER_NODE_BOOTSTRAP_UNAVAILABLE")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


_BOOTSTRAP = _load_bootstrap()
ControllerNodeRuntimeError = _BOOTSTRAP.RuntimeBootstrapError


def fixed_node_executable() -> Path:
    return _BOOTSTRAP.runtime_root() / "bin" / "node"


def verify_controller_node_environment() -> Mapping[str, object]:
    return _BOOTSTRAP.verify_all()


__all__ = [
    "ControllerNodeRuntimeError",
    "fixed_node_executable",
    "verify_controller_node_environment",
]
