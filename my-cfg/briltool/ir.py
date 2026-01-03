from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeAlias

Instruction: TypeAlias = Dict[str, Any]

TERMINATORS = {"jmp", "br", "ret"}
COMMUTATIVE = {"add", "mul"}


def is_label(instr: Instruction) -> bool:
    """A Bril label instruction has 'label' and no 'op'."""
    return "label" in instr and "op" not in instr


def get_dest(instr: Instruction) -> Optional[str]:
    """Bril 'dest' is typically a string. Return None if absent."""
    d = instr.get("dest")
    return d if isinstance(d, str) else None


def get_args(instr: Instruction) -> List[str]:
    """Bril 'args' is typically a list of strings."""
    args = instr.get("args", [])
    return list(args) if isinstance(args, list) else []


@dataclass
class BlockInfo:
    """
    Basic block + CFG container for one function.
    label_map: block_name -> list of non-label instructions
    label_to_block_id: bril_label -> block_name
    """
    function_name: str
    label_map: Dict[str, List[Instruction]]
    label_to_block_id: Dict[str, str]
    function_meta: Dict[str, Any] = field(default_factory=dict)
    successors: Dict[str, List[str]] = field(default_factory=dict)
    predecessors: Dict[str, List[str]] = field(default_factory=dict)

