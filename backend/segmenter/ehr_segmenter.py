import pdfplumber
import pandas as pd
from datetime import datetime
from fuzzywuzzy import fuzz
import re
from typing import Dict, List, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EHRSegmenter:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pages_data = []
        self.current_record = None
        self.parent_key_counter = 100000  # Starting point for parent keys
        self.category_keywords = {
            24: ['LABORATORY', 'LAB REPORT', 'LAB TEST', 'LABS', 'LABORATORY REPORT'],
            16: ['PROGRESS', 'CLINICAL NOTE', 'CONSULTATION', 'PROGRESS NOTE', 'CLINICAL'],
            17: ['DISCHARGE', 'DISCHARGE SUMMARY'],
            18: ['CONSULTATION', 'CONSULT'],
            19: ['OPERATIVE', 'SURGICAL', 'SURGERY'],
            20: ['RADIOLOGY', 'X-RAY', 'IMAGING'],
            21: ['PATHOLOGY', 'PATH'],
            22: ['EMERGENCY', 'ER', 'ED'],
            23: ['PHARMACY', 'MEDICATION', 'PRESCRIPTION']
        }
        
    def _normalize_header(self, header: str) -> str:
        """Normalize header by removing continuation markers and standardizing format."""
        if not header:
            return ""
        # Remove continuation markers
        header = re.sub(r'\s*\(continued\)', '', header, flags=re.IGNORECASE)
        header = re.sub(r'\s*\(cont\.\)', '', header, flags=re.IGNORECASE)
        # Standardize common variations
        header = re.sub(r'^LABS?\b', 'LABORATORY', header, flags=re.IGNORECASE)
        header = re.sub(r'^PROG\.?\s*NOTE', 'PROGRESS NOTE', header, flags=re.IGNORECASE)
        return header.strip()

    def extract_text_from_pdf(self) -> List[Dict]:
        """Extract text and metadata from each page of the PDF."""
        prev_header = ""
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if not text:
                        continue
                        
                    # Extract header (improved logic)
                    header = self._extract_header(text, prev_header)
                    if header:
                        prev_header = header
                        header = self._normalize_header(header)
                    
                    # Extract date of service
                    dos = self._extract_dos(text)
                    
                    # Extract provider and facility (improved logic)
                    provider_facility = self._extract_provider_facility(text)
                    
                    # Determine category based on header and content
                    category = self._determine_category(header, text)
                    
                    self.pages_data.append({
                        'pagenumber': page_num,
                        'text': text,
                        'header': header,
                        'dos': dos,
                        'provider': provider_facility,
                        'category': category,
                        'isreviewable': True,
                        'parentkey': None,
                        'referencekey': None
                    })
                    
            return self.pages_data
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            raise

    def _extract_header(self, text: str, prev_header: str = "") -> str:
        """Extract header from the first 15 lines, fallback to previous header if likely continuation."""
        lines = text.split('\n')
        header_keywords = ['LABORATORY', 'PROGRESS', 'NOTE', 'REPORT', 'CLINICAL', 'CONSULTATION']
        
        # First pass: look for exact matches
        for line in lines[:15]:
            if any(keyword in line.upper() for keyword in header_keywords):
                return line.strip()
            if "(continued)" in line.lower() or "(cont.)" in line.lower():
                return line.strip()
                
        # Second pass: look for partial matches
        for line in lines[:15]:
            for keyword in header_keywords:
                if fuzz.partial_ratio(keyword, line.upper()) > 80:
                    return line.strip()
                    
        # Fallback to previous header if likely continuation
        if prev_header:
            return prev_header
            
        return ""

    def _extract_dos(self, text: str) -> str:
        """Extract date of service using regex patterns with improved fallback."""
        date_patterns = [
            r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
            r'\d{1,2}-\d{1,2}-\d{4}',  # MM-DD-YYYY
            r'\d{4}-\d{1,2}-\d{1,2}',  # YYYY-MM-DD
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}'  # Month DD, YYYY
        ]
        
        # First look for dates near the top of the page
        lines = text.split('\n')
        for line in lines[:10]:
            for pattern in date_patterns:
                matches = re.findall(pattern, line, re.IGNORECASE)
                if matches:
                    return matches[0]
                    
        # If not found, search the entire text
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0]
                
        return ""

    def _extract_provider_facility(self, text: str) -> str:
        """Extract provider and facility information using regex and keyword search."""
        lines = text.split('\n')
        for line in lines[:20]:
            match = re.search(r'(Facility|Provider|Doctor|Dr\.|Physician):\s*(.+)', line, re.IGNORECASE)
            if match:
                return match.group(2).strip()
            if 'DOCTOR' in line.upper() or 'FACILITY' in line.upper():
                return line.strip()
        return ""

    def _determine_category(self, header: str, text: str) -> int:
        """Determine the category based on header content and page text with improved detection."""
        header_upper = header.upper()
        text_upper = text.upper()
        
        # Check header first
        for category, keywords in self.category_keywords.items():
            if any(keyword in header_upper for keyword in keywords):
                return category
                
        # Check first 500 characters of text
        for category, keywords in self.category_keywords.items():
            if any(keyword in text_upper[:500] for keyword in keywords):
                return category
                
        # If still no category found, try to infer from text content
        if 'NOTE' in text_upper[:1000]:
            return 16  # Progress Note
        elif 'LAB' in text_upper[:1000]:
            return 24  # Laboratory Report
            
        logger.warning(f"Could not determine category for header: {header}")
        return None

    def group_records(self) -> List[Dict]:
        if not self.pages_data:
            return []
        current_group = []
        grouped_records = []
        for i, page in enumerate(self.pages_data):
            if not current_group:
                current_group = [page]
                continue
            if self._belongs_to_same_record(current_group[-1], page):
                current_group.append(page)
            else:
                self._process_group(current_group)
                grouped_records.extend(current_group)
                current_group = [page]
        if current_group:
            self._process_group(current_group)
            grouped_records.extend(current_group)
        return grouped_records

    def _belongs_to_same_record(self, prev_page: Dict, current_page: Dict) -> bool:
        """Determine if current page belongs to the same record as previous page with improved logic."""
        # Normalize headers for comparison
        prev_header = self._normalize_header(prev_page['header'])
        curr_header = self._normalize_header(current_page['header'])
        
        # Check header similarity
        header_similarity = fuzz.ratio(prev_header, curr_header)
        
        # Check DOS match
        dos_match = prev_page['dos'] == current_page['dos']
        
        # Check provider/facility similarity
        provider_similarity = fuzz.ratio(prev_page['provider'], current_page['provider'])
        
        # Check content continuity
        content_similarity = fuzz.ratio(prev_page['text'][-200:], current_page['text'][:200])
        
        # Check for continuation markers
        is_continuation = any(marker in current_page['header'].lower() 
                            for marker in ['(continued)', '(cont.', 'continued'])
        
        # If it's a continuation page, be more lenient with grouping
        if is_continuation:
            return (header_similarity > 70 or content_similarity > 60) and (
                dos_match or provider_similarity > 70
            )
            
        # Normal grouping logic
        return (header_similarity > 80 and (dos_match or provider_similarity > 80)) or content_similarity > 70

    def _process_group(self, group: List[Dict]):
        """Process a group of pages and assign parent/reference keys with improved metadata handling."""
        if not group:
            return
            
        parent_key = self.parent_key_counter
        self.parent_key_counter += 1
        
        # Find the most common category in the group
        categories = [p['category'] for p in group if p['category'] is not None]
        if categories:
            most_common_category = max(set(categories), key=categories.count)
        else:
            most_common_category = 0
            
        # Find the most common header
        headers = [p['header'] for p in group if p['header']]
        if headers:
            most_common_header = max(set(headers), key=headers.count)
        else:
            most_common_header = ""
            
        # Find the most common DOS
        dos_values = [p['dos'] for p in group if p['dos']]
        if dos_values:
            most_common_dos = max(set(dos_values), key=dos_values.count)
        else:
            most_common_dos = ""
            
        # Find the most common provider
        providers = [p['provider'] for p in group if p['provider']]
        if providers:
            most_common_provider = max(set(providers), key=providers.count)
        else:
            most_common_provider = ""
        
        # Update all pages in the group with consistent metadata
        for i, page in enumerate(group):
            # ReferenceKey pattern: parentkey + (i*10) + 1
            page['parentkey'] = parent_key
            page['referencekey'] = int(parent_key) + (i * 10) + 1
            
            # Forward-fill metadata if missing
            if not page['category'] or page['category'] == 0:
                # Try to infer from text
                if 'note' in page['text'].lower():
                    page['category'] = 16
                elif 'lab' in page['text'].lower():
                    page['category'] = 24
                else:
                    page['category'] = most_common_category
                    if page['category'] == 0:
                        logger.warning(f"Page {page['pagenumber']} could not be categorized.")
                        
            if not page['header']:
                page['header'] = most_common_header
            if not page['dos']:
                page['dos'] = most_common_dos
            if not page['provider']:
                page['provider'] = most_common_provider

    def generate_output_csv(self, output_path: str):
        """Generate the final CSV output."""
        df = pd.DataFrame(self.pages_data)
        df = df.drop('text', axis=1)
        df['lockstatus'] = 'L'
        df['facilitygroup'] = ''
        df['reviewerid'] = 287
        df['qcreviewerid'] = 322
        df['isduplicate'] = False
        columns = ['pagenumber', 'category', 'isreviewable', 'dos', 'provider',
                  'referencekey', 'parentkey', 'lockstatus', 'header',
                  'facilitygroup', 'reviewerid', 'qcreviewerid', 'isduplicate']
        df = df[columns]
        df.to_csv(output_path, index=False)
        logger.info(f"Output CSV generated at: {output_path}")

def main():
    segmenter = EHRSegmenter('Sample Document.pdf')
    logger.info("Extracting text from PDF...")
    segmenter.extract_text_from_pdf()
    logger.info("Grouping records...")
    segmenter.group_records()
    logger.info("Generating output CSV...")
    segmenter.generate_output_csv('output.csv')
    logger.info("Processing completed successfully!")

if __name__ == "__main__":
    main() 