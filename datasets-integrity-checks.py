from datasets import load_dataset
from itertools import islice
import textwrap, sys

DATASETS = [
    # 1) DOLMA + JSON
    {
        "hub_path": "AI-Culture-Commons/ai-culture-multilingual-json-dolma",
        "configs": ["dolma", "json"],
        "streaming": {"dolma": False, "json": False}, 
    },
    # 2) CSV
    {
        "hub_path": "AI-Culture-Commons/philosophy-culture-translations-html-csv",
        "configs": ["csv"],
        "streaming": {"csv": False},
    },
]

WRAP = lambda s: textwrap.shorten(repr(s), width=80, placeholder="…")

def check_one(hub_path: str, config: str, streaming: bool):
    """Load a single (hub_path, config), print info or raise the exception."""
    print(f"\n▶ {hub_path}  |  config='{config}'  |  streaming={streaming}")
    ds = load_dataset(
        hub_path,
        name=config,
        split="train",
        streaming=streaming,
    )

    # Rows
    print(f"  rows: {len(ds):,}")

    # Columns
    print("  columns:", list(ds.features.keys()) if hasattr(ds, "features") else "N/A")

    # 3 Samples
    example_rows = [ds[0], ds[1], ds[-1]]
    for idx, row in enumerate(example_rows, 1):
        preview = {k: WRAP(v) for k, v in row.items()}
        print(f"    sample {idx}: {preview}")

def main() -> None:
    failed = False
    for item in DATASETS:
        for config in item["configs"]:
            try:
                check_one(item["hub_path"], config, item["streaming"].get(config, False))
            except Exception as e:
                failed = True
                print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
