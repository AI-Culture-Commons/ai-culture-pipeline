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

    def extract_content(self, html_content):
        """
        Extract title and clean text from HTML content.
        
        Args:
            html_content (str): Full HTML content
            
        Returns:
            tuple: (title, clean text)
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        title = soup.title.string.strip() if soup.title else ""
        content = soup.get_text(separator='\n\n', strip=True)
        return title, content

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
        return hebrew_name, content, self.extract_content(content)[1]

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
                            translated_html = f.read()
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
                    
                    # Extract translated text
                    _, translated_text = self.extract_content(translated_html)
                    
                    # Create file identifier and section name
                    article_code = file_path.stem
                    section_name = "main"  # default
                    for heb, eng in self.hebrew_to_english_paths.items():
                        if eng in str(file_path):
                            section_name = eng
                            break
                    
                    # Create URLs
                    source_url = f"https://hitdarderut-haaretz.org/{hebrew_name}"
                    translated_url = f"https://degeneration-of-nation.org/{lang}/{file_path.name}"
                    
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

def main():
    parser = argparse.ArgumentParser(description='Create AI Culture multilingual CSV dataset')
    parser.add_argument('--input-dir', default='website2', help='Input directory (default: website2)')
    parser.add_argument('--output', default='ai-culture.csv', help='Output file (default: ai-culture.csv)')
    
    args = parser.parse_args()
    
    creator = DatasetCreator()
    creator.create_csv_dataset(args.input_dir, args.output)

if __name__ == "__main__":
    main()