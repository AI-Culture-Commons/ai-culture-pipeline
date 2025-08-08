import json
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
import re, html, unicodedata, html2text

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

    def process_file(self, file_path, lang):
        """Process single file and convert to required format."""
        if file_path.suffix != '.html':
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = self.compact_html(f.read())

        if lang == "he":
            content = content.replace('<html dir="ltr" lang="">', '<html dir="rtl" lang="he">')

        # Skip partial translations files
        if 'Read complete version in English' in content or '.partial.html' in str(file_path):
            return None
            
        # Create file identifier
        relative_path = file_path.name[:-5]
        file_id = f"{lang}/{relative_path}"
        if relative_path.endswith("index"):
            relative_path = ""
            print("Language: " + lang)

        # Convert English path to Hebrew if needed
        original_path = relative_path
        if lang != "he":
            for heb, eng in self.hebrew_to_english_paths.items():
                original_path = original_path.replace(eng, heb)

        # Generate URLs
        original_url = f"https://hitdarderut-haaretz.org/{original_path}"
        url = original_url if lang == "he" else f"https://degeneration-of-nation.org/{lang}/{relative_path}"
        
        title, extracted_content = self.extract_content(content)
        
        # Clean control characters that can break JSON
        title = self.clean_control_chars(title)
        extracted_content = self.clean_control_chars(extracted_content)
        content = self.clean_control_chars(content)
        
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