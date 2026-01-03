from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from .cfg import form_blocks, form_cfg
from .ir import BlockInfo
from .render import cfg_to_dot, print_cfg, print_blocks
from .passes import dce_local_only, dce_global_only, dce_both, local_value_numbering

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PassSpec:
    name: str
    description: str
    run: Callable[[BlockInfo], None]


PASS_REGISTRY: Dict[str, PassSpec] = {
    "dce-local": PassSpec("dce-local", "Local DCE (per-block dead-store elimination).", dce_local_only),
    "dce-global": PassSpec("dce-global", "Global simple DCE (unused dest removal to fixed point).", dce_global_only),
    "dce": PassSpec("dce", "DCE both (global simple DCE then local DCE).", dce_both),
    "lvn": PassSpec("lvn", "Local value numbering (per basic block).", lambda blks: _run_lvn(blks)),
}


def _run_lvn(blks: BlockInfo) -> None:
    for block in blks.label_map.values():
        local_value_numbering(block)


def list_passes_text() -> str:
    lines = ["Available passes:"]
    for name in sorted(PASS_REGISTRY.keys()):
        lines.append(f"  {name:<10} {PASS_REGISTRY[name].description}")
    return "\n".join(lines)


def parse_pipeline(passes_flags: List[str]) -> List[str]:
    """
    Accepts repeated --passes entries, each may be comma-separated.
    """
    out: List[str] = []
    for item in passes_flags:
        for p in item.split(","):
            p = p.strip()
            if p:
                out.append(p)
    return out


def dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def output_json_prog(program: List[BlockInfo]) -> None:
    """
    Outputs transformed program as Bril JSON. Only called if --emit-json is set.
    This mirrors your original behavior: re-linearize blocks and reinsert labels
    where applicable.
    """
    out = {"functions": []}

    for blks in program:
        func_obj: Dict[str, Any] = {
            "name": blks.function_name,
            **{k: v for k, v in blks.function_meta.items() if k not in ("name", "instrs")},
            "instrs": [],
        }

        # Invert label map: block_id -> bril_label
        block_id_to_label = {block_id: label for label, block_id in blks.label_to_block_id.items()}

        instrs: List[Dict[str, Any]] = []
        for block_id, block in blks.label_map.items():
            if block_id in block_id_to_label:
                instrs.append({"label": block_id_to_label[block_id]})
            instrs.extend(block)

        func_obj["instrs"] = instrs
        out["functions"].append(func_obj)

    print(json.dumps(out, indent=2))


def run_driver(
    prog: Dict[str, Any],
    *,
    pipeline: List[str],
    do_cfg: bool,
    cfg_format: str,
    cfg_show_instrs: bool,
    dump_blocks_flag: bool,
    blocks_show_instrs: bool,
    emit_json: bool,
) -> int:
    if "functions" not in prog or not isinstance(prog["functions"], list):
        logger.error("Input JSON missing 'functions' list.")
        return 1

    # Validate pipeline
    for p in pipeline:
        if p not in PASS_REGISTRY:
            logger.error("Unknown pass '%s'. Use --list-passes.", p)
            return 1

    program: List[BlockInfo] = []

    for func in prog["functions"]:
        name = func.get("name", "<unknown>")
        instrs = func.get("instrs", [])
        func_meta = {k: v for k, v in func.items() if k not in ("name", "instrs")}
        blks = form_blocks(instrs, name, function_meta=func_meta)

        # Run passes
        for p in pipeline:
            PASS_REGISTRY[p].run(blks)

        # CFG is required for CFG output; form it on demand.
        if do_cfg or cfg_format:
            form_cfg(blks)

        # Optional outputs (only when flags are set)
        if dump_blocks_flag:
            print_blocks(blks, show_instrs=blocks_show_instrs)

        if do_cfg:
            if cfg_format == "dot":
                print(cfg_to_dot(blks, name, show_instrs=cfg_show_instrs))
            elif cfg_format == "text":
                print_cfg(blks, show_instrs=cfg_show_instrs)
            elif cfg_format == "both":
                print_cfg(blks, show_instrs=cfg_show_instrs)
                print(cfg_to_dot(blks, name, show_instrs=cfg_show_instrs))
            else:
                logger.error("Unknown CFG format '%s'.", cfg_format)
                return 1

        program.append(blks)

    if emit_json:
        output_json_prog(program)

    return 0
