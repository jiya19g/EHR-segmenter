import pdfplumber
import pandas as pd
from datetime import datetime
from dateutil import parser
from rapidfuzz import fuzz, process
from typing import Dict, List, Tuple, Optional
import logging
import argparse
from functools import lru_cache
import uuid
from pathlib import Path
import json
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    """Configuration and constants for the EHR segmenter."""
    CATEGORY_KEYWORDS = {
        24: ['LABORATORY', 'LAB REPORT', 'LAB TEST', 'LABS', 'LABORATORY REPORT'],
        16: ['PROGRESS', 'CLINICAL NOTE', 'CONSULTATION', 'PROGRESS NOTE', 'CLINICAL', 'NOTE'],
        17: ['DISCHARGE', 'DISCHARGE SUMMARY'],
        18: ['CONSULTATION', 'CONSULT'],
        19: ['OPERATIVE', 'SURGICAL', 'SURGERY'],
        20: ['RADIOLOGY', 'X-RAY', 'IMAGING'],
        21: ['PATHOLOGY', 'PATH'],
        22: ['EMERGENCY', 'ER', 'ED'],
        23: ['PHARMACY', 'MEDICATION', 'PRESCRIPTION']
    }
    
    # Category to facility group mapping
    CATEGORY_TO_FACILITY_GROUP = {
        24: 'LABORATORY',
        16: 'CLINICAL',
        17: 'DISCHARGE',
        18: 'CONSULTATION',
        19: 'SURGICAL',
        20: 'RADIOLOGY',
        21: 'PATHOLOGY',
        22: 'EMERGENCY',
        23: 'PHARMACY'
    }
    
    DATE_PATTERNS = [
        r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
        r'\d{1,2}-\d{1,2}-\d{4}',  # MM-DD-YYYY
        r'\d{4}-\d{1,2}-\d{1,2}',  # YYYY-MM-DD
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}'  # Month DD, YYYY
    ]
    
    HEADER_KEYWORDS = ['LABORATORY', 'PROGRESS', 'NOTE', 'REPORT', 'CLINICAL', 'CONSULTATION']
    
    # Grouping thresholds
    HEADER_SIMILARITY_THRESHOLD = 85
    CONTENT_SIMILARITY_THRESHOLD = 75
    PROVIDER_SIMILARITY_THRESHOLD = 80
    
    # Cache sizes
    MAX_CACHE_SIZE = 128
    
    # Add default provider and facility names
    DEFAULT_PROVIDER = "ABC DoctorName"
    DEFAULT_FACILITY = "ABC Facility Name"

class Extractor:
    """Handles extraction of metadata from PDF pages."""
    
    @staticmethod
    @lru_cache(maxsize=Config.MAX_CACHE_SIZE)
    def normalize_header(header: str) -> str:
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
    
    @staticmethod
    def extract_dos(text: str) -> str:
        """Extract the most relevant date of service (DOS) from the page."""
        lines = text.split('\n')
        date_candidates = []
        keyword_contexts = [
            'frequency', 'signed by', 'provider', 'doctor', 'department', 'facility', 'service date', 'date of service', 'seen', 'visit', 'admission', 'discharge'
        ]
        ignore_contexts = ['dob', 'date of birth']
        # Collect all date matches with their line index and context
        for idx, line in enumerate(lines):
            line_lower = line.lower()
            # Ignore lines with DOB
            if any(ignore in line_lower for ignore in ignore_contexts):
                continue
            for pattern in Config.DATE_PATTERNS:
                for match in re.findall(pattern, line, re.IGNORECASE):
                    # Check for context keywords in the line or nearby lines
                    context_score = 0
                    for k in keyword_contexts:
                        if k in line_lower:
                            context_score += 2
                        # Look at previous and next line for context
                        if idx > 0 and k in lines[idx-1].lower():
                            context_score += 1
                        if idx < len(lines)-1 and k in lines[idx+1].lower():
                            context_score += 1
                    date_candidates.append((idx, context_score, match.strip()))
        # Prefer candidates with context, then those closer to the bottom
        if date_candidates:
            # Sort by context_score DESC, then by idx DESC (bottom-most)
            date_candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
            return date_candidates[0][2]
        # Fallback: last date on the page (not the first)
        all_dates = []
        for idx, line in enumerate(lines):
            if any(ignore in line.lower() for ignore in ignore_contexts):
                continue
            for pattern in Config.DATE_PATTERNS:
                for match in re.findall(pattern, line, re.IGNORECASE):
                    all_dates.append((idx, match.strip()))
        if all_dates:
            return all_dates[-1][1]
        return ""
    
    @staticmethod
    def extract_provider_facility(text: str) -> str:
        """Extract provider and facility information using regex patterns."""
        lines = text.split('\n')
        patterns = [
            r'(?:Facility|Provider|Doctor|Dr\.|Physician):\s*(.+)',
            r'(?:Hospital|Clinic|Medical Center):\s*(.+)'
        ]
        
        provider = None
        facility = None
        
        # First try to find provider and facility in the text
        for line in lines[:20]:
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    if 'facility' in line.lower() or 'hospital' in line.lower() or 'clinic' in line.lower():
                        facility = value
                    else:
                        provider = value
        
        # If not found, use defaults
        if not provider:
            provider = Config.DEFAULT_PROVIDER
        if not facility:
            facility = Config.DEFAULT_FACILITY
            
        return f"{provider} - {facility}"

class Grouper:
    """Handles grouping of pages into records."""
    
    @staticmethod
    def calculate_similarity_score(prev_page: Dict, curr_page: Dict) -> float:
        """Calculate similarity score between two pages."""
        score = 0.0
        
        # DOS match (exact)
        if prev_page['dos'] and curr_page['dos']:
            score += 1.0 if prev_page['dos'] == curr_page['dos'] else 0.0
        
        # Header similarity
        prev_header = Extractor.normalize_header(prev_page['header'])
        curr_header = Extractor.normalize_header(curr_page['header'])
        header_similarity = fuzz.token_set_ratio(prev_header, curr_header) / 100.0
        score += header_similarity
        
        # Content similarity
        content_similarity = fuzz.partial_ratio(
            prev_page['text'][-200:],
            curr_page['text'][:200]
        ) / 100.0
        score += content_similarity
        
        # Provider similarity
        if prev_page['provider'] and curr_page['provider']:
            provider_similarity = fuzz.ratio(
                prev_page['provider'],
                curr_page['provider']
            ) / 100.0
            score += provider_similarity
        
        return score / 4.0  # Normalize to 0-1 range
    
    @staticmethod
    def belongs_to_same_record(prev_page: Dict, curr_page: Dict) -> bool:
        """Determine if current page belongs to the same record as previous page."""
        score = Grouper.calculate_similarity_score(prev_page, curr_page)
        
        # Check for continuation markers
        is_continuation = any(
            marker in curr_page['header'].lower()
            for marker in ['(continued)', '(cont.)', 'continued']
        )
        
        # Lower threshold for continuation pages
        threshold = 0.6 if is_continuation else 0.7
        return score >= threshold

class EHRSegmenter:
    """Main class for EHR segmentation."""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pages_data = []
        self.current_record = None
        self.referencekey_counter = 120991  # Start referencekey at 120991
    
    def extract_text_from_pdf(self) -> List[Dict]:
        """Extract text and metadata from each page of the PDF."""
        prev_header = ""
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if not text:
                        continue
                    
                    # Extract metadata
                    header = self._extract_header(text, prev_header)
                    if header:
                        prev_header = header
                        header = Extractor.normalize_header(header)
                    
                    dos = Extractor.extract_dos(text)
                    provider_facility = Extractor.extract_provider_facility(text)
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
        """Extract header from the first 15 lines."""
        lines = text.split('\n')
        
        # First pass: look for exact matches
        for line in lines[:15]:
            if any(keyword in line.upper() for keyword in Config.HEADER_KEYWORDS):
                return line.strip()
            if "(continued)" in line.lower() or "(cont.)" in line.lower():
                return line.strip()
        
        # Second pass: look for partial matches
        for line in lines[:15]:
            for keyword in Config.HEADER_KEYWORDS:
                if fuzz.partial_ratio(keyword, line.upper()) > 80:
                    return line.strip()
        
        # Fallback to previous header
        return prev_header if prev_header else ""
    
    def _determine_category(self, header: str, text: str) -> Optional[int]:
        """Determine the category based on header content and page text."""
        header_upper = header.upper()
        text_upper = text.upper()
        
        # Check header first
        for category, keywords in Config.CATEGORY_KEYWORDS.items():
            if any(keyword in header_upper for keyword in keywords):
                return category
        
        # Check first 500 characters of text
        for category, keywords in Config.CATEGORY_KEYWORDS.items():
            if any(keyword in text_upper[:500] for keyword in keywords):
                return category
        
        # If still no category found, try to infer from text content
        # Prioritize Progress Note (16) over Emergency (22)
        if any(keyword in text_upper[:1000] for keyword in ['NOTE', 'CLINICAL', 'PROGRESS']):
            return 16  # Progress Note
        elif any(keyword in text_upper[:1000] for keyword in ['LAB', 'LABORATORY']):
            return 24  # Laboratory Report
        elif any(keyword in text_upper[:1000] for keyword in ['DISCHARGE']):
            return 17  # Discharge
        elif any(keyword in text_upper[:1000] for keyword in ['EMERGENCY', 'ER', 'ED']):
            # Only assign Emergency (22) if there's a clear emergency indicator
            # and no other category indicators are present
            if not any(keyword in text_upper[:1000] for keyword in ['NOTE', 'CLINICAL', 'PROGRESS']):
                return 22  # Emergency
        
        # Default to Progress Note (16) if no clear category is found
        logger.warning(f"Could not determine category for header: {header}, defaulting to Progress Note")
        return 16
    
    def group_records(self) -> List[Dict]:
        """Group pages into records based on content similarity."""
        if not self.pages_data:
            return []
        
        current_group = []
        grouped_records = []
        
        for i, page in enumerate(self.pages_data):
            if not current_group:
                current_group = [page]
                continue
            
            if Grouper.belongs_to_same_record(current_group[-1], page):
                current_group.append(page)
            else:
                self._process_group(current_group)
                grouped_records.extend(current_group)
                current_group = [page]
        
        if current_group:
            self._process_group(current_group)
            grouped_records.extend(current_group)
        
        return grouped_records
    
    def _process_group(self, group: List[Dict]):
        """Process a group of pages and assign parent/reference keys and propagate metadata."""
        if not group:
            return
        # Find most common values in the group
        categories = [p['category'] for p in group if p['category'] is not None]
        most_common_category = max(set(categories), key=categories.count) if categories else 16
        headers = [p['header'] for p in group if p['header']]
        most_common_header = max(set(headers), key=headers.count) if headers else ""
        dos_values = [p['dos'] for p in group if p['dos']]
        most_common_dos = max(set(dos_values), key=dos_values.count) if dos_values else ""
        providers = [p['provider'] for p in group if p['provider']]
        most_common_provider = max(set(providers), key=providers.count) if providers else Config.DEFAULT_PROVIDER + " - " + Config.DEFAULT_FACILITY
        # Assign keys and propagate metadata
        group_size = len(group)
        first_refkey = self.referencekey_counter
        for i, page in enumerate(group):
            if i == 0:
                page['referencekey'] = first_refkey
                page['parentkey'] = 0
            else:
                page['referencekey'] = first_refkey + i
                page['parentkey'] = first_refkey
            # Propagate metadata
            page['category'] = most_common_category
            page['header'] = most_common_header
            page['dos'] = most_common_dos
            page['provider'] = most_common_provider
            # Facility group: leave blank if not reliably extracted
            page['facilitygroup'] = ''
        self.referencekey_counter += group_size
    
    def generate_output_csv(self, output_path: str):
        """Generate the final CSV output."""
        df = pd.DataFrame(self.pages_data)
        df = df.drop('text', axis=1)
        
        # Add required columns
        df['lockstatus'] = 'L'
        df['reviewerid'] = 287
        df['qcreviewerid'] = 322
        df['isduplicate'] = False
        
        # Ensure facilitygroup is set based on category
        df['facilitygroup'] = df['category'].map(Config.CATEGORY_TO_FACILITY_GROUP).fillna('')
        
        # Reorder columns
        columns = [
            'pagenumber', 'category', 'isreviewable', 'dos', 'provider',
            'referencekey', 'parentkey', 'lockstatus', 'header',
            'facilitygroup', 'reviewerid', 'qcreviewerid', 'isduplicate'
        ]
        
        df = df[columns]
        df.to_csv(output_path, index=False)
        logger.info(f"Output CSV generated at: {output_path}")

def main():
    """Main function with CLI support."""
    parser = argparse.ArgumentParser(description='EHR Segmentation Tool')
    parser.add_argument('--input', required=True, help='Input PDF file path')
    parser.add_argument('--output', default='output.csv', help='Output CSV file path')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        segmenter = EHRSegmenter(args.input)
        logger.info("Extracting text from PDF...")
        segmenter.extract_text_from_pdf()
        logger.info("Grouping records...")
        segmenter.group_records()
        logger.info("Generating output CSV...")
        segmenter.generate_output_csv(args.output)
        logger.info("Processing completed successfully!")
    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        raise

if __name__ == "__main__":
    main() 