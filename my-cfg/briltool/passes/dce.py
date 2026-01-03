from __future__ import annotations

import logging
from typing import Dict, List, Set

from ..ir import BlockInfo, Instruction, get_args, get_dest

logger = logging.getLogger(__name__)


def simple_dce(blks: BlockInfo) -> None:
    """
    Simple DCE across the function:
    - Collect all variables used in args across all instructions.
    - Remove any instruction whose dest is never used.
    Repeats to fixed point.

    Note: This preserves your original intent and does not attempt to reason about side effects.
    """
    repeat = True
    pass_num = 0

    while repeat:
        repeat = False
        pass_num += 1
        logger.debug("(Simple DCE, pass number %d)", pass_num)

        used: Set[str] = set()
        for block in blks.label_map.values():
            for instr in block:
                used.update(get_args(instr))

        for block_name, block in blks.label_map.items():
            new_block: List[Instruction] = []
            for instr in block:
                d = get_dest(instr)
                if d is None:
                    new_block.append(instr)
                    continue

                if d not in used:
                    logger.info("(Simple DCE, %d) removing unused def in %s: %s", pass_num, block_name, instr)
                    repeat = True
                else:
                    new_block.append(instr)

            blks.label_map[block_name] = new_block


def local_dce(block: List[Instruction]) -> None:
    """
    Local DCE (dead-store elimination) within a block:
    if a dest is overwritten before any use, remove the earlier write.
    Repeats to fixed point.

    This follows your original approach (candidate tracking) without changing its spirit.
    """
    repeat = True
    pass_num = 0

    while repeat:
        pass_num += 1
        logger.debug("(Local DCE, pass number %d)", pass_num)
        repeat = False

        candidates: Dict[str, Instruction] = {}

        for instr in list(block):
            # Uses kill candidates
            for arg in instr.get("args", []) if isinstance(instr.get("args", []), list) else []:
                candidates.pop(arg, None)

            d = get_dest(instr)
            if d is None:
                continue

            if d in candidates:
                logger.info("(Local DCE, %d) removing overwritten def: %s", pass_num, candidates[d])
                block.remove(candidates[d])
                repeat = True

            candidates[d] = instr


def dce_local_only(blks: BlockInfo) -> None:
    for block in blks.label_map.values():
        local_dce(block)


def dce_global_only(blks: BlockInfo) -> None:
    simple_dce(blks)


def dce_both(blks: BlockInfo) -> None:
    """
    Matches your prior behavior: simple_dce then local_dce on each block.
    """
    simple_dce(blks)
    for block in blks.label_map.values():
        local_dce(block)

