"""
Structured Data Organizer for AI/LLM Processing
Organizes transcripts with rich metadata for N8N and AI tools
"""

import os
import json
import hashlib
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict
import re

import logging
logger = logging.getLogger(__name__)

from .markdown_transcript_generator import MarkdownTranscriptGenerator


class StructuredDataOrganizer:
    """
    Organizes transcription data in an AI/LLM-friendly structure
    Optimized for N8N workflows and machine learning pipelines
    """

    def __init__(
        self,
        base_directory: str = "/var/www/call-recording-system/data/structured",
        enable_indexing: bool = True,
        enable_embeddings_prep: bool = True
    ):
        """
        Initialize the structured data organizer

        Args:
            base_directory: Root directory for structured data
            enable_indexing: Create searchable indexes
            enable_embeddings_prep: Prepare data for embedding generation
        """
        self.base_dir = Path(base_directory)
        self.enable_indexing = enable_indexing
        self.enable_embeddings_prep = enable_embeddings_prep

        # Initialize markdown generator
        self.markdown_generator = MarkdownTranscriptGenerator()

        # Create directory structure
        self._initialize_directory_structure()

        # Initialize indexes
        self.indexes = {
            'by_customer': defaultdict(list),
            'by_phone': defaultdict(list),
            'by_date': defaultdict(list),
            'by_agent': defaultdict(list),
            'by_topic': defaultdict(list),
            'by_sentiment': defaultdict(list)
        }

    def _initialize_directory_structure(self):
        """
        Create the ideal directory structure for AI/LLM processing

        Structure:
        /structured/
        ├── by_date/                 # Chronological organization
        │   ├── 2025/
        │   │   ├── 01/
        │   │   │   ├── 19/
        │   │   │   │   ├── call_001.json
        │   │   │   │   └── call_002.json
        ├── by_customer/             # Customer-centric view
        │   ├── customer_id/
        │   │   ├── metadata.json
        │   │   ├── calls/
        │   │   └── analytics/
        ├── by_phone/                # Phone number organization
        │   ├── +1234567890/
        │   │   ├── inbound/
        │   │   └── outbound/
        ├── n8n_workflows/           # N8N-ready data
        │   ├── queue/               # Processing queue
        │   ├── processed/           # Completed items
        │   └── webhooks/            # Webhook payloads
        ├── ml_datasets/             # ML-ready formats
        │   ├── training/
        │   ├── embeddings/
        │   └── classifications/
        ├── analytics/               # Aggregated analytics
        │   ├── daily_summaries/
        │   ├── sentiment_analysis/
        │   └── topic_modeling/
        ├── indexes/                 # Search indexes
        │   ├── master_index.json
        │   ├── customer_index.json
        │   └── phone_index.json
        └── exports/                 # Export formats
            ├── csv/
            ├── parquet/
            └── elasticsearch/
        """
        directories = [
            # Date-based organization
            'by_date',

            # Human review transcripts
            'human_review/by_date',
            'human_review/by_employee',
            'human_review/pending_review',
            'human_review/reviewed',

            # Entity-based organization
            'by_customer',
            'by_phone',
            'by_agent',
            'by_employee',      # Employee/extension based
            'by_extension',     # Direct extension organization

            # N8N workflow directories
            'n8n_workflows/queue',
            'n8n_workflows/processed',
            'n8n_workflows/webhooks',
            'n8n_workflows/templates',

            # ML/AI directories
            'ml_datasets/training',
            'ml_datasets/embeddings',
            'ml_datasets/classifications',
            'ml_datasets/ner_entities',  # Named Entity Recognition
            'ml_datasets/sentiment',
            'ml_datasets/topics',

            # Analytics directories
            'analytics/daily_summaries',
            'analytics/sentiment_analysis',
            'analytics/topic_modeling',
            'analytics/customer_insights',
            'analytics/call_patterns',

            # Index directories
            'indexes',
            'indexes/temporal',
            'indexes/entities',
            'indexes/full_text',

            # Export directories
            'exports/csv',
            'exports/parquet',
            'exports/elasticsearch',
            'exports/bigquery',

            # Metadata and schemas
            'metadata/schemas',
            'metadata/mappings',
            'metadata/taxonomies'
        ]

        for dir_path in directories:
            full_path = self.base_dir / dir_path
            full_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Directory structure initialized at {self.base_dir}")

    def process_transcription(
        self,
        transcription_data: Dict[str, Any],
        call_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process and organize a transcription with enhanced metadata

        Args:
            transcription_data: Raw transcription data
            call_metadata: Call metadata

        Returns:
            Processing result with file locations
        """
        # Generate unique ID
        call_id = call_metadata.get('recording_id', self._generate_call_id())

        # Enrich metadata
        enriched_data = self._enrich_metadata(transcription_data, call_metadata)

        # Extract entities and features
        extracted_features = self._extract_features(enriched_data)

        # Create comprehensive document
        document = self._create_structured_document(
            call_id=call_id,
            transcription=enriched_data,
            features=extracted_features
        )

        # Save to multiple locations for different access patterns
        saved_locations = self._save_structured_data(document)

        # Update indexes
        if self.enable_indexing:
            self._update_indexes(document)

        # Prepare for N8N processing
        n8n_payload = self._prepare_n8n_payload(document)
        self._queue_for_n8n(n8n_payload)

        # Prepare for ML pipelines
        if self.enable_embeddings_prep:
            self._prepare_ml_format(document)

        return {
            'success': True,
            'call_id': call_id,
            'document': document,
            'paths': list(saved_locations.values()),
            'locations': saved_locations,
            'indexes_updated': self.enable_indexing,
            'n8n_queued': True,
            'features': extracted_features
        }

    def _enrich_metadata(
        self,
        transcription_data: Dict[str, Any],
        call_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich metadata with additional structured information

        Returns enriched data with:
        - Normalized phone numbers
        - Customer identification
        - Time-based features
        - Call classifications
        """
        enriched = {
            **transcription_data,
            'metadata': {
                **transcription_data.get('metadata', {}),
                **call_metadata
            }
        }

        # Normalize phone numbers and detect extensions
        from_number = call_metadata.get('phone_from', call_metadata.get('from_number'))
        to_number = call_metadata.get('phone_to', call_metadata.get('to_number'))

        enriched['normalized_phones'] = {
            'from': self._normalize_phone(from_number),
            'to': self._normalize_phone(to_number)
        }

        # Extract extensions from phone numbers if present
        # Look for patterns like ext:1234 or x1234 in caller name or after phone number
        caller_name = call_metadata.get('caller_name', '')

        # Check for extension patterns
        ext_patterns = [
            r'ext[:\.]?\s*(\d+)',
            r'x(\d+)',
            r'extension[:\.]?\s*(\d+)'
        ]

        for pattern in ext_patterns:
            match = re.search(pattern, caller_name, re.IGNORECASE)
            if match:
                enriched['extension'] = match.group(1)
                enriched['employee_name'] = re.sub(pattern, '', caller_name, flags=re.IGNORECASE).strip()
                break

        # Also check if the last 3-4 digits of internal numbers might be extensions
        if not enriched.get('extension'):
            # If it's an internal number (shorter than normal phone)
            if from_number and len(str(from_number)) <= 6:
                enriched['extension'] = str(from_number)
            elif to_number and len(str(to_number)) <= 6:
                enriched['extension'] = str(to_number)

        # Extract temporal features
        # Support both 'call_start_time' and 'start_time' for compatibility
        start_time_key = 'call_start_time' if 'call_start_time' in call_metadata else 'start_time'
        if start_time_key in call_metadata:
            start_time = datetime.fromisoformat(str(call_metadata[start_time_key]))
            enriched['temporal_features'] = {
                'year': start_time.year,
                'month': start_time.month,
                'day': start_time.day,
                'hour': start_time.hour,
                'day_of_week': start_time.strftime('%A'),
                'week_of_year': start_time.isocalendar()[1],
                'quarter': (start_time.month - 1) // 3 + 1,
                'is_business_hours': 9 <= start_time.hour < 17,
                'timestamp_iso': start_time.isoformat()
            }

        # Add processing metadata
        enriched['processing_metadata'] = {
            'processed_at': datetime.now(timezone.utc).isoformat(),
            'schema_version': '2.0',
            'organizer_version': '1.0'
        }

        return enriched

    def _extract_features(self, enriched_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract features for AI/ML processing

        Features extracted:
        - Named entities (names, companies, locations)
        - Phone numbers mentioned in conversation
        - Dates and times mentioned
        - Monetary amounts
        - Email addresses
        - Keywords and topics
        """
        text = enriched_data.get('text', '')
        features = {
            'entities': {},
            'keywords': [],
            'metrics': {}
        }

        # Extract phone numbers from text
        phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
        features['entities']['phone_numbers'] = re.findall(phone_pattern, text)

        # Extract email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        features['entities']['emails'] = re.findall(email_pattern, text)

        # Extract potential monetary amounts
        money_pattern = r'\$[\d,]+\.?\d*'
        features['entities']['amounts'] = re.findall(money_pattern, text)

        # Extract dates (simple pattern)
        date_pattern = r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b'
        features['entities']['dates'] = re.findall(date_pattern, text)

        # Calculate metrics
        features['metrics'] = {
            'word_count': enriched_data.get('word_count', 0),
            'duration_seconds': enriched_data.get('metadata', {}).get('duration', 0),
            'confidence_score': enriched_data.get('confidence', 0),
            'speaking_rate': self._calculate_speaking_rate(enriched_data)
        }

        # Extract potential customer names (simple heuristic)
        features['entities']['potential_names'] = self._extract_potential_names(text)

        # Identify potential topics/keywords
        features['keywords'] = self._extract_keywords(text)

        return features

    def _create_structured_document(
        self,
        call_id: str,
        transcription: Dict[str, Any],
        features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a comprehensive structured document for AI processing

        This document format is optimized for:
        - N8N workflows
        - LLM analysis
        - Embedding generation
        - Search indexing
        """
        document = {
            # Unique identifiers
            'id': call_id,
            'document_type': 'call_transcript',
            'schema_version': '2.0',

            # Core content
            'content': {
                'text': transcription.get('text', ''),
                'segments': transcription.get('segments', []),
                'summary': transcription.get('summary', None)
            },

            # Call information
            'call_info': {
                'recording_id': transcription.get('metadata', {}).get('recording_id'),
                'start_time': transcription.get('temporal_features', {}).get('timestamp_iso'),
                'duration_seconds': transcription.get('metadata', {}).get('duration'),
                'direction': transcription.get('metadata', {}).get('direction'),
                'participants': {
                    'from': {
                        'number': transcription.get('normalized_phones', {}).get('from'),
                        'name': transcription.get('metadata', {}).get('from_name', transcription.get('employee_name')),
                        'extension': transcription.get('extension') if transcription.get('metadata', {}).get('direction') == 'outbound' else None,
                        'type': 'caller'
                    },
                    'to': {
                        'number': transcription.get('normalized_phones', {}).get('to'),
                        'name': transcription.get('metadata', {}).get('to_name'),
                        'extension': transcription.get('extension') if transcription.get('metadata', {}).get('direction') == 'inbound' else None,
                        'type': 'recipient'
                    }
                }
            },

            # Temporal organization
            'temporal': transcription.get('temporal_features', {}),

            # Extracted features
            'features': features,

            # Language and quality
            'language_info': {
                'language': transcription.get('language', 'en-US'),
                'confidence': transcription.get('language_probability', 0),
                'transcription_confidence': transcription.get('confidence', 0)
            },

            # Processing metadata
            'metadata': {
                'created_at': datetime.now(timezone.utc).isoformat(),
                'processing': transcription.get('processing_metadata', {}),
                'source': 'salad_cloud',
                'audio_deleted': True,  # Security compliance
                'retention_policy': 'transcript_only'
            },

            # N8N workflow hints
            'n8n_hints': {
                'workflow_ready': True,
                'requires_sentiment_analysis': True,
                'requires_entity_extraction': True,
                'requires_summarization': len(transcription.get('text', '')) > 1000,
                'priority': self._calculate_priority(transcription)
            },

            # Search and indexing
            'search_tags': self._generate_search_tags(transcription, features)
        }

        return document

    def _save_structured_data(self, document: Dict[str, Any]) -> Dict[str, str]:
        """
        Save structured data to multiple locations for different access patterns

        Returns dictionary of saved locations
        """
        locations = {}
        call_id = document['id']
        temporal = document.get('temporal', {})

        # 1. Save by date
        if temporal:
            date_path = self.base_dir / 'by_date' / str(temporal['year']) / f"{temporal['month']:02d}" / f"{temporal['day']:02d}"
            date_path.mkdir(parents=True, exist_ok=True)
            date_file = date_path / f"{call_id}.json"
            with open(date_file, 'w') as f:
                json.dump(document, f, indent=2, default=str)
            locations['by_date'] = str(date_file)

        # 2. Save by phone number
        from_number = document.get('call_info', {}).get('participants', {}).get('from', {}).get('number')
        if from_number:
            phone_path = self.base_dir / 'by_phone' / self._sanitize_filename(from_number)
            phone_path.mkdir(parents=True, exist_ok=True)
            phone_file = phone_path / f"{call_id}.json"
            with open(phone_file, 'w') as f:
                json.dump(document, f, indent=2, default=str)
            locations['by_phone'] = str(phone_file)

        # 3. Save to N8N queue
        n8n_queue_path = self.base_dir / 'n8n_workflows' / 'queue'
        n8n_file = n8n_queue_path / f"{call_id}.json"
        with open(n8n_file, 'w') as f:
            json.dump(document, f, indent=2, default=str)
        locations['n8n_queue'] = str(n8n_file)

        # 4. Save ML-ready format
        ml_path = self.base_dir / 'ml_datasets' / 'training'
        ml_file = ml_path / f"{call_id}.json"
        ml_document = self._prepare_ml_document(document)
        with open(ml_file, 'w') as f:
            json.dump(ml_document, f, indent=2, default=str)
        locations['ml_dataset'] = str(ml_file)

        # 5. Save by employee/extension
        participants = document.get('call_info', {}).get('participants', {})

        # Check for extension in metadata or participants
        extension = None
        employee_name = None

        # Try to extract extension from various places
        for participant_type in ['from', 'to']:
            participant = participants.get(participant_type, {})
            if participant.get('extension'):
                extension = participant['extension']
                employee_name = participant.get('name')
                break

        # Save by extension if found
        if extension:
            ext_path = self.base_dir / 'by_extension' / str(extension)
            ext_path.mkdir(parents=True, exist_ok=True)
            ext_file = ext_path / f"{call_id}.json"
            with open(ext_file, 'w') as f:
                json.dump(document, f, indent=2, default=str)
            locations['by_extension'] = str(ext_file)

            # Also save by employee name if available
            if employee_name:
                emp_path = self.base_dir / 'by_employee' / self._sanitize_filename(employee_name)
                emp_path.mkdir(parents=True, exist_ok=True)
                emp_file = emp_path / f"{call_id}.json"
                with open(emp_file, 'w') as f:
                    json.dump(document, f, indent=2, default=str)
                locations['by_employee'] = str(emp_file)

        # 6. Generate and save human-readable markdown transcript
        if temporal:
            # Save by date for human review
            review_date_path = self.base_dir / 'human_review' / 'by_date' / str(temporal['year']) / f"{temporal['month']:02d}" / f"{temporal['day']:02d}"
            review_date_path.mkdir(parents=True, exist_ok=True)
            markdown_file = review_date_path / f"{call_id}.md"

            markdown_path = self.markdown_generator.save_markdown_transcript(
                document=document,
                output_path=markdown_file,
                include_metadata=True,
                include_analysis=True,
                include_technical=False  # Keep it clean for human review
            )
            locations['human_review_markdown'] = markdown_path

            # Also save to pending review
            pending_path = self.base_dir / 'human_review' / 'pending_review' / f"{call_id}.md"
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(markdown_file, pending_path)
            locations['pending_review'] = str(pending_path)

            # If employee is identified, save in employee folder too
            if employee_name:
                emp_review_path = self.base_dir / 'human_review' / 'by_employee' / self._sanitize_filename(employee_name)
                emp_review_path.mkdir(parents=True, exist_ok=True)
                emp_markdown = emp_review_path / f"{call_id}.md"
                shutil.copy2(markdown_file, emp_markdown)
                locations['employee_review'] = str(emp_markdown)

        return locations

    def _prepare_n8n_payload(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare N8N-compatible payload with webhook-friendly structure

        N8N best practices:
        - Flat structure where possible
        - Clear field names
        - Webhook-ready format
        - Included processing hints
        """
        return {
            'id': document['id'],
            'timestamp': document['metadata']['created_at'],
            'transcript_text': document['content']['text'],
            'duration_seconds': document['call_info']['duration_seconds'],
            'from_number': document['call_info']['participants']['from']['number'],
            'to_number': document['call_info']['participants']['to']['number'],
            'direction': document['call_info']['direction'],
            'confidence': document['language_info']['transcription_confidence'],
            'word_count': document['features']['metrics']['word_count'],
            'entities': document['features']['entities'],
            'workflow_hints': document['n8n_hints'],
            'webhook_url': os.getenv('N8N_WEBHOOK_URL', ''),
            'callback_url': f"/api/transcripts/{document['id']}/processed"
        }

    def _queue_for_n8n(self, payload: Dict[str, Any]):
        """Queue document for N8N processing"""
        queue_file = self.base_dir / 'n8n_workflows' / 'queue' / f"{payload['id']}_n8n.json"
        with open(queue_file, 'w') as f:
            json.dump(payload, f, indent=2, default=str)

    def _prepare_ml_format(self, document: Dict[str, Any]):
        """
        Prepare data for ML pipelines (embeddings, classification, etc.)

        Creates formats for:
        - Text embedding generation
        - Sentiment analysis
        - Topic modeling
        - Named entity recognition
        """
        # Prepare for embeddings
        embedding_doc = {
            'id': document['id'],
            'text': document['content']['text'],
            'chunks': self._chunk_text_for_embeddings(document['content']['text']),
            'metadata': {
                'timestamp': document['call_info']['start_time'],
                'participants': document['call_info']['participants']
            }
        }

        embeddings_path = self.base_dir / 'ml_datasets' / 'embeddings'
        with open(embeddings_path / f"{document['id']}_embed.json", 'w') as f:
            json.dump(embedding_doc, f, indent=2)

    def _prepare_ml_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare ML-optimized document format"""
        return {
            'id': document['id'],
            'text': document['content']['text'],
            'features': {
                'length': len(document['content']['text']),
                'word_count': document['features']['metrics']['word_count'],
                'duration': document['call_info']['duration_seconds'],
                'confidence': document['language_info']['transcription_confidence'],
                'entities': document['features']['entities'],
                'temporal': document['temporal']
            },
            'labels': {},  # For supervised learning
            'embeddings': None,  # Placeholder for generated embeddings
        }

    def _update_indexes(self, document: Dict[str, Any]):
        """Update various indexes for fast retrieval"""
        call_id = document['id']

        # Update phone index
        from_number = document['call_info']['participants']['from']['number']
        if from_number:
            self.indexes['by_phone'][from_number].append(call_id)

        # Update date index
        date_key = f"{document['temporal']['year']}-{document['temporal']['month']:02d}-{document['temporal']['day']:02d}"
        self.indexes['by_date'][date_key].append(call_id)

        # Save indexes periodically
        self._persist_indexes()

    def _persist_indexes(self):
        """Save indexes to disk"""
        index_dir = self.base_dir / 'indexes'

        for index_name, index_data in self.indexes.items():
            index_file = index_dir / f"{index_name}.json"
            with open(index_file, 'w') as f:
                json.dump(dict(index_data), f, indent=2, default=str)

    def _normalize_phone(self, phone: Optional[str]) -> str:
        """Normalize phone number to E.164 format"""
        if not phone:
            return ""

        # Remove all non-numeric characters
        cleaned = re.sub(r'\D', '', phone)

        # Add country code if missing (assuming US)
        if len(cleaned) == 10:
            cleaned = '1' + cleaned

        # Format as E.164
        if len(cleaned) == 11:
            return f"+{cleaned}"

        return phone  # Return original if can't normalize

    def _sanitize_filename(self, text: str) -> str:
        """Sanitize text for use as filename"""
        # Remove special characters
        sanitized = re.sub(r'[^\w\s-]', '', text)
        # Replace spaces with underscores
        sanitized = re.sub(r'[-\s]+', '_', sanitized)
        return sanitized

    def _generate_call_id(self) -> str:
        """Generate unique call ID"""
        timestamp = datetime.now(timezone.utc).isoformat()
        hash_input = f"{timestamp}_{os.urandom(16).hex()}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def _calculate_speaking_rate(self, data: Dict[str, Any]) -> float:
        """Calculate words per minute speaking rate"""
        word_count = data.get('word_count', 0)
        duration = data.get('metadata', {}).get('duration', 0)

        if duration > 0:
            return (word_count / duration) * 60

        return 0

    def _extract_potential_names(self, text: str) -> List[str]:
        """Extract potential customer/agent names (simple heuristic)"""
        # This is a simple pattern - in production, use NER models
        name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
        return re.findall(name_pattern, text)[:5]  # Limit to 5

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords (simple frequency-based)"""
        # Remove common words (stopwords)
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were'}

        words = text.lower().split()
        word_freq = defaultdict(int)

        for word in words:
            cleaned = re.sub(r'[^\w]', '', word)
            if cleaned and cleaned not in stopwords and len(cleaned) > 3:
                word_freq[cleaned] += 1

        # Return top 10 keywords
        sorted_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, freq in sorted_keywords[:10]]

    def _calculate_priority(self, transcription: Dict[str, Any]) -> str:
        """Calculate processing priority based on various factors"""
        # Factors: duration, confidence, keywords
        duration = transcription.get('metadata', {}).get('duration', 0)
        confidence = transcription.get('confidence', 0)

        if duration > 600:  # Long calls (>10 min)
            return 'high'
        elif confidence < 0.7:  # Low confidence
            return 'high'
        else:
            return 'normal'

    def _generate_search_tags(self, transcription: Dict[str, Any], features: Dict[str, Any]) -> List[str]:
        """Generate search tags for indexing"""
        tags = []

        # Add temporal tags
        if 'temporal_features' in transcription:
            temporal = transcription['temporal_features']
            tags.append(f"year:{temporal['year']}")
            tags.append(f"month:{temporal['month']}")
            tags.append(f"day:{temporal['day']}")
            tags.append(f"hour:{temporal['hour']}")
            tags.append(temporal['day_of_week'].lower())

        # Add participant tags
        if 'normalized_phones' in transcription:
            tags.append(f"from:{transcription['normalized_phones']['from']}")
            tags.append(f"to:{transcription['normalized_phones']['to']}")

        # Add feature tags
        if features.get('entities', {}).get('emails'):
            tags.append('has_email')
        if features.get('entities', {}).get('amounts'):
            tags.append('has_amount')

        # Add confidence tags
        confidence = transcription.get('confidence', 0)
        if confidence > 0.9:
            tags.append('high_confidence')
        elif confidence < 0.7:
            tags.append('low_confidence')

        return tags

    def _chunk_text_for_embeddings(self, text: str, chunk_size: int = 512) -> List[str]:
        """
        Chunk text for embedding generation

        Args:
            text: Full text
            chunk_size: Maximum chunk size in characters

        Returns:
            List of text chunks
        """
        words = text.split()
        chunks = []
        current_chunk = []
        current_size = 0

        for word in words:
            word_len = len(word) + 1  # +1 for space
            if current_size + word_len > chunk_size:
                chunks.append(' '.join(current_chunk))
                current_chunk = [word]
                current_size = word_len
            else:
                current_chunk.append(word)
                current_size += word_len

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks