import json
import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Dict, Tuple, TypeAlias

logger = logging.getLogger(__name__)

TERMINATORS = {"jmp", "br", "ret"}

# ==================================================================
# PARSER HELPERS
# ==================================================================
def parse_log_level(value: str) -> int:
    value = value.lower()

    aliases = {
        "d": "debug",
        "i": "info",
        "w": "warning",
        "e": "error",
        "c": "critical",
    }

    value = aliases.get(value, value)

    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }

    if value not in levels:
        raise argparse.ArgumentTypeError(
            f"Invalid log level '{value}'. "
            f"Choose from: {', '.join(levels)}"
        )

    return levels[value]

# ==================================================================
# DATA CLASSES FOR BASIC BLOCKS AND CFG
# ==================================================================
@dataclass
class BlockInfo:
    """
    Data class to hold information about basic blocks.
    """
    function_name: str
    label_map: Dict[str, List[Any]]             # block_id -> list of instructions
    label_to_block_id: dict[str, str]           # bril_label -> block_name
    successors: Dict[str, List[str]] = field(default_factory=dict)
    predecessors: Dict[str, List[str]] = field(default_factory=dict)

# ==================================================================
# POGRAN LOADING (JSON FORMAT) FROM FILE OR STDIN
# ==================================================================
def load_json(input_file: Path | None) -> Any:
    """
    Loads JSON content from a file or stdin.
    """
    # Accept also stdin
    if input_file is None or str(input_file) == "-":
        return json.load(sys.stdin)

    with input_file.open("r", encoding="utf-8") as f:
        return json.load(f)

# ==================================================================
# BASIC BLOCK FORMATION
# ==================================================================
def block_id_generator(func_name: str):
    i = 0
    while True:
        yield f"{func_name}::b{i}"
        i += 1

def is_label(isntr: Dict[str, Any]) -> bool:
    return "label" in isntr and "op" not in isntr

def form_blocks(body: List[Dict[str, Any]], name: str) -> BlockInfo:
    """
    Forms basic blocks from a list of instructions.
    1. A block starts at a label or the function entry.
    2. A block ends at a terminator instruction (jmp, br, ret) or before a label.
    """
    blocks : List[List[Any]] = []
    label_map : Dict[str, List[Any]] = {}
    label_to_block_id: Dict[str, str] = {}

    gen = block_id_generator(name)

    current_block : List[Any] = []
    current_label : str | None = None
    for i in body:
        logger.debug("Processing instruction: %s", i)
        if not is_label(i):
            current_block.append(i)
            logger.debug("Added instruction %s to current block.", i)
        if is_label(i) or i.get("op") in TERMINATORS:
            if current_block:
                if current_label is not None:
                    block_name = f"{name}::{current_label}"
                    label_to_block_id[current_label] = block_name
                else:
                    block_name = next(gen)

                blocks.append(current_block)
                label_map[block_name] = current_block
                logger.debug("Formed a block of len %d and started a new one.",
                            len(current_block))

            if is_label(i):
                new_label = i["label"]
            else:
                new_label = None
            current_label = new_label

            current_block = []

    if current_block:
        if current_label is not None:
            block_name = f"{name}::{current_label}"
            label_to_block_id[current_label] = block_name
        else:
            block_name = next(gen)
        blocks.append(current_block)
        label_map[block_name] = current_block
        logger.debug("Added remaining instructions as a final block.")

    return BlockInfo(
        function_name=name,
        label_map=label_map,
        label_to_block_id=label_to_block_id
    )

# ==================================================================
# CONTROL FLOW GRAPH (CFG) FORMATION
# ==================================================================
def form_cfg(blks: BlockInfo) -> None:
    """
    Forms a Control Flow Graph (CFG) by determining successors and predecessors
    for each basic block.
    """
    labels = list(blks.label_map.keys())

    for idx, label in enumerate(labels):
        block = blks.label_map[label]
        last_instr = block[-1]
        op = last_instr.get("op")

        if op in ("jmp", "br"):
            targets = [
                blks.label_to_block_id[t]
                for t in last_instr["labels"]
            ]
        elif op == "ret":
            targets = []
        else:
            targets = [labels[idx + 1]] if idx + 1 < len(labels) else []
        blks.successors[label] = targets
        logger.debug("Successors of '%s' are: %s", label, targets)

        for t in targets:
            blks.predecessors.setdefault(t, []).append(label)
            logger.debug("Predecessor '%s' added to block '%s'.", label, t)

    # Ensure all labels are in predecessors and successors
    for label in blks.label_map:
        blks.predecessors.setdefault(label, [])
        blks.successors.setdefault(label, [])

# ==================================================================
# CFG PRINTING AND DOT EXPORT
# ==================================================================
def print_cfg(blks: BlockInfo, show_instrs: bool = False) -> None:
    print("Control Flow Graph:")
    print(f"FUNCTION {blks.function_name}")

    for label, block in blks.label_map.items():
        print(f"  BLOCK   {label}")
        if logger.isEnabledFor(logging.DEBUG):
            for instr in blks.label_map[label]:
                print(f"            {instr}")
        print(f"    SUCCESSORS   {', '.join(blks.successors.get(label, [])) or '∅'}")
        print(f"    PREDECESSORS {', '.join(blks.predecessors.get(label, [])) or '∅'}")

        if show_instrs:
            print("    Instructions:")
            for instr in block:
                print(f"      {instr}")
        print()

def cfg_to_dot(blks: BlockInfo, func_name: str, show_instrs: bool = False) -> str:
    lines = []
    lines.append(f'digraph {func_name} {{')

    # Emit nodes
    for block_name, block in blks.label_map.items():
        if show_instrs:
            instrs = "\\l".join(json.dumps(i) for i in block) + "\\l"
            lines.append(f'  {block_name} [label="{block_name}:\\l{instrs}"];')
        else:
            lines.append(f'  {block_name};')

    # Emit edges
    for src, targets in blks.successors.items():
        for tgt in targets:
            lines.append(f'  {src} -> {tgt};')

    lines.append("}")
    return "\n".join(lines)

# ==================================================================
# DEAD CODE ELIMINATION
# ==================================================================
def simple_dce(blks: BlockInfo) -> None:
    repeat = True
    pass_num = 0
    while repeat:
        repeat = False
        pass_num += 1
        logger.debug(f"(Simple DCE, pass number {pass_num})")
        used_instrs = set()
        for block in blks.label_map.values():
            for instr in block:
                if "args" in instr:
                    used_instrs.update(instr["args"])
                    logger.debug(f"(Simple DCE, {pass_num}) Instruction {instr} uses args {instr["args"]}")

        for block in blks.label_map.values():
            for instr in block:
                dest = instr.get("dest", [])
                for d in dest:
                    if d not in used_instrs:
                        logger.info(f"(Simple DCE, {pass_num}), Instruction {instr} defines unused dest {d}")
                        block.remove(instr)
                        repeat = True

def local_dce(block: List[Dict[str, Any]]) -> None:
    repeat = True
    pass_num = 0
    while repeat:
        pass_num += 1
        logger.debug(f"(Local DCE, pass number {pass_num})")
        repeat = False
        candidates : Dict[str, Dict[str, Any]] = {}
        for instr in block:
            for arg in instr.get("args", []):
                if arg in candidates:
                    del candidates[arg]

            if "dest" in instr:
                for d in instr["dest"]:
                    if d in candidates:
                        logger.info(f"(Local DCE, {pass_num}) Destination %s already a candidate, overwriting.", d)
                        block.remove(candidates[d])
                        repeat = True
                    candidates[d] = instr

# ==================================================================
# OUTPUT PROGRAM IN JSON
# ==================================================================
def output_json_prog(program: List[BlockInfo]) -> None:
    print("{")
    print('  "functions": [')

    for func_idx, blks in enumerate(program):
        print("    {")
        print(f'      "name": "{blks.function_name}",')
        print('      "instrs": [')

        # Invert label map once
        block_id_to_label = {
            block_id: label
            for label, block_id in blks.label_to_block_id.items()
        }

        instrs = []
        for block_id, block in blks.label_map.items():
            # Reinsert label if this block has one
            if block_id in block_id_to_label:
                instrs.append({"label": block_id_to_label[block_id]})

            instrs.extend(block)

        for i, instr in enumerate(instrs):
            comma = "," if i < len(instrs) - 1 else ""
            print(f"        {json.dumps(instr)}{comma}")

        print("      ]")
        comma = "," if func_idx < len(program) - 1 else ""
        print(f"    }}{comma}")

    print("  ]")
    print("}")

# ==================================================================
# LOCAL VALUE NUMBERING (LVN)
# ==================================================================
LVNExpr: TypeAlias = Tuple[str, Tuple[Any, ...]]

@dataclass
class LVNTable:
    expr2id: Dict[LVNExpr, int] = field(default_factory=dict)
    id2canon: Dict[int, str] = field(default_factory=dict)
    current_status: Dict[str, int] = field(default_factory=dict)
    next_id: int = 0

def _ensure_var_id(var: str, lvn) -> int:
    """Assign a value number to an input var if unseen."""
    if var not in lvn.current_status:
        vid = lvn.next_id
        lvn.next_id += 1
        lvn.current_status[var] = vid
        lvn.id2canon.setdefault(vid, var)
    return lvn.current_status[var]

def _get_expr(op: str, instr: Dict[str, Any], lvn) -> LVNExpr:
    if op == "const":
        return (op, (("c", instr["value"]),))
    elif op == "id":
        src = instr["args"][0]
        return (op, (("v", _ensure_var_id(src, lvn)),))
    elif op in {"add", "mul", "sub", "div", "print"}:
        keys = tuple(("v", _ensure_var_id(a, lvn)) for a in instr["args"])
        return (op, keys)
    else:
        raise ValueError(f"Unsupported operation for LVN: {op}")

def local_value_numbering(block: List[Dict[str, Any]]) -> None:
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

# ==================================================================
# MAIN FUNCTION
# ==================================================================
def main(input_file: Path | None) -> int:
    """
    Main function to load JSON and form basic blocks for each function.
    """
    # Load program in JSON format.
    source = "stdin" if input_file is None or str(input_file) == "-" else input_file
    try:
        prog = load_json(input_file)
    except Exception:
        logger.exception("Failed to load JSON from %s", source)
        return 1
    logger.debug("Successfully loaded JSON from %s", source)
    logger.debug("Loaded JSON content:\n%s", json.dumps(prog, indent=2))

    # Process each function to form basic blocks
    program : List[BlockInfo] = []
    for func in prog['functions']:
        blks = form_blocks(func["instrs"], func["name"])
        logger.debug("Function '%s' has %d blocks.", func["name"], len(blks.label_map))

        if args.dce:
            simple_dce(blks)
            logger.debug("Performed simple dead code elimination on function '%s'.", func["name"])
            for block in blks.label_map.values():
                local_dce(block)

        # Process basc blocks to form a Control Flow Graph (CFG)
        form_cfg(blks)
        logger.debug("Formed CFG for function '%s'.", func["name"])
        if args.cfg_out:
            print_cfg(blks)
            dot = cfg_to_dot(blks, func["name"])
            print(dot)

        program.append(blks)

    if args.show_instrs:
        output_json_prog(program)

    return 0

# ==================================================================
# ENTRY POINT
# ==================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task 2 Script")
    parser.add_argument("input_file", type=Path, nargs="?",
        help="Path to the input JSON file (reads stdin if omitted or '-')")
    parser.add_argument("--log-level", type=parse_log_level, default=logging.INFO,
        help="Logging verbosity (debug|info|warning|error|critical or d|i|w|e|c)")
    parser.add_argument("--dce", action="store_true", 
        help="Perform simple dead code elimination on basic blocks")
    parser.add_argument("--cfg-out", action="store_true",
        help="Output the control flow graph in DOT format")
    parser.add_argument("--lvn", action="store_true",
        help="Perform local value numbering on basic blocks")
    parser.add_argument("--show-instrs", action="store_true",
        help="Output to stdout the program json")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sys.exit(main(args.input_file))

