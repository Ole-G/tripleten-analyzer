"""
Unified pipeline orchestrator for TripleTen integration analytics.

Runs all 6 pipeline steps sequentially:
  1. Data preparation (CSV parsing, YouTube metadata + transcripts)
  2. Audio transcription via Whisper (for videos without captions)
  3. LLM enrichment — YouTube integrations
  4. LLM enrichment — Reels / TikTok integrations
  5. Correlation analysis (merge + report via Claude Opus)
  6. Textual analysis (feature extraction + comparison + report)

Usage:
    python -m scripts.run_pipeline                    # Run all steps
    python -m scripts.run_pipeline --from-step 3      # Resume from step 3
    python -m scripts.run_pipeline --only-step 5      # Run step 5 only
    python -m scripts.run_pipeline --skip-steps 2 4   # Skip steps 2 and 4
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

STEPS = {
    1: ("Data Preparation", "scripts.data_prep"),
    2: ("Audio Transcription (Whisper)", "scripts.run_transcription"),
    3: ("LLM Enrichment — YouTube", "scripts.run_enrichment"),
    4: ("LLM Enrichment — Reels/TikTok", "scripts.run_enrichment_reels"),
    5: ("Correlation Analysis Report", "scripts.run_analysis"),
    6: ("Textual Analysis Report", "scripts.run_textual_analysis"),
}


def _print_banner(step_num: int, name: str) -> None:
    """Print a visible step banner."""
    print(f"\n{'=' * 70}")
    print(f"  STEP {step_num}/6: {name}")
    print(f"{'=' * 70}\n")


def _run_step(step_num: int) -> bool:
    """Run a single pipeline step. Returns True on success, False on error."""
    name, module_name = STEPS[step_num]
    _print_banner(step_num, name)
    start = time.time()

    try:
        if step_num == 1:
            from scripts.data_prep import main as step_main
            step_main()
        elif step_num == 2:
            from scripts.run_transcription import main as step_main
            step_main(platform="all")
        elif step_num == 3:
            from scripts.run_enrichment import main as step_main
            step_main()
        elif step_num == 4:
            from scripts.run_enrichment_reels import main as step_main
            step_main(platform="all")
        elif step_num == 5:
            from scripts.run_analysis import main as step_main
            step_main()
        elif step_num == 6:
            from scripts.run_textual_analysis import main as step_main
            step_main(platform="all")

        elapsed = time.time() - start
        print(f"\n✅ Step {step_num} ({name}) completed in {elapsed:.1f}s\n")
        return True

    except SystemExit as e:
        # Some scripts call sys.exit() on error — catch and continue
        if e.code and e.code != 0:
            elapsed = time.time() - start
            print(f"\n❌ Step {step_num} ({name}) failed after {elapsed:.1f}s")
            print(f"   (sys.exit with code {e.code})")
            return False
        return True

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ Step {step_num} ({name}) failed after {elapsed:.1f}s")
        print(f"   Error: {e}")
        logger.exception("Step %d failed", step_num)
        return False


def main(
    from_step: int = 1,
    only_step: int = None,
    skip_steps: list[int] = None,
) -> None:
    """
    Run the full pipeline.

    Args:
        from_step: Start from this step number (1-6).
        only_step: Run only this step number.
        skip_steps: List of step numbers to skip.
    """
    skip_steps = set(skip_steps or [])

    # Determine which steps to run
    if only_step:
        steps_to_run = [only_step]
    else:
        steps_to_run = [s for s in range(from_step, 7) if s not in skip_steps]

    print("\n" + "=" * 70)
    print("  TRIPLETEN INTEGRATION ANALYZER — FULL PIPELINE")
    print("=" * 70)
    print(f"\n  Steps to run: {steps_to_run}")
    for s in steps_to_run:
        print(f"    {s}. {STEPS[s][0]}")
    print()

    results = {}
    pipeline_start = time.time()

    for step_num in steps_to_run:
        success = _run_step(step_num)
        results[step_num] = success

        if not success:
            print(f"\n⚠️  Step {step_num} failed. Continuing with remaining steps...\n")
            # For critical dependencies, we might want to stop
            # Steps 3-4 depend on step 1, steps 5-6 depend on steps 3-4
            if step_num == 1:
                print("   Step 1 (data prep) is required. Stopping pipeline.")
                break

    # Summary
    total_time = time.time() - pipeline_start
    print("\n" + "=" * 70)
    print("  PIPELINE SUMMARY")
    print("=" * 70)
    for step_num in steps_to_run:
        status = results.get(step_num)
        icon = "✅" if status else ("❌" if status is False else "⏭️")
        print(f"  {icon} Step {step_num}: {STEPS[step_num][0]}")
    print(f"\n  Total time: {total_time:.1f}s ({total_time/60:.1f} min)")

    failed = [s for s, ok in results.items() if not ok]
    if failed:
        print(f"\n  ⚠️  Failed steps: {failed}")
        print(f"  Re-run with: python -m scripts.run_pipeline --from-step {failed[0]}")
    else:
        print("\n  🎉 All steps completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the full TripleTen analytics pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.run_pipeline                    # All steps
  python -m scripts.run_pipeline --from-step 3      # Resume from step 3
  python -m scripts.run_pipeline --only-step 5      # Just step 5
  python -m scripts.run_pipeline --skip-steps 2 4   # Skip Whisper & Reels
        """,
    )
    parser.add_argument(
        "--from-step",
        type=int,
        default=1,
        choices=range(1, 7),
        help="Start from this step (1-6, default: 1)",
    )
    parser.add_argument(
        "--only-step",
        type=int,
        default=None,
        choices=range(1, 7),
        help="Run only this step",
    )
    parser.add_argument(
        "--skip-steps",
        type=int,
        nargs="+",
        default=None,
        help="Steps to skip (e.g. --skip-steps 2 4)",
    )
    args = parser.parse_args()
    main(
        from_step=args.from_step,
        only_step=args.only_step,
        skip_steps=args.skip_steps,
    )
