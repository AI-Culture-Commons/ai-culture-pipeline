# ai-culture-pipeline
## AI-Culture Commons Datasets Pipeline

Our [datasets](https://degeneration-of-nation.org/dataset) are created with an **open-source pipeline** that:

1. Processes files from local project directories (no web crawling required)
2. Extracts plain text via *BeautifulSoup* or *PyMuPDF* (for PDF files)
3. Runs language-aware word counting and assigns domain labels
4. Generates:
   * `ai-culture.jsonl.gz` – DOLMA-compatible newline-delimited JSON
   * `ai-culture.json` – one compact record per article
   * `ai-culture.csv` – parallel text pairs with metadata
5. Performs integrity checks

All scripts include a **zero-duplicate** guarantee. We maintain **machine-validated alignment** between languages.
