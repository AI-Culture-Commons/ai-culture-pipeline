import json
import gzip
import hashlib
import re, html, unicodedata, html2text
import subprocess
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime, timezone

class DatasetCreator:
    """Creates Dolma-format multilingual dataset from HTML and PDF files (converted to TXT)."""
    
    def __init__(self, debug=False):
        self.debug = debug
        self.hebrew_to_english_paths = {
            "actualia": "alternative-commentary",
            "tarbut-vesifrut": "culture&literature",
            "filosofia": "philosophy-of-learning",
            "igul-shachor": "night-life",
            "bikoret-haaretz": "press-review",
            "tzurat-atid": "future-tense",
            "handasat-enosh": "human-engineering",
            "acharrit-halelot": "end-of-nights",
            "hapostim-shel-hashavua": "posts-of-the-week"
        }
        
        # Updated category mapping
        self.domain_mapping = {
            "actualia": "commentary",
            "hapostim-shel-hashavua": "commentary", 
            "tarbut-vesifrut": "culture",
            "filosofia": "philosophy",
            "bikoret-haaretz": "press-review",
            "igul-shachor": "literature",
            "tzurat-atid": "literature", 
            "handasat-enosh": "literature",
            "acharit-halelot": "literature",
            "pdf": "literature"
        }
        
        self.languages = ["he", "en", "es", "fr", "de", "pt", "it", "ja", "ru", "ko", "zh", "hi"]
        
        # Debug samples
        self.debug_samples = {"html": [], "pdf": []}

    def get_domain(self, file_path, source_format, lang):
        """Determine category by filename or directory."""
        if source_format == 'pdf':
            return "literature"
        
        path_str = str(file_path).lower()
        
        if lang == "he":
            # Hebrew - search by Hebrew names
            for hebrew_name, domain in self.domain_mapping.items():
                if hebrew_name != "pdf" and hebrew_name in path_str:
                    return domain
        else:
            # Translations - search by English names
            for hebrew_name, english_name in self.hebrew_to_english_paths.items():
                if english_name in path_str:
                    return self.domain_mapping.get(hebrew_name, "general")
        
        return "general"

    def count_words_smart(self, text, lang):
        """Smart word counting by language."""
        if not text:
            return 0
        
        # Asian languages without spaces
        if lang in ['zh', 'ja']:
            # Chinese and Japanese - count non-space/punctuation chars and divide by 2.5
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text))
            other_words = len(re.findall(r'[a-zA-Z]+', text))  # Latin words
            return int(chinese_chars / 2.5) + other_words
        
        elif lang == 'ko':
            # Korean - count hangul blocks and divide by 2
            korean_chars = len(re.findall(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', text))
            other_words = len(re.findall(r'[a-zA-Z]+', text))
            return int(korean_chars / 2) + other_words
        
        else:
            # Languages with spaces - regular counting
            words = text.split()
            return len([w for w in words if w.strip()])

    def clean_control_chars(self, text):
        """Remove control characters that break JSON."""
        if not text:
            return text
        # Strip UTF-8/UTF-16 BOM if it sneaked in
        text = text.lstrip('\ufeff')        
        # Remove control chars 0x00-0x1F except tab(0x09), LF(0x0A), CR(0x0D)
        # Keep regular spaces and newlines
        control_chars = {i: None for i in range(0x00, 0x20)}
        # Keep tab, LF, CR
        del control_chars[0x09]  # tab
        del control_chars[0x0A]  # line feed
        del control_chars[0x0D]  # carriage return
        
        return text.translate(control_chars)

    def compact_html(self, raw):
        """
        Shrink raw HTML

        • Collapses \n \r \t and double-spaces outside tags  
        • Drops gaps such as '>  <' **and** ' </span>' / '<span> '  
        • Keeps the exact bytes of <script>, and anything inside tags
        """
        out, in_tag, protect = [], False, False
        i, n = 0, len(raw)

        while i < n:
            ch = raw[i]
            if ch == "<":
                tag = raw[i:i+10].lower()
                if tag.startswith("<script"):
                    protect = True
                elif tag.startswith("</script"):
                    protect = False
                in_tag = True
                out.append(ch)

            elif ch == ">":
                in_tag = False
                out.append(ch)

            else:
                if in_tag or protect:                     # inside tag or protected block
                    out.append(ch)
                else:                                     # normal text
                    out.append(" " if ch in "\n\r\t" else ch)
            i += 1

        s = "".join(out)
        # 1) remove whitespace between consecutive tags
        s = re.sub(r">\s+<", "><", s)
        # 2) remove whitespace right *before* a tag boundary
        s = re.sub(r"\s+<", "<", s)
        # 3) remove whitespace right *after* a tag boundary
        s = re.sub(r">\s+", ">", s)
        # 4) final collapse of multiple spaces
        return re.sub(r" {2,}", " ", s).strip()
    
    def extract_content(self, html_content):
        """
        Extract HTML content (supporting 12 website languages) and return:
            title – page title
            text  – "flat" body text for model training/management
        """
        
        # Enhanced CJK range - includes extended characters and punctuation
        CJK_RANGE = (r"\u4E00-\u9FFF"      # CJK Unified Ideographs  
                    r"\u3040-\u30FF"      # Hiragana + Katakana
                    r"\uAC00-\uD7AF"      # Hangul Syllables
                    r"\u3100-\u312F"      # Bopomofo (Chinese phonetic)
                    r"\uFF00-\uFFEF")     # CJK punctuation and symbols

        # 1. Title – always via BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        title = unicodedata.normalize('NFKC', html.unescape(title))

        # 2. html2text – body text extraction
        h2t = html2text.HTML2Text()
        h2t.body_width = 0            # no hard-wrap
        h2t.ignore_links = True       # anchor-text only
        h2t.ignore_images = True
        h2t.ignore_tables = True
        h2t.ignore_emphasis = True    # no **bold** / *italics*
        h2t.single_line_break = True  # <br> → \n  ,  block → \n\n
        h2t.unicode_snob = True       # handles &#xNN;
        h2t.escape_all = False
        
        # Additional cleanup settings (prevent unwanted substitutions)
        h2t.default_image_alt = ""    # Don't substitute [alt text] for images
        h2t.mark_code = False         # Don't add backticks/indentation to code blocks

        raw_text = h2t.handle(html_content)

        # 3. Post-process
        text = html.unescape(raw_text)
        text = unicodedata.normalize('NFKC', text)

        # a. Multiple spaces → single space (doesn't touch \n)
        text = re.sub(r"[ \t]{2,}", " ", text)
        # b. Spaces around newlines
        text = re.sub(r" *\n *", "\n", text)
        # c. Collapse: more than two empty lines → one empty line
        text = re.sub(r"\n{3,}", "\n\n", text)
        # d. CJK – remove spaces inserted between Chinese/Japanese/Korean characters
        text = re.sub(fr"([{CJK_RANGE}])\s+([{CJK_RANGE}])", r"\1\2", text)

        # 4. Final filtering: remove invisible comments/remnants
        text = text.strip("\n ")

        return title, text

    def extract_txt_file(self, txt_path):
        """Extract text from a pre-converted TXT file (originally PDF) and clean whitespace."""
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Clean leading and trailing whitespace (including newlines)
            text = text.strip()
            
            # Get title from filename (without extension)
            title = Path(txt_path).stem
            
            return title, text
            
        except Exception as e:
            if self.debug:
                print(f"Error reading converted PDF file {txt_path}: {e}")
            return None, None

    def process_file(self, file_path, lang, base_path):
        """Process single file."""
        # Determine file type
        if file_path.suffix == '.html':
            source_format = 'html'
        elif file_path.suffix == '.txt':
            # Check if this TXT file is from pdf directory (converted PDF)
            if 'pdf' in str(file_path.parent):
                source_format = 'pdf'  # Treat as PDF for metadata
            else:
                source_format = 'txt'
        else:
            return None
            
        # Extract content
        html_raw = None  # only for HTML
        try:
            if source_format == 'html':
                with open(file_path, 'r', encoding='utf-8') as f:
                    html_raw = self.compact_html(f.read())  # save raw HTML
                    
                if 'Read complete version in English' in html_raw or '.partial.html' in str(file_path):
                    return None
                    
                title, extracted_content = self.extract_content(html_raw)
            else:  # TXT (converted from PDF)
                title, extracted_content = self.extract_txt_file(file_path)
                if title is None or extracted_content is None:
                    return None
            
            if not extracted_content.strip():
                return None
                
        except Exception as e:
            if self.debug:
                print(f"Error processing {file_path}: {e}")
            return None
            
        # Clean control chars before creating record
        title = self.clean_control_chars(title)
        extracted_content = self.clean_control_chars(extracted_content)
        if html_raw:
            html_raw = self.clean_control_chars(html_raw)
            
        # Create unique ID
        if lang == "he":
            if source_format == 'pdf':  # TXT files converted from PDF
                # Change .txt extension to .pdf for ID
                filename_with_pdf_ext = file_path.stem + '.pdf'
                file_id = f"he/{filename_with_pdf_ext}"
            else:
                file_id = f"he/{file_path.name}"
        else:
            file_id = file_path.relative_to(base_path).as_posix()
        
        # URLs
        original_filename = file_path.name
        if lang != "he":
            for heb, eng in self.hebrew_to_english_paths.items():
                original_filename = original_filename.replace(eng, heb)
        
        if lang == "he":
            if source_format == 'pdf':  # TXT files converted from PDF
                # Use PDF extension in original URL
                original_filename_pdf = file_path.stem + '.pdf'
                original_url = f"https://hitdarderut-haaretz.org/{original_filename_pdf}"
            else:
                original_url = f"https://hitdarderut-haaretz.org/{original_filename}"
            url = original_url
        else:
            original_url = f"https://hitdarderut-haaretz.org/{original_filename}"
            url = f"https://degeneration-of-nation.org/{file_path.relative_to(base_path).as_posix()}"
        
        # Calculate fields - with smart word counting
        wc = self.count_words_smart(extracted_content, lang)
        char_count = len(extracted_content)
        checksum = hashlib.sha256(extracted_content.encode('utf-8')).hexdigest()
        domain = self.get_domain(file_path, source_format, lang)
        
        # Dolma document
        metadata = {
            "language": lang,
            "title": title,
            "url": url,
            "translation_of": original_url if lang != "he" else None,
            "source_format": source_format,
            "domain": domain,
            "license": "CC-BY-4.0",
            "word_count": wc,
            "char_count": char_count,
            "sha256": checksum,
            "html_raw": html_raw,
        }
        
        doc = {
            "id": file_id,
            "text": extracted_content,
            "source": "hitdarderut-haaretz" if lang == "he" else "degeneration-of-nation",
            "metadata": metadata,
            "added": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        }
        
        # Save for debug
        if self.debug:
            if source_format == 'pdf':
                self.debug_samples["pdf"].append(doc)
            else:
                self.debug_samples["html"].append(doc)
        
        return doc

    def create_dataset(self, base_dir):
        """Create the dataset."""
        base_path = Path(base_dir)
        articles = []
        
        for lang in tqdm(self.languages, desc="Processing languages"):
            current_path = base_path if lang == "he" else base_path / lang
            if not current_path.exists():
                continue
                
            # Count files
            html_files = list(current_path.glob('*.html'))
            txt_files = []
            
            # For Hebrew, also look for TXT files in pdf directory (parallel to base_dir)
            if lang == "he":
                pdf_dir = base_path.parent / "pdf"
                if pdf_dir.exists():
                    txt_files = list(pdf_dir.glob('*.txt'))
            
            all_files = html_files + txt_files
            
            if not all_files:
                continue
                
            if self.debug:
                print(f"\nProcessing {lang}: {len(html_files)} HTML + {len(txt_files)} PDF files")
            
            # Process HTML
            for file_path in tqdm(html_files, desc=f"HTML {lang}", leave=False):
                article = self.process_file(file_path, lang, base_path)
                if article:
                    articles.append(article)
            
            # Process TXT (converted from PDF, Hebrew only)
            if lang == "he" and txt_files:
                for txt_path in tqdm(txt_files, desc=f"PDF {lang}", leave=False):
                    article = self.process_file(txt_path, lang, base_path)
                    if article:
                        articles.append(article)
        
        return articles

    def validate_jsonl(self, filename):
        """Basic JSONL validation."""
        if self.debug:
            print(f"\nBasic validation of {filename}...")
        
        try:
            with gzip.open(filename, 'rt', encoding='utf-8') as f:
                lines = f.readlines()
                
            total_lines = len(lines)
            check_lines = min(10, total_lines)
            
            if self.debug:
                print(f"Checking first {check_lines} lines...")
            
            for i, line in enumerate(lines[:check_lines], 1):
                try:
                    json.loads(line.strip())
                except json.JSONDecodeError as e:
                    if self.debug:
                        print(f"Line {i}: JSON error")
                    return False
            
            if self.debug:
                print(f"All {check_lines} lines are valid.")
                print(f"Total lines in file: {total_lines}")
            return True
                
        except Exception as e:
            print(f"Error reading file: {e}")
            return False

    def run_external_validations(self, filename):
        """Run external quick validations on entire file."""
        print(f"\nRunning external validations on {filename}...")
        
        tests_passed = 0
        total_tests = 2
        
        # Test 1: valid JSON on entire file
        if self.debug:
            print("\n1. Checking JSON validity on entire file...")
        try:
            json_test_script = f'''
import gzip, json, sys
errors = 0
total = 0
with gzip.open('{filename}','rt',encoding='utf-8') as f:
    for line_num, line in enumerate(f, 1):
        try: 
            json.loads(line.strip())
            total += 1
        except Exception as e:
            errors += 1
            if errors <= 5:  # show first 5 errors
                print(f'X line {{line_num}}: {{e}}', file=sys.stderr)
        if line_num % 1000 == 0:  # progress report
            print(f'Checked {{line_num}} lines...', file=sys.stderr)

if errors == 0:
    print(f'All {{total}} lines are valid JSON')
else:
    print(f'Found {{errors}} JSON errors out of {{total}} lines', file=sys.stderr)
    sys.exit(1)
'''
            result = subprocess.run(['python3', '-c', json_test_script], 
                                  capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                if self.debug:
                    print(f"{result.stdout.strip()}")
                tests_passed += 1
            else:
                print(f"JSON problems found:")
                print(result.stderr)
        except Exception as e:
            print(f"JSON test error: {e}")
        
        # Test 2: datasets can load
        if self.debug:
            print("\n2. Checking datasets library loading...")
        try:
            datasets_test_script = f'''
try:
    from datasets import load_dataset
    dataset = load_dataset('json', data_files='{filename}', split='train', streaming=True)
    # count actual rows
    count = sum(1 for _ in dataset.take(10))  # check first 10 records
    print(f'datasets loaded and read {{count}} sample records')
except ImportError:
    print('datasets library not installed - install with: pip install datasets')
except Exception as e:
    print(f'datasets error: {{e}}')
'''
            result = subprocess.run(['python3', '-c', datasets_test_script], 
                                  capture_output=True, text=True, timeout=60)
            if 'datasets loaded' in result.stdout:
                if self.debug:
                    print(f"{result.stdout.strip()}")
                tests_passed += 1
            elif 'datasets library not installed' in result.stdout:
                print("datasets not installed - install: pip install datasets")
            else:
                print(f"datasets cannot load: {result.stdout}{result.stderr}")
        except Exception as e:
            if self.debug:
                print(f"datasets test error: {e}")
        
        # Summary
        if self.debug:
            print(f"\nExternal validation results:")
            print(f"Passed: {tests_passed:.0f}/{total_tests} tests")
        
        if tests_passed >= 2:
            return True
        return False

    def print_debug_info(self, dataset):
        """Display debug info - first and last only, 150 chars."""
        if not self.debug:
            return
            
        print("\n" + "="*80)
        print("DEBUG INFO - Dolma Data Structure")
        print("="*80)
        
        def print_sample(sample, sample_type, index, position=""):
            print(f"\n--- {sample_type} #{index} {position}---")
            print("JSON structure:")
            
            # ID, Source, Added
            print(f"ID: {sample['id']}")
            print(f"Source: {sample['source']}")
            print(f"Added: {sample['added']}")
            # Text (up to N chars)
            text = sample['text']
            if len(text) > 150:
                text_preview = text[:150] + "..."
            else:
                text_preview = text
            
            # Display clearly
            print(f"Text: {text_preview}")

            # Metadata
            print("Metadata:")
            for key, value in sample['metadata'].items():
                if isinstance(value, str) and len(value) > 150:
                    value = value[:150] + "..."
                print(f"  {key}: {value}")
        
        # Show samples
        for format_type in ['html', 'pdf']:
            all_samples = self.debug_samples[format_type]
            if not all_samples:
                continue
                
            print(f"\n{format_type.upper()} Samples (out of {len(all_samples)} records):")
            
            # Show every 400th sample
            step = 400
            for i in range(0, len(all_samples), step):
                sample_index = i + 1
                print_sample(all_samples[i], format_type.upper(), sample_index, f"(sample #{sample_index})")
            
            # Always show the last sample if not already shown
            if len(all_samples) > 1 and (len(all_samples) - 1) % step != 0:
                print_sample(all_samples[-1], format_type.upper(), len(all_samples), "(final)")
        
        print("\n" + "="*80)

def main():
    parser = argparse.ArgumentParser(description='Create AI Culture multilingual Dolma-format dataset')
    parser.add_argument('--input-dir', default='website2', help='Input directory (default: website2)')
    parser.add_argument('--output', default='ai-culture.jsonl.gz', help='Output file (default: ai-culture.jsonl.gz)')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    
    args = parser.parse_args()
    
    creator = DatasetCreator(debug=args.debug)
    dataset = creator.create_dataset(args.input_dir)
    
    # Show debug info
    creator.print_debug_info(dataset)
    
    # Safe writing to JSONL with control char cleaning
    print(f"\nWriting {len(dataset)} documents to Dolma JSONL format...")
    
    with gzip.open(args.output, 'wt', encoding='utf-8') as out:
        for doc in tqdm(dataset, desc="Writing JSONL"):
            # Ensure no control chars in text again
            if 'text' in doc:
                doc['text'] = creator.clean_control_chars(doc['text'])
            if 'title' in doc.get('metadata', {}):
                doc['metadata']['title'] = creator.clean_control_chars(doc['metadata']['title'])
                
            json.dump(doc, out, ensure_ascii=False)
            out.write('\n')
    
    print(f"Successfully wrote {len(dataset)} documents")
    
    # Statistics
    total_words = sum(d['metadata']['word_count'] for d in dataset)
    total_chars = sum(d['metadata']['char_count'] for d in dataset)
    languages_count = {}
    languages_words = {}
    format_count = {}
    domain_count = {}
    
    for doc in dataset:
        lang = doc['metadata']['language']
        fmt = doc['metadata']['source_format']
        domain = doc['metadata']['domain']
        word_count = doc['metadata']['word_count']
        
        languages_count[lang] = languages_count.get(lang, 0) + 1
        languages_words[lang] = languages_words.get(lang, 0) + word_count
        format_count[fmt] = format_count.get(fmt, 0) + 1
        domain_count[domain] = domain_count.get(domain, 0) + 1
    
    print(f"\nDataset Statistics:")
    print(f"Total documents: {len(dataset)}")
    print(f"Total words: {total_words:,}")
    print(f"Total characters: {total_chars:,}")
    print(f"Documents per language: {dict(sorted(languages_count.items()))}")
    print(f"Words per language: {dict(sorted({k: f'{v:,}' for k, v in languages_words.items()}.items()))}")
    print(f"Formats: {format_count}")
    print(f"Domains: {dict(sorted(domain_count.items()))}")
    print(f"Output: {args.output}")
    
    if Path(args.output).exists():
        print(f"Size: {Path(args.output).stat().st_size / 1024 / 1024:.1f} MB")
    
    # External validation tests
    print(f"\nRunning validation tests...")
    
    # Run comprehensive external tests
    all_tests_passed = creator.run_external_validations(args.output)
    
    if all_tests_passed:
        print(f"\nAll tests passed successfully. JSONL dataset is ready for use.")
    else:
        print(f"\nSome issues found - see tests above")

if __name__ == "__main__":
    main()