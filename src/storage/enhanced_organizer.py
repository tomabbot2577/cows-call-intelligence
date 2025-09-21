"""
Enhanced Storage Organizer for Dual Format (JSON + Markdown)
Optimized for N8N workflows and LLM analysis
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EnhancedStorageOrganizer:
    """
    Organizes transcriptions in both JSON and Markdown formats
    with comprehensive metadata for LLM/N8N processing
    """

    def __init__(self, base_path: str = "/var/www/call-recording-system/data"):
        """Initialize the enhanced organizer"""
        self.base_path = Path(base_path)

        # Define directory structure
        self.dirs = {
            'json': self.base_path / 'transcriptions' / 'json',
            'markdown': self.base_path / 'transcriptions' / 'markdown',
            'n8n_queue': self.base_path / 'n8n_integration' / 'queue',
            'n8n_processing': self.base_path / 'n8n_integration' / 'processing',
            'n8n_completed': self.base_path / 'n8n_integration' / 'completed',
            'n8n_failed': self.base_path / 'n8n_integration' / 'failed',
            'analytics': self.base_path / 'analytics',
            'indexes': self.base_path / 'transcriptions' / 'indexes'
        }

        # Create all directories
        for dir_path in self.dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Enhanced organizer initialized at {self.base_path}")

    def save_transcription(
        self,
        recording_id: str,
        transcription_result: Dict[str, Any],
        call_metadata: Dict[str, Any],
        google_drive_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Save transcription in both JSON and Markdown formats

        Returns:
            Dict with paths to saved files
        """
        timestamp = datetime.utcnow()

        # Create comprehensive JSON document for LLM/N8N
        json_doc = self._create_json_document(
            recording_id,
            transcription_result,
            call_metadata,
            google_drive_id,
            timestamp
        )

        # Create readable Markdown document
        markdown_doc = self._create_markdown_document(json_doc)

        # Save files
        date_path = timestamp.strftime('%Y/%m/%d')

        # Save JSON
        json_path = self.dirs['json'] / date_path / f"{recording_id}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_doc, f, indent=2, ensure_ascii=False)

        # Save enhanced JSON with AI analysis
        enhanced_json_path = self.dirs['json'] / date_path / f"{recording_id}.enhanced.json"
        with open(enhanced_json_path, 'w', encoding='utf-8') as f:
            json.dump(self._enhance_with_ai_fields(json_doc), f, indent=2, ensure_ascii=False)

        # Save Markdown
        md_path = self.dirs['markdown'] / date_path / f"{recording_id}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown_doc)

        # Add to N8N queue
        queue_path = self._add_to_n8n_queue(recording_id, json_doc)

        # Update indexes
        self._update_indexes(recording_id, json_doc)

        logger.info(f"Saved transcription {recording_id} in dual format")

        return {
            'json': str(json_path),
            'enhanced_json': str(enhanced_json_path),
            'markdown': str(md_path),
            'n8n_queue': str(queue_path)
        }

    def _create_json_document(
        self,
        recording_id: str,
        transcription: Dict[str, Any],
        call_metadata: Dict[str, Any],
        google_drive_id: Optional[str],
        timestamp: datetime
    ) -> Dict[str, Any]:
        """Create comprehensive JSON document for LLM/N8N processing"""

        # Extract transcription details
        text = transcription.get('text', '')
        segments = transcription.get('segments', [])
        confidence = transcription.get('confidence', 0)
        word_count = transcription.get('word_count', 0)

        # Extract enhanced Salad features from metadata
        metadata = transcription.get('metadata', {})
        summary = metadata.get('summary', '')
        srt_content = metadata.get('srt_content', '')
        word_segments = metadata.get('word_segments', [])
        salad_processing_time = metadata.get('salad_processing_time', 0)
        overall_processing_time = metadata.get('overall_processing_time', 0)

        # Parse call metadata
        from_info = call_metadata.get('from', {})
        to_info = call_metadata.get('to', {})

        doc = {
            'recording_id': recording_id,
            'version': '2.0',
            'timestamp': timestamp.isoformat() + 'Z',

            'call_metadata': {
                'date': call_metadata.get('date', timestamp.strftime('%Y-%m-%d')),
                'time': call_metadata.get('time', timestamp.strftime('%H:%M:%S')),
                'duration_seconds': call_metadata.get('duration', 0),
                'direction': call_metadata.get('direction', 'unknown'),
                'from': {
                    'number': from_info.get('number', 'unknown'),
                    'name': from_info.get('name', ''),
                    'extension': from_info.get('extension', ''),
                    'department': from_info.get('department', '')
                },
                'to': {
                    'number': to_info.get('number', 'unknown'),
                    'name': to_info.get('name', ''),
                    'company': to_info.get('company', '')
                },
                'file_size_bytes': call_metadata.get('file_size', 0)
            },

            'transcription': {
                'text': text,
                'confidence': confidence,
                'language': transcription.get('language', 'en-US'),
                'language_probability': transcription.get('language_probability', 0.99),
                'word_count': word_count,
                'duration_seconds': transcription.get('duration_seconds', 0),
                'processing_time_seconds': transcription.get('processing_time_seconds', 0),
                'salad_processing_time': salad_processing_time,
                'overall_processing_time': overall_processing_time,
                'segments': segments[:100] if segments else [],  # First 100 segments
                'word_segments': word_segments[:500] if word_segments else [],  # First 500 words
                'speakers': self._extract_speakers(segments),
                'srt_content': srt_content[:5000] if srt_content else '',  # First 5000 chars of SRT
                'summary': summary or self._generate_summary(text),
                'job_id': transcription.get('job_id', ''),
                'timestamps': transcription.get('timestamps', {})
            },

            'ai_analysis': {
                'summary': summary or self._generate_summary(text),
                'sentiment': self._analyze_sentiment(text),
                'topics': self._extract_topics(text),
                'entities': self._extract_entities(text),
                'action_items': self._extract_action_items(text),
                'customer_satisfaction': self._predict_satisfaction(text),
                'key_moments': self._extract_key_moments(segments),
                'conversation_flow': self._analyze_conversation_flow(segments)
            },

            'support_metrics': {
                'issue_type': self._classify_issue(text),
                'resolution_status': self._determine_resolution(text),
                'first_call_resolution': self._check_fcr(text),
                'escalation_required': self._check_escalation(text),
                'follow_up_needed': self._check_followup(text),
                'agent_performance': self._evaluate_agent(text)
            },

            'n8n_metadata': {
                'workflow_ready': True,
                'processing_queue': 'support_calls',
                'tags': self._generate_tags(text),
                'webhook_url': os.getenv('N8N_WEBHOOK_URL', ''),
                'automation_triggers': self._identify_triggers(text)
            },

            'storage': {
                'google_drive_id': google_drive_id or '',
                'google_drive_url': f"https://drive.google.com/file/d/{google_drive_id}/view" if google_drive_id else '',
                'local_path': f"/data/transcriptions/json/{timestamp.strftime('%Y/%m/%d')}/{recording_id}.json",
                'backup_status': 'completed' if google_drive_id else 'pending',
                'retention_days': 90
            }
        }

        return doc

    def _create_markdown_document(self, json_doc: Dict[str, Any]) -> str:
        """Create human-readable Markdown document"""

        call_meta = json_doc['call_metadata']
        trans = json_doc['transcription']
        ai = json_doc['ai_analysis']
        metrics = json_doc['support_metrics']

        # Format duration
        duration_seconds = call_meta['duration_seconds']
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes} minute{'s' if minutes != 1 else ''} {seconds} seconds"

        # Build Markdown
        md = f"""# Call Transcript - {json_doc['recording_id']}
**Date:** {call_meta['date']} at {call_meta['time']}
**Duration:** {duration_str}
**Type:** {call_meta['direction'].title()} Support Call

---

## 📞 Participants

**From:** {call_meta['from']['name'] or 'Unknown'} ({call_meta['from']['number']})
**To:** {call_meta['to']['name'] or 'Unknown'} ({call_meta['to']['number']})

---

## 📝 Summary

{ai['summary']}

**Issue Type:** {metrics['issue_type']}
**Resolution:** {metrics['resolution_status']}
**Follow-up Required:** {'Yes ⚠️' if metrics['follow_up_needed'] else 'No ✅'}

---

## 💬 Full Transcript

"""

        # Add formatted transcript segments
        if trans['segments']:
            for segment in trans['segments'][:50]:  # First 50 segments
                speaker = segment.get('speaker', 'Unknown')
                text = segment.get('text', '')
                start = segment.get('start', 0)

                # Format timestamp
                mins = int(start // 60)
                secs = int(start % 60)
                timestamp = f"[{mins}:{secs:02d}]"

                md += f"**{timestamp} {speaker.title()}:** {text}\n\n"
        else:
            md += f"{trans['text'][:5000]}...\n\n"  # First 5000 chars if no segments

        md += f"""---

## 🎯 Action Items

"""
        for i, item in enumerate(ai['action_items'], 1):
            priority_icon = '⚠️' if item.get('priority') == 'high' else '📋'
            md += f"{i}. {priority_icon} **{item.get('assigned_to', 'Team')}** - {item['description']}\n"

        md += f"""
---

## 📊 Analytics

- **Sentiment:** {ai['sentiment']['overall'].title()}
- **Customer Satisfaction:** {ai['customer_satisfaction']['predicted_score']}/5
- **Key Topics:** {', '.join([t['name'] for t in ai['topics'][:3]])}
- **First Call Resolution:** {'Yes ✅' if metrics['first_call_resolution'] else 'No ❌'}

---

## 🏷️ Tags

{' '.join([f'`{tag}`' for tag in json_doc['n8n_metadata']['tags']])}

---

*Generated: {json_doc['timestamp']}*
*Processor Version: {json_doc['version']}*
"""

        return md

    def _add_to_n8n_queue(self, recording_id: str, json_doc: Dict[str, Any]) -> Path:
        """Add transcription to N8N processing queue"""

        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        queue_file = self.dirs['n8n_queue'] / f"{timestamp}_{recording_id}.json"

        # Create queue entry with minimal data for webhook
        queue_entry = {
            'recording_id': recording_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'file_path': str(self.dirs['json'] / datetime.utcnow().strftime('%Y/%m/%d') / f"{recording_id}.json"),
            'google_drive_id': json_doc['storage'].get('google_drive_id'),
            'triggers': json_doc['n8n_metadata']['automation_triggers'],
            'priority': 'high' if json_doc['support_metrics']['escalation_required'] else 'normal'
        }

        with open(queue_file, 'w') as f:
            json.dump(queue_entry, f, indent=2)

        return queue_file

    def _update_indexes(self, recording_id: str, json_doc: Dict[str, Any]):
        """Update search indexes"""

        # Load or create master index
        index_file = self.dirs['indexes'] / 'master_index.json'
        if index_file.exists():
            with open(index_file, 'r') as f:
                index = json.load(f)
        else:
            index = {'recordings': {}, 'updated': None}

        # Add entry
        index['recordings'][recording_id] = {
            'date': json_doc['call_metadata']['date'],
            'time': json_doc['call_metadata']['time'],
            'duration': json_doc['call_metadata']['duration_seconds'],
            'from': json_doc['call_metadata']['from']['name'] or json_doc['call_metadata']['from']['number'],
            'to': json_doc['call_metadata']['to']['name'] or json_doc['call_metadata']['to']['number'],
            'summary': json_doc['ai_analysis']['summary'][:200],
            'tags': json_doc['n8n_metadata']['tags'],
            'file_path': json_doc['storage']['local_path']
        }

        index['updated'] = datetime.utcnow().isoformat()

        # Save index
        with open(index_file, 'w') as f:
            json.dump(index, f, indent=2)

    def _enhance_with_ai_fields(self, json_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Add additional fields specifically for AI/LLM processing"""

        enhanced = json_doc.copy()

        # Add embeddings placeholder
        enhanced['embeddings'] = {
            'text_embedding': None,  # To be filled by embedding service
            'summary_embedding': None,
            'model': 'text-embedding-ada-002'
        }

        # Add classification placeholders
        enhanced['classifications'] = {
            'intent': None,
            'urgency': None,
            'category': None,
            'subcategory': None
        }

        # Add for training data
        enhanced['ml_metadata'] = {
            'suitable_for_training': True,
            'quality_score': json_doc['transcription']['confidence'],
            'has_ground_truth': False,
            'annotations': []
        }

        return enhanced

    # AI Analysis Helper Methods (simplified implementations)

    def _generate_summary(self, text: str) -> str:
        """Generate summary (placeholder - would use LLM in production)"""
        sentences = text.split('.')[:3]
        return '. '.join(sentences) + '.' if sentences else 'No summary available'

    def _analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment (simplified)"""
        return {
            'overall': 'neutral',
            'customer': 'neutral',
            'agent': 'professional',
            'score': 0.5
        }

    def _extract_topics(self, text: str) -> List[Dict[str, Any]]:
        """Extract topics (simplified)"""
        topics = []
        if 'technical' in text.lower() or 'issue' in text.lower():
            topics.append({'name': 'Technical Support', 'confidence': 0.8})
        if 'billing' in text.lower() or 'payment' in text.lower():
            topics.append({'name': 'Billing', 'confidence': 0.7})
        if 'login' in text.lower() or 'password' in text.lower():
            topics.append({'name': 'Account Access', 'confidence': 0.75})
        return topics[:3]

    def _extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities (simplified)"""
        entities = []
        # Would use NER model in production
        if 'PCRecruiter' in text:
            entities.append({'type': 'SOFTWARE', 'value': 'PCRecruiter', 'mentions': text.count('PCRecruiter')})
        return entities

    def _extract_action_items(self, text: str) -> List[Dict[str, Any]]:
        """Extract action items (simplified)"""
        items = []
        if 'follow up' in text.lower() or 'call back' in text.lower():
            items.append({
                'type': 'follow_up',
                'description': 'Follow up with customer',
                'priority': 'high',
                'assigned_to': 'agent'
            })
        return items

    def _predict_satisfaction(self, text: str) -> Dict[str, Any]:
        """Predict customer satisfaction (simplified)"""
        return {
            'predicted_score': 3,
            'indicators': ['neutral_interaction']
        }

    def _classify_issue(self, text: str) -> str:
        """Classify issue type"""
        text_lower = text.lower()
        if 'technical' in text_lower or 'error' in text_lower:
            return 'technical'
        elif 'billing' in text_lower or 'payment' in text_lower:
            return 'billing'
        elif 'account' in text_lower or 'login' in text_lower:
            return 'account'
        return 'general'

    def _determine_resolution(self, text: str) -> str:
        """Determine resolution status"""
        if 'resolved' in text.lower() or 'fixed' in text.lower():
            return 'resolved'
        elif 'escalate' in text.lower():
            return 'escalated'
        return 'pending'

    def _check_fcr(self, text: str) -> bool:
        """Check first call resolution"""
        return 'resolved' in text.lower() or 'fixed' in text.lower()

    def _check_escalation(self, text: str) -> bool:
        """Check if escalation required"""
        return 'escalate' in text.lower() or 'manager' in text.lower()

    def _check_followup(self, text: str) -> bool:
        """Check if follow-up needed"""
        return 'follow up' in text.lower() or 'call back' in text.lower()

    def _evaluate_agent(self, text: str) -> Dict[str, bool]:
        """Evaluate agent performance"""
        return {
            'greeting': 'hello' in text.lower() or 'thank you for calling' in text.lower(),
            'empathy_shown': 'sorry' in text.lower() or 'understand' in text.lower(),
            'solution_offered': 'help' in text.lower() or 'assist' in text.lower(),
            'proper_closing': 'thank you' in text.lower() or 'have a great' in text.lower()
        }

    def _generate_tags(self, text: str) -> List[str]:
        """Generate tags for the call"""
        tags = []
        text_lower = text.lower()

        if 'technical' in text_lower:
            tags.append('technical')
        if 'urgent' in text_lower or 'asap' in text_lower:
            tags.append('urgent')
        if 'escalate' in text_lower:
            tags.append('escalation')
        if 'billing' in text_lower:
            tags.append('billing')

        return tags

    def _identify_triggers(self, text: str) -> List[str]:
        """Identify automation triggers"""
        triggers = []
        text_lower = text.lower()

        if 'escalate' in text_lower:
            triggers.append('escalation_needed')
        if 'follow up' in text_lower:
            triggers.append('follow_up_required')
        if 'urgent' in text_lower:
            triggers.append('high_priority')

        return triggers

    def _extract_key_moments(self, segments: List[Dict]) -> List[Dict]:
        """Extract key moments from the conversation"""
        key_moments = []
        for i, segment in enumerate(segments[:50]):  # Analyze first 50 segments
            text_lower = segment.get('text', '').lower()
            if any(keyword in text_lower for keyword in
                   ['problem', 'issue', 'error', 'broken', 'not working', 'help', 'urgent', 'critical']):
                key_moments.append({
                    'timestamp': segment.get('start', 0),
                    'segment_id': segment.get('id', i),
                    'type': 'issue_reported',
                    'text': segment.get('text', '')[:200],
                    'speaker': segment.get('speaker', 'unknown')
                })
            elif any(keyword in text_lower for keyword in
                    ['fixed', 'resolved', 'solution', 'try this', 'restart']):
                key_moments.append({
                    'timestamp': segment.get('start', 0),
                    'segment_id': segment.get('id', i),
                    'type': 'solution_offered',
                    'text': segment.get('text', '')[:200],
                    'speaker': segment.get('speaker', 'unknown')
                })
        return key_moments[:10]  # Return top 10 key moments

    def _analyze_conversation_flow(self, segments: List[Dict]) -> Dict:
        """Analyze conversation flow and speaker patterns"""
        speaker_changes = 0
        previous_speaker = None
        agent_speaking_time = 0
        customer_speaking_time = 0
        total_segments = len(segments)

        for segment in segments:
            speaker = segment.get('speaker', 'unknown')
            duration = segment.get('end', 0) - segment.get('start', 0)

            if speaker != previous_speaker:
                speaker_changes += 1
                previous_speaker = speaker

            if 'agent' in speaker.lower():
                agent_speaking_time += duration
            else:
                customer_speaking_time += duration

        total_time = agent_speaking_time + customer_speaking_time

        return {
            'speaker_changes': speaker_changes,
            'total_segments': total_segments,
            'agent_speaking_percentage': round(agent_speaking_time / total_time * 100, 2) if total_time > 0 else 0,
            'customer_speaking_percentage': round(customer_speaking_time / total_time * 100, 2) if total_time > 0 else 0,
            'average_turn_duration': round(total_time / speaker_changes, 2) if speaker_changes > 0 else 0,
            'conversation_pace': 'rapid' if speaker_changes > 20 else 'normal' if speaker_changes > 10 else 'slow'
        }

    def _extract_speakers(self, segments: List[Dict]) -> List[Dict[str, Any]]:
        """Extract speaker information from segments with enhanced diarization data"""
        speakers = {}

        for segment in segments:
            speaker_id = segment.get('speaker', 'unknown')
            if speaker_id not in speakers:
                speakers[speaker_id] = {
                    'id': speaker_id,
                    'label': speaker_id.title(),
                    'speaking_time': 0,
                    'segment_count': 0,
                    'average_confidence': 0
                }

            duration = segment.get('end', 0) - segment.get('start', 0)
            speakers[speaker_id]['speaking_time'] += duration
            speakers[speaker_id]['segment_count'] += 1
            speakers[speaker_id]['average_confidence'] += segment.get('confidence', 0.95)

        # Calculate averages
        for speaker in speakers.values():
            if speaker['segment_count'] > 0:
                speaker['average_confidence'] = round(speaker['average_confidence'] / speaker['segment_count'], 3)
            speaker['speaking_time'] = round(speaker['speaking_time'], 2)

        return list(speakers.values())