"""Tiny CLI to run the pipeline once without the HTTP server.

Usage:
    python -m app.cli --name "Rosemary Hair Growth Oil" \
        --image https://example.com/product.jpg \
        --description "Natural rosemary oil for hair growth" \
        --benefit "Reduce hair shedding" --benefit "Promote thicker hair"
"""
from __future__ import annotations

import argparse
import logging

from app.containers import Container
from app.core.entities import ProductInput
from app.database.session import init_db
from app.logging_config import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and deploy a TikTok ad creative.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--image", default="", help="Product image URL (not required for --script-only).")
    parser.add_argument("--description", default="")
    parser.add_argument("--benefit", action="append", default=[], dest="benefits")
    parser.add_argument("--landing-page", default=None)
    parser.add_argument(
        "--script",
        default=None,
        help="Prepared ad script. When set, the script generator (Gemini) is skipped.",
    )
    parser.add_argument(
        "--script-file",
        default=None,
        help="Path to a file containing the prepared script (alternative to --script).",
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Generate + download the video only; skip TikTok upload and ad creation.",
    )
    parser.add_argument(
        "--script-only",
        action="store_true",
        help="Generate ONLY the script (profiles-aware) — no video, no ad, nothing persisted.",
    )
    args = parser.parse_args()

    script_text = args.script
    if args.script_file:
        with open(args.script_file, "r", encoding="utf-8") as fh:
            script_text = fh.read()

    container = Container()
    configure_logging(container.settings().log_level)
    init_db(container.engine())

    product = ProductInput(
        name=args.name,
        image_url=args.image,
        description=args.description,
        benefits=args.benefits,
    )

    # Script-only: run just the Strategist and print the structured result.
    if args.script_only:
        out = container.script_strategist().generate(product, 0)
        print("\n--- SCRIPT (%s) ---" % out.provider)
        print(out.script)
        print("\n--- STRATEGY ---")
        print(f"angle={out.angle}  hook_type={out.hook_type}  segment={out.audience_segment}")
        print(f"mode={out.mode}  similarity={out.similarity:.2f}  words={len(out.script.split())}")
        return
    result = container.creative_service().run(
        product,
        script_text=script_text,
        deploy=not args.no_deploy,
        landing_page_url=args.landing_page,
    )

    log = logging.getLogger("cli")
    log.info("Done. deployed=%s video=%s", result.deployed, result.local_video_path)
    print("\n--- SCRIPT (%s) ---" % result.script_provider)
    print(result.script_text)
    print("\n--- RESULT ---")
    print(f"local_video={result.local_video_path}")
    if result.deployed:
        print(f"ad_id={result.ad_id}")
        print(f"creative_id={result.creative_id}")
        print(f"platform_video_id={result.platform_video_id}")
    else:
        print("deployed=False (video only — TikTok upload/ad skipped)")


if __name__ == "__main__":
    main()
