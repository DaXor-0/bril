import json
import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Dict

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
    blocks: List[List[Any]]                     # list of blocks, each block is a list of instructions
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
        i += 1
        yield f"{func_name}::b{i}"

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
        blocks=blocks,
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

def program_name_from_input(input_file: Path | None) -> str:
    if input_file is None or str(input_file) == "-":
        return "stdin"
    return input_file.stem

def cfg_to_dot(blks: BlockInfo, func_name: str, show_instrs: bool = False) -> str:
    lines = []
    lines.append(f'digraph "{func_name}_CFG" {{')

    # Emit nodes
    for block_name, block in blks.label_map.items():
        if show_instrs:
            instrs = "\\l".join(json.dumps(i) for i in block) + "\\l"
            label = f"{block_name}:\\l{instrs}"
        else:
            label = block_name

        lines.append(f'  "{block_name}" [label="{label}"];')

    # Emit edges
    for src, targets in blks.successors.items():
        for tgt in targets:
            lines.append(f'  "{src}" -> "{tgt}";')

    lines.append("}")
    return "\n".join(lines)

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
    logger.info("Successfully loaded JSON from %s", source)
    logger.debug("Loaded JSON content:\n%s", json.dumps(prog, indent=2))



    prog_name = program_name_from_input(input_file)

    # Process each function to form basic blocks
    for func in prog['functions']:
        blks = form_blocks(func["instrs"], func["name"])
        logger.info("Function '%s' has %d blocks.", func["name"], len(blks.blocks))

        # Process basc blocks to form a Control Flow Graph (CFG)
        form_cfg(blks)
        logger.info("Formed CFG for function '%s'.", func["name"])
        print_cfg(blks)

        if args.output:
            dot = cfg_to_dot(blks, func["name"])
            out_name = f"{func['name']}-{prog_name}.dot"

            with open(out_name, "w", encoding="utf-8") as f:
                f.write(dot)

            logger.info("Wrote CFG to %s", out_name)

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
    parser.add_argument("-o", "--output", action="store_true",
        help="Emit CFG as Graphviz .dot file(s)")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sys.exit(main(args.input_file))

