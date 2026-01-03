from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, TypeAlias

from ..ir import Instruction, TERMINATORS

LVNExpr: TypeAlias = Tuple[str, Tuple[Any, ...]]


@dataclass
class LVNTable:
    expr2id: Dict[LVNExpr, int] = field(default_factory=dict)
    id2canon: Dict[int, str] = field(default_factory=dict)
    current_status: Dict[str, int] = field(default_factory=dict)
    next_id: int = 0


def _ensure_var_id(var: str, lvn: LVNTable) -> int:
    if var not in lvn.current_status:
        vid = lvn.next_id
        lvn.next_id += 1
        lvn.current_status[var] = vid
        lvn.id2canon.setdefault(vid, var)
    return lvn.current_status[var]


def _get_expr(op: str, instr: Instruction, lvn: LVNTable) -> LVNExpr:
    if op == "const":
        return (op, (("c", instr["value"]),))
    elif op == "id":
        src = instr["args"][0]
        return (op, (("v", _ensure_var_id(src, lvn)),))
    elif op in {"add", "mul", "sub", "div"}:
        keys = tuple(("v", _ensure_var_id(a, lvn)) for a in instr["args"])
        return (op, keys)
    else:
        raise ValueError(f"Unsupported operation for LVN: {op}")


def local_value_numbering(block: List[Instruction]) -> None:
    """
    Preserves your original LVN behavior (no commutativity normalization, etc.).
    Only supports const/id/add/mul/sub/div and skips labels/terminators.
    """
    lvn = LVNTable()

    for instr in block:
        op = instr.get("op", None)
        if op is None or op in TERMINATORS:
            continue
        # ----------------------------------------------------------
        # Canonicalize args (including for dest-less ops like print),
        # but do NOT memoize dest-less ops.
        # Only rewrite arg -> canon if canon still represents the same value id.
        # ----------------------------------------------------------
        if "args" in instr and isinstance(instr["args"], list):
            new_args = []
            for a in instr["args"]:
                vid = _ensure_var_id(a, lvn)
                canon = lvn.id2canon.get(vid, a)
                if canon and lvn.current_status.get(canon) == vid:
                    new_args.append(canon)
                else:
                    new_args.append(a)
            instr["args"] = new_args

        dest = instr.get("dest")
        if dest is None:
            # Dest-less op: rewritten args are kept, but we skip LVN memoization/CSE.
            continue

        expr : LVNExpr = _get_expr(op, instr, lvn)

        if expr in lvn.expr2id:
            expr_id = lvn.expr2id[expr]
            var = lvn.id2canon[expr_id]

            # Convert to id if canonical var currently represents the expr id
            if lvn.current_status.get(var) == expr_id:
                instr["op"] = "id"
                instr["args"] = [var]

            lvn.current_status[dest] = expr_id
        else:
            expr_id = lvn.next_id
            lvn.next_id += 1
            lvn.expr2id[expr] = expr_id

            lvn.current_status[dest] = expr_id
            lvn.id2canon[expr_id] = dest

