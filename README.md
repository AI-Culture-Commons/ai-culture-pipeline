# ai-culture-pipeline
## AI-Culture Commons Datasets Pipeline

Our [datasets](https://degeneration-of-nation.org/dataset) are created with an **open-source pipeline** that:

1. Processes files from local project directories (no web crawling required)
2. Extracts and processes content through a multi-stage pipeline:
   * **HTML files**: Compacts HTML structure, extracts titles via *BeautifulSoup*, and converts body content to clean text using *html2text* with enhanced CJK character handling
   * **PDF files**: Reads pre-converted TXT files from Word document sources that generated the PDFs
   * **Text processing**: Removes control characters, normalizes Unicode (NFKC), handles bidirectional text spacing, and collapses excessive whitespace
3. Runs language-aware word counting (smart algorithms for Chinese/Japanese/Korean vs. space-separated languages) and assigns domain labels based on file paths
4. Generates:
   * `ai-culture.jsonl.gz` – DOLMA-compatible newline-delimited JSON
   * `ai-culture.json` – one compact record per article
   * `ai-culture.csv` – parallel text pairs with metadata
5. Runs multi-layer integrity validation including dataset loading, structure verification, and sample inspection across all formats. Includes supplementary datasets library compatibility tests for Hugging Face Hub integration

All scripts include a **zero-duplicate** guarantee. We maintain **machine-validated alignment** between languages.
