"""CLI utility to generate reproducible synthetic scenario cohorts."""

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrypay.evaluation.generator import (
    ScenarioGenerationConfig,
    SyntheticScenarioGenerator,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic checkout failure scenarios.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for scenario generation")
    parser.add_argument("--cohort-size", type=int, default=1000, help="Number of synthetic cases")
    parser.add_argument(
        "--output", type=str, default="data/synthetic_cohort.json", help="Output JSON path"
    )
    args = parser.parse_args()

    config = ScenarioGenerationConfig(seed=args.seed, cohort_size=args.cohort_size)
    gen = SyntheticScenarioGenerator(config)
    cohort = gen.generate_cohort()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cohort.model_dump_json(indent=2), encoding="utf-8")

    print(f"Successfully generated synthetic cohort: {cohort.cohort_id}")
    print(f"Total cases: {len(cohort.cases)}")
    print(f"Saved to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
