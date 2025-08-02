import json
import argparse
from pathlib import Path
from bs4 import BeautifulSoup

class DatasetCreator:
    """Creates multilingual dataset from HTML files with Hebrew-English path mapping."""
    
    def __init__(self):
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
        
        self.languages = ["he", "en", "es", "fr", "de", "pt", "it", "ja", "ru", "ko", "zh", "hi"]

    def extract_content(self, html_content):
        """Extract title and content from HTML file."""
        soup = BeautifulSoup(html_content, 'html.parser')
        title = soup.title.string.strip() if soup.title else ""
        content = soup.get_text(separator='\n\n', strip=True)
        return title, content

    def process_file(self, file_path, lang):
        """Process single file and convert to required format."""
        if file_path.suffix != '.html':
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Skip partial or English-only files
        if 'Read complete version in English' in content or '.partial.html' in str(file_path):
            return None
            
        # Create file identifier
        relative_path = file_path.name
        file_id = f"{lang}/{relative_path}"
        
        # Convert English path to Hebrew if needed
        original_path = relative_path
        if lang != "he":
            for heb, eng in self.hebrew_to_english_paths.items():
                original_path = original_path.replace(eng, heb)
        
        # Generate URLs
        original_url = f"https://hitdarderut-haaretz.org/{original_path}"
        url = original_url if lang == "he" else f"https://degeneration-of-nation.org/{file_id}"
        
        title, extracted_content = self.extract_content(content)
        
        return {
            "id": file_id,
            "language": lang,
            "title": title,
            "content": extracted_content,
            "html": content,
            "url": url,
            "original_url": original_url
        }

    def create_dataset(self, base_dir):
        """Create complete dataset from all languages."""
        base_path = Path(base_dir)
        articles = []
        
        # Process all languages including Hebrew
        for lang in self.languages:
            # Hebrew files are in root directory
            current_path = base_path if lang == "he" else base_path / lang
            if not current_path.exists():
                print(f"Directory not found: {current_path}")
                continue
                
            for file_path in current_path.glob('*.html'):
                article = self.process_file(file_path, lang)
                if article:
                    articles.append(article)
        
        return articles

def main():
    parser = argparse.ArgumentParser(description='Create AI Culture multilingual dataset')
    parser.add_argument('--input-dir', default='website2', help='Input directory (default: website2)')
    parser.add_argument('--output', default='ai-culture.json', help='Output file (default: ai-culture.json)')
    
    args = parser.parse_args()
    
    creator = DatasetCreator()
    dataset = creator.create_dataset(args.input_dir)
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    
    print(f"Created dataset with {len(dataset)} articles")

if __name__ == "__main__":
    main()