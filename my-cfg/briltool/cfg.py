from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .ir import BlockInfo, Instruction, TERMINATORS, is_label

logger = logging.getLogger(__name__)


def block_id_generator(func_name: str):
    i = 0
    while True:
        yield f"{func_name}::b{i}"
        i += 1


def form_blocks(body: List[Instruction], name: str) -> BlockInfo:
    """
    Forms basic blocks from a list of instructions.
    1. A block starts at a label or function entry.
    2. A block ends at a terminator (jmp, br, ret) or before a label.
    Labels are not included in blocks; they are tracked in label_to_block_id.
    """
    label_map: Dict[str, List[Instruction]] = {}
    label_to_block_id: Dict[str, str] = {}

    gen = block_id_generator(name)

    current_block: List[Instruction] = []
    current_label: Optional[str] = None

    def close_block():
        nonlocal current_block, current_label
        if not current_block:
            return

        if current_label is not None:
            block_name = f"{name}::{current_label}"
            label_to_block_id[current_label] = block_name
        else:
            block_name = next(gen)

        label_map[block_name] = current_block
        current_block = []
        current_label = None

    for instr in body:
        logger.debug("Processing instruction: %s", instr)

        if is_label(instr):
            # Close previous block before starting a new one at this label.
            close_block()
            current_label = instr["label"]
            continue

        # Non-label instruction
        current_block.append(instr)

        if instr.get("op") in TERMINATORS:
            close_block()

    # Close trailing block
    close_block()

    return BlockInfo(
        function_name=name,
        label_map=label_map,
        label_to_block_id=label_to_block_id,
    )


def form_cfg(blks: BlockInfo) -> None:
    """
    Populates successors and predecessors for each basic block.
    """
    blks.successors.clear()
    blks.predecessors.clear()

    labels = list(blks.label_map.keys())

    for idx, label in enumerate(labels):
        block = blks.label_map[label]
        last_instr = block[-1] if block else {}
        op = last_instr.get("op")

        if op in ("jmp", "br"):
            targets = [blks.label_to_block_id[t] for t in last_instr["labels"]]
        elif op == "ret":
            targets = []
        else:
            targets = [labels[idx + 1]] if idx + 1 < len(labels) else []

        blks.successors[label] = targets
        for t in targets:
            blks.predecessors.setdefault(t, []).append(label)

    for label in blks.label_map:
        blks.predecessors.setdefault(label, [])
        blks.successors.setdefault(label, [])
