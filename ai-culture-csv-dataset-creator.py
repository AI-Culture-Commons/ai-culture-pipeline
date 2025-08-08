#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CSV Dataset Creator

Creates CSV version of multilingual dataset.
Takes original website files and generates parallel CSV file
containing original and translated texts with their metadata.
"""

import csv
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
import re, html, unicodedata, html2text

class DatasetCreator:
    """Creates CSV format multilingual dataset from HTML files."""
    
    def __init__(self):
        # Mapping between Hebrew and English section names
        self.hebrew_to_english_paths = {
            "actualia": "alternative-commentary",
            "tarbut-vesifrut": "culture&literature",
            "filosofia": "philosophy-of-learning",
            "igul-shachor": "night-life",
            "bikoret-haaretz": "press-review",
            "tzurat-atid": "future-tense",
            "handasat-enosh": "human-engineering",
            "acharit-halelot": "end-of-nights",
            "hapostim-shel-hashavua": "posts-of-the-week"
        }
        
        # List of languages to process (excluding Hebrew as source language)
        self.languages = ["en", "es", "fr", "de", "pt", "it", "ja", "ru", "ko", "zh", "hi"]

    def clean_control_chars(self, text):
        """Remove control characters that break CSV."""
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
        
        return text.translate(control_chars).strip()

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

        # Add line break between divs for proper paragraph spacing
        html_content = re.sub(r'</div>', '</div><br>', html_content)

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

        return title, text

    def get_hebrew_content(self, file_name, base_dir):
        """
        Find and extract corresponding Hebrew content for foreign language file.
        
        Args:
            file_name (str): Foreign language file name
            base_dir (Path): Website base directory
            
        Returns:
            tuple: (Hebrew file name, Hebrew HTML content, Hebrew clean text)
            or (None, None, None) if no corresponding file found
        """
        hebrew_name = file_name
        for eng, heb in self.hebrew_to_english_paths.items():
            hebrew_name = hebrew_name.replace(heb, eng)
        
        hebrew_path = Path(base_dir) / hebrew_name
        if not hebrew_path.exists():
            return None, None, None
            
        with open(hebrew_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Apply same processing as other formats
        content = self.compact_html(content)
        content = content.replace('<html dir="ltr" lang="">', '<html dir="rtl" lang="he">')
        _, clean_text = self.extract_content(content)
        
        return hebrew_name, content, clean_text

    def validate_csv(self, csv_file):
        """Basic validation and statistics for the created CSV file."""
        print(f"\nValidating CSV file...")
        
        try:
            # Increase CSV field size limit for large HTML content
            csv.field_size_limit(1000000)  # 1MB limit instead of default 131KB
            
            # Basic validation with standard csv module
            with open(csv_file, 'r', encoding='utf-8', newline='') as f:
                reader = csv.reader(f, quoting=csv.QUOTE_NONNUMERIC)
                header = next(reader)
                rows = list(reader)
            
            print(f"CSV validation successful")
            print(f"Rows: {len(rows)}, Columns: {len(header)}")
            
            # Optional: Enhanced statistics with pandas if available
            try:
                import pandas as pd
                df = pd.read_csv(csv_file)
                print(f"Languages: {sorted(df['target_lang'].unique())}")
                print(f"Sections: {sorted(df['section_name'].unique())}")
            except ImportError:
                print("Install pandas for detailed statistics: pip install pandas")
                
            return True
                
        except Exception as e:
            print(f"CSV validation failed: {e}")
            return False

    def create_csv_dataset(self, base_dir, output_file='ai-culture.csv'):
        """
        Create CSV dataset file.
        
        Args:
            base_dir (str): Path to website base directory
            output_file (str): Output file name (default: ai-culture.csv)
        """
        base_path = Path(base_dir)
        rows_created = 0
        
        with open(output_file, 'w', encoding='utf-8', newline='') as csvfile:
            writer = csv.writer(csvfile, quoting=csv.QUOTE_NONNUMERIC)
            
            # Write column headers
            writer.writerow([
                'article_code', 'source_lang', 'target_lang', 'section_name',
                'source_text', 'translated_text', 'source_html', 'translated_html',
                'source_url', 'translated_url'
            ])
            
            # Process all languages
            for lang in self.languages:
                current_path = base_path / lang
                if not current_path.exists():
                    print(f"Warning: Directory for language {lang} not found")
                    continue
                    
                for file_path in current_path.glob('*.html'):
                    # Skip partial files
                    if '.partial.html' in str(file_path):
                        continue
                        
                    # Read translated file
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            translated_html = self.compact_html(f.read())
                    except Exception as e:
                        print(f"Error reading file {file_path}: {e}")
                        continue
                    
                    # Skip partial files (additional content check)
                    if 'Read complete version in English' in translated_html:
                        continue
                    
                    # Find corresponding Hebrew content
                    hebrew_name, source_html, source_text = self.get_hebrew_content(file_path.name, base_path)
                    if not source_html:
                        print(f"Warning: No Hebrew content found for {file_path.name}")
                        continue
                    
                    # Extract translated text using advanced processing
                    _, translated_text = self.extract_content(translated_html)
                    
                    # Clean control characters for all text fields
                    source_text = self.clean_control_chars(source_text)
                    translated_text = self.clean_control_chars(translated_text)
                    source_html = self.clean_control_chars(source_html)
                    translated_html = self.clean_control_chars(translated_html)
                    
                    # Create file identifier and section name
                    article_code = file_path.stem
                    section_name = "main"  # default
                    for heb, eng in self.hebrew_to_english_paths.items():
                        if eng in str(file_path):
                            section_name = eng
                            break
                    
                    # Create URLs
                    source_url = f"https://hitdarderut-haaretz.org/{'' if hebrew_name.endswith('index.html') else hebrew_name[:-5]}"
                    translated_url = f"https://degeneration-of-nation.org/{lang}/{'' if article_code.endswith('index') else article_code}"
                    
                    # Write row
                    writer.writerow([
                        article_code,
                        'he',
                        lang,
                        section_name,
                        source_text,
                        translated_text,
                        source_html,
                        translated_html,
                        source_url,
                        translated_url
                    ])
                    
                    rows_created += 1
                    
                    # Progress update every 1000 rows
                    if rows_created % 1000 == 0:
                        print(f"Created {rows_created} rows...")
        
        print(f"\nFinished! Created {rows_created} rows in {output_file}")
        
        self.validate_csv(output_file)

def main():
    parser = argparse.ArgumentParser(description='Create AI Culture multilingual CSV dataset')
    parser.add_argument('--input-dir', default='website2', help='Input directory (default: website2)')
    parser.add_argument('--output', default='ai-culture.csv', help='Output file (default: ai-culture.csv)')
    
    args = parser.parse_args()
    
    creator = DatasetCreator()
    creator.create_csv_dataset(args.input_dir, args.output)

if __name__ == "__main__":
    main()