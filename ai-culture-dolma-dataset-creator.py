import json
import gzip
import hashlib
import re
import subprocess
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime, timezone

class DatasetCreator:
    """Creates Dolma-format multilingual dataset from HTML and PDF files."""
    
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

    def clean_control_chars(self, text):
        """Remove control characters that break JSON."""
        if not text:
            return text
        
        # Remove control chars 0x00-0x1F except tab(0x09), LF(0x0A), CR(0x0D)
        # Keep regular spaces and newlines
        control_chars = {i: None for i in range(0x00, 0x20)}
        # Keep tab, LF, CR
        del control_chars[0x09]  # tab
        del control_chars[0x0A]  # line feed
        del control_chars[0x0D]  # carriage return
        
        return text.translate(control_chars)

    def get_domain(self, file_path, source_format, lang):
        """Determine category by filename or directory."""
        if source_format == 'pdf':
            return "literature"
        
        filename = file_path.stem.lower()
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

    def extract_content(self, html_content):
        """Extract title and content from HTML file - preserve text structure."""
        soup = BeautifulSoup(html_content, 'html.parser')
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        content = soup.get_text(separator='\n\n', strip=True)
        return title, content

    def extract_pdf(self, pdf_path):
        """Extract text from PDF with Hebrew fixes."""
        import fitz
        
        doc = fitz.open(pdf_path)
        text_parts = []
        
        for page in doc:
            page_text = page.get_text()
            if page_text.strip():
                text_parts.append(page_text)
        
        doc.close()
        text = '\n'.join(text_parts)
        
        # Fix Hebrew if needed
        if text and self._has_hebrew(text) and self._looks_reversed(text):
            text = self._fix_hebrew_bidi(text)
            
        title = Path(pdf_path).stem
        return title, text

    def _has_hebrew(self, text):
        """Check if text contains Hebrew."""
        return any(0x0590 <= ord(c) <= 0x05FF for c in text[:200])

    def _looks_reversed(self, text):
        """Check if text looks reversed."""
        words = text.split()[:20]
        hebrew_words = [w for w in words if any(0x0590 <= ord(c) <= 0x05FF for c in w)]
        english_words = [w for w in words if w.isascii() and w.isalpha()]
        return len(hebrew_words) > 0 and len(english_words) > 0

    def _fix_hebrew_bidi(self, text):
        """Fix with bidi algorithm."""
        try:
            from bidi.algorithm import get_display
            lines = text.splitlines()
            fixed_lines = []
            
            for line in lines:
                if self._has_hebrew(line):
                    fixed_line = get_display(line)
                    fixed_lines.append(fixed_line)
                else:
                    fixed_lines.append(line)
            
            return '\n'.join(fixed_lines)
            
        except ImportError:
            if self.debug:
                print("Warning: python-bidi not installed - returning original text")
            return text

    def process_file(self, file_path, lang, base_path):
        """Process single file."""
        # Determine file type
        if file_path.suffix == '.html':
            source_format = 'html'
        elif file_path.suffix == '.pdf':
            source_format = 'pdf'
        else:
            return None
            
        # Extract content
        html_raw = None  # only for HTML
        try:
            if source_format == 'html':
                with open(file_path, 'r', encoding='utf-8') as f:
                    html_raw = f.read()  # save raw HTML
                    
                if 'Read complete version in English' in html_raw or '.partial.html' in str(file_path):
                    return None
                    
                title, extracted_content = self.extract_content(html_raw)
            else:  # PDF
                title, extracted_content = self.extract_pdf(file_path)
            
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
            file_id = f"he/{file_path.name}"
        else:
            file_id = file_path.relative_to(base_path).as_posix()
        
        # URLs
        original_filename = file_path.name
        if lang != "he":
            for heb, eng in self.hebrew_to_english_paths.items():
                original_filename = original_filename.replace(eng, heb)
        
        if lang == "he":
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
            self.debug_samples[source_format].append(doc)
        
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
            pdf_files = list(current_path.glob('*.pdf')) if lang == "he" else []
            all_files = html_files + pdf_files
            
            if not all_files:
                continue
                
            if self.debug:
                print(f"\nProcessing {lang}: {len(all_files)} files")
            
            # Process HTML
            for file_path in tqdm(html_files, desc=f"HTML {lang}", leave=False):
                article = self.process_file(file_path, lang, base_path)
                if article:
                    articles.append(article)
            
            # Process PDF (Hebrew only)
            if lang == "he" and pdf_files:
                for pdf_path in tqdm(pdf_files, desc=f"PDF {lang}", leave=False):
                    article = self.process_file(pdf_path, lang, base_path)
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
        total_tests = 3
        
        # Test 1: valid gzip
        if self.debug:
            print("\n1. Checking gzip integrity...")
        try:
            result = subprocess.run(['gzip', '-t', filename], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                if self.debug:
                    print("gzip file is valid")
                tests_passed += 1
            else:
                print(f"gzip file is corrupt: {result.stderr}")
        except Exception as e:
            print(f"gzip test error: {e}")
        
        # Test 2: valid JSON on entire file
        if self.debug:
            print("\n2. Checking JSON validity on entire file...")
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
        
        # Test 3: datasets can load
        if self.debug:
            print("\n3. Checking datasets library loading...")
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
        
        if tests_passed >= 3:
            return True
        else:
            print("Some issues found - check errors above")
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
            # Text (up to 150 chars)
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
        
        # Show samples - only first and last
        for format_type in ['html', 'pdf']:
            all_samples = self.debug_samples[format_type]
            if not all_samples:
                continue
                
            print(f"\n{format_type.upper()} Samples (out of {len(all_samples)} records):")
            
            # First
            if len(all_samples) > 0:
                print_sample(all_samples[0], format_type.upper(), 1, "(first)")
            
            # Last (if more than 1)
            if len(all_samples) > 1:
                print_sample(all_samples[-1], format_type.upper(), len(all_samples), "(last)")
        
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