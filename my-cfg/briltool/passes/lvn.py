from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, TypeAlias

from ..ir import Instruction, TERMINATORS, COMMUTATIVE

logger = logging.getLogger(__name__)

LVNExpr: TypeAlias = Tuple[str, Tuple[Any, ...]]


@dataclass
class LVNTable:
    expr2id: Dict[LVNExpr, int] = field(default_factory=dict)
    id2canon: Dict[int, str] = field(default_factory=dict)
    current_status: Dict[str, int] = field(default_factory=dict)
    next_id: int = 0


def _ensure_var_id(var: str, lvn: LVNTable) -> int:
    """
    Return the current value-number id for `var`.
    If `var` is unseen in this block, allocate a fresh id and record it.
    """
    if var not in lvn.current_status:
        vid = lvn.next_id
        lvn.next_id += 1
        lvn.current_status[var] = vid
        lvn.id2canon.setdefault(vid, var)
    return lvn.current_status[var]


def _get_expr(op: str, instr: Instruction, lvn: LVNTable) -> LVNExpr:
    """
    Build a hashable expression key for LVN memoization/CSE.

    Operands are encoded as:
      - ("c", literal) for constants
      - ("v", value_id) for variable arguments (using their current value number)
    """
    if op == "const":
        return (op, (("c", instr["value"]),))
    elif op == "id":
        src = instr["args"][0]
        return (op, (("v", _ensure_var_id(src, lvn)),))
    elif op in {"add", "mul", "sub", "div", "print"}:
        keys = tuple(("v", _ensure_var_id(a, lvn)) for a in instr["args"])
        if op in COMMUTATIVE:
            keys = tuple(sorted(keys))
        return (op, keys)
    else:
        raise ValueError(f"Unsupported operation for LVN: {op}")


def local_value_numbering(block: List[Instruction]) -> None:
    """
    Local Value Numbering (LVN) within a single basic block.

    - Rewrites argument names to a canonical representative when safe.
    - Performs CSE for supported ops by memoizing expression keys.
    - Treats `id` as a copy (dest gets the same value number as src).
    - Skips labels/terminators and does not memoize dest-less ops (e.g., print).
    """
    lvn = LVNTable()
    logger.debug("Starting LVN on block %s", block)

    for instr in block:
        op = instr.get("op", None)
        if op is None or op in TERMINATORS:
            continue
        # ----------------------------------------------------------
        # Canonicalize args
        # ----------------------------------------------------------
        args = instr.get("args")
        if isinstance(args, list):
            rewritten_args: List[str] = []
            for a in args:
                vid = _ensure_var_id(a, lvn)
                canon = lvn.id2canon.get(vid) or a

                if canon != a and lvn.current_status.get(canon) == vid:
                    logger.info("Rewriting arg %s to canon %s for instruction %s",
                                a, canon, instr)
                    rewritten_args.append(canon)
                else:
                    rewritten_args.append(a)
            instr["args"] = rewritten_args

        # ----------------------------------------------------------
        # Skip memoization for dest-less instructions
        # ----------------------------------------------------------
        dest = instr.get("dest")
        if dest is None:
            continue

        # ----------------------------------------------------------
        # For ID ops, directly map dest to src's value id.
        # ----------------------------------------------------------
        if op == "id":
            src = instr["args"][0]
            src_vid = _ensure_var_id(src, lvn)
            canon = lvn.id2canon.get(src_vid, src)

            if lvn.current_status.get(canon) == src_vid:
                instr["args"] = [canon]

            lvn.current_status[dest] = src_vid
            lvn.id2canon.setdefault(src_vid, canon)
            continue # skip expr memoization/CSE for `id`

        # ----------------------------------------------------------
        # For other ops, perform expression memoization
        # ----------------------------------------------------------
        expr : LVNExpr = _get_expr(op, instr, lvn)
        expr_id = lvn.expr2id.get(expr)

        if expr_id is None: # New expression, allocate fresh id
            expr_id = lvn.next_id
            lvn.next_id += 1
            lvn.expr2id[expr] = expr_id

            lvn.current_status[dest] = expr_id
            lvn.id2canon[expr_id] = dest
            continue

        canon_var = lvn.id2canon[expr_id] 
        if lvn.current_status.get(canon_var) == expr_id:
            logger.info("LVN CSE: Rewriting instruction %s to id %s", instr, canon_var)
            instr["op"] = "id"
            instr["args"] = [canon_var]

        lvn.current_status[dest] = expr_id

