from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

from .io import load_json
from .driver import (
    dedupe_preserve_order,
    list_passes_text,
    parse_pipeline,
    run_driver,
)

logger = logging.getLogger(__name__)


def parse_log_level(value: str) -> int:
    value = value.lower()
    aliases = {"d": "debug", "i": "info", "w": "warning", "e": "error", "c": "critical"}
    value = aliases.get(value, value)
    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    if value not in levels:
        raise argparse.ArgumentTypeError(f"Invalid log level '{value}'. Choose from: {', '.join(levels)}")
    return levels[value]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bril toolchain driver (modular passes + CFG/block dumps).")

    p.add_argument("input_file", type=Path, nargs="?", default=Path("-"),
                   help="Path to input JSON file (reads stdin if omitted or '-')")

    p.add_argument("--log-level", type=parse_log_level, default=logging.INFO,
                   help="Logging verbosity (debug|info|warning|error|critical or d|i|w|e|c)")

    # Pipeline
    p.add_argument("--list-passes", action="store_true",
                   help="List available passes and exit.")
    p.add_argument("--passes", action="append", default=[],
                   help="Comma-separated pipeline passes (repeatable). Example: --passes dce-local,lvn")

    # Convenience flags (expand into passes)
    p.add_argument("--dce", choices=["local", "global", "both"],
                   help="Convenience: add DCE pass (local/global/both) to the pipeline.")
    p.add_argument("--lvn", action="store_true",
                   help="Convenience: add 'lvn' to the pipeline.")

    # Outputs (OFF by default)
    p.add_argument("--emit-json", action="store_true",
                   help="Emit transformed JSON program to stdout.")
    p.add_argument("--dump-blocks", action="store_true",
                   help="Print basic blocks to stdout.")
    p.add_argument("--blocks-show-instrs", action="store_true",
                   help="Include instructions in --dump-blocks output.")

    p.add_argument("--cfg", action="store_true",
                   help="Print control flow graph to stdout.")
    p.add_argument("--cfg-format", choices=["text", "dot", "both"], default="both",
                   help="CFG output format used with --cfg.")
    p.add_argument("--cfg-show-instrs", action="store_true",
                   help="Include instructions in CFG output (text listing or DOT labels).")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.list_passes:
        print(list_passes_text())
        return 0

    # Build pipeline from --passes plus convenience flags
    pipeline = parse_pipeline(args.passes)

    if args.dce:
        if args.dce == "local":
            pipeline.append("dce-local")
        elif args.dce == "global":
            pipeline.append("dce-global")
        else:
            pipeline.append("dce")

    if args.lvn:
        pipeline.append("lvn")

    pipeline = dedupe_preserve_order(pipeline)

    try:
        prog = load_json(args.input_file)
    except Exception:
        src = "stdin" if str(args.input_file) == "-" else str(args.input_file)
        logger.exception("Failed to load JSON from %s", src)
        return 1

    return run_driver(
        prog,
        pipeline=pipeline,
        do_cfg=args.cfg,
        cfg_format=args.cfg_format,
        cfg_show_instrs=args.cfg_show_instrs,
        dump_blocks_flag=args.dump_blocks,
        blocks_show_instrs=args.blocks_show_instrs,
        emit_json=args.emit_json,
    )
