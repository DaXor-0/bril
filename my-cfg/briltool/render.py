from __future__ import annotations

import json
from typing import List

from .ir import BlockInfo


def print_blocks(blks: BlockInfo, *, show_instrs: bool) -> None:
    print(f"BLOCKS for FUNCTION {blks.function_name}")
    for label, instrs in blks.label_map.items():
        print(f"  BLOCK {label}")
        if show_instrs:
            for instr in instrs:
                print(f"    {instr}")
        print("")


def print_cfg(blks: BlockInfo, *, show_instrs: bool = False) -> None:
    print("Control Flow Graph:")
    print(f"FUNCTION {blks.function_name}")

    for label, block in blks.label_map.items():
        print(f"  BLOCK   {label}")
        print(f"    SUCCESSORS   {', '.join(blks.successors.get(label, [])) or '∅'}")
        print(f"    PREDECESSORS {', '.join(blks.predecessors.get(label, [])) or '∅'}")

        if show_instrs:
            print("    Instructions:")
            for instr in block:
                print(f"      {instr}")
        print("")


def cfg_to_dot(blks: BlockInfo, func_name: str, *, show_instrs: bool = False) -> str:
    def q(s: str) -> str:
        # Quote node ids (because your ids include ':' which DOT can misread).
        esc = s.replace("\\", "\\\\").replace('"', '\\"')
        return f"\"{esc}\""

    lines: List[str] = []
    lines.append(f"digraph {q(func_name)} {{")

    for block_name, block in blks.label_map.items():
        if show_instrs:
            instrs = "\\l".join(json.dumps(i) for i in block) + "\\l"
            label = f"{block_name}:\\l{instrs}"
            label = label.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f"  {q(block_name)} [label=\"{label}\"];")
        else:
            lines.append(f"  {q(block_name)};")

    for src, targets in blks.successors.items():
        for tgt in targets:
            lines.append(f"  {q(src)} -> {q(tgt)};")

    lines.append("}")
    return "\n".join(lines)
