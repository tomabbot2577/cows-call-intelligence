#!/usr/bin/env python3
"""
Markdown Transcript Generator for Human Review
Generates clean, formatted markdown files for easy human review of call transcripts
"""

import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
import re
import logging

logger = logging.getLogger(__name__)


class MarkdownTranscriptGenerator:
    """
    Generate human-readable markdown transcripts with proper formatting
    """

    def __init__(self):
        """Initialize the markdown generator"""
        self.template_cache = {}

    def generate_transcript_markdown(
        self,
        document: Dict[str, Any],
        include_metadata: bool = True,
        include_analysis: bool = True,
        include_technical: bool = False
    ) -> str:
        """
        Generate a formatted markdown transcript for human review

        Args:
            document: The structured document containing transcript data
            include_metadata: Include call metadata section
            include_analysis: Include AI analysis sections
            include_technical: Include technical details (IDs, confidence scores)

        Returns:
            Formatted markdown string
        """
        md_lines = []

        # Header
        call_id = document.get('id', 'Unknown')
        call_info = document.get('call_info', {})
        temporal = document.get('temporal', {})

        # Title with call date/time
        if temporal:
            date_str = f"{temporal.get('year', '')}-{temporal.get('month', ''):02d}-{temporal.get('day', ''):02d}"
            time_str = f"{temporal.get('hour', 0):02d}:{temporal.get('timestamp_iso', '').split('T')[1][:5] if 'timestamp_iso' in temporal else '00:00'}"
            md_lines.append(f"# Call Transcript - {date_str} {time_str}")
        else:
            md_lines.append(f"# Call Transcript - {call_id}")

        md_lines.append("")

        # Call Summary Box
        md_lines.append("## 📞 Call Summary")
        md_lines.append("")
        md_lines.append("| Field | Value |")
        md_lines.append("|-------|-------|")

        # Participants
        participants = call_info.get('participants', {})
        from_info = participants.get('from', {})
        to_info = participants.get('to', {})

        md_lines.append(f"| **From** | {self._format_participant(from_info)} |")
        md_lines.append(f"| **To** | {self._format_participant(to_info)} |")

        # Call details
        md_lines.append(f"| **Direction** | {call_info.get('direction', 'Unknown').title()} |")
        md_lines.append(f"| **Duration** | {self._format_duration(call_info.get('duration_seconds', 0))} |")

        if temporal:
            md_lines.append(f"| **Date** | {temporal.get('day_of_week', '')}, {date_str} |")
            md_lines.append(f"| **Time** | {time_str} |")
            md_lines.append(f"| **Business Hours** | {'Yes ✅' if temporal.get('is_business_hours') else 'No ❌'} |")

        if include_technical:
            md_lines.append(f"| **Recording ID** | `{call_info.get('recording_id', 'N/A')}` |")
            md_lines.append(f"| **Call ID** | `{call_id}` |")

        md_lines.append("")

        # Summary if available
        content = document.get('content', {})
        if content.get('summary'):
            md_lines.append("## 📝 Summary")
            md_lines.append("")
            md_lines.append(content['summary'])
            md_lines.append("")

        # Transcript content
        md_lines.append("## 📄 Transcript")
        md_lines.append("")

        transcript_text = content.get('text', '').strip()
        if transcript_text:
            # Check if we have speaker diarization
            segments = content.get('segments', [])
            if segments and any('speaker' in seg for seg in segments):
                md_lines.extend(self._format_diarized_transcript(segments))
            else:
                # Plain transcript
                md_lines.extend(self._format_plain_transcript(transcript_text, segments))
        else:
            md_lines.append("*No transcript available*")

        md_lines.append("")

        # AI Analysis sections
        if include_analysis:
            # Sentiment Analysis
            sentiment = document.get('features', {}).get('sentiment')
            if sentiment:
                md_lines.append("## 😊 Sentiment Analysis")
                md_lines.append("")
                md_lines.append(self._format_sentiment(sentiment))
                md_lines.append("")

            # Topics and Keywords
            keywords = document.get('features', {}).get('keywords', [])
            topics = document.get('features', {}).get('topics', [])
            if keywords or topics:
                md_lines.append("## 🏷️ Topics & Keywords")
                md_lines.append("")
                if topics:
                    md_lines.append("**Topics:** " + ", ".join(topics))
                    md_lines.append("")
                if keywords:
                    md_lines.append("**Keywords:** " + ", ".join(f"`{kw}`" for kw in keywords[:10]))
                    md_lines.append("")

            # Action Items
            action_items = document.get('features', {}).get('action_items', [])
            if action_items:
                md_lines.append("## ✅ Action Items")
                md_lines.append("")
                for item in action_items:
                    md_lines.append(f"- [ ] {item}")
                md_lines.append("")

            # Entities Extracted
            entities = document.get('features', {}).get('entities', {})
            if any(entities.values()):
                md_lines.append("## 🔍 Extracted Information")
                md_lines.append("")

                if entities.get('phone_numbers'):
                    md_lines.append(f"**Phone Numbers:** {', '.join(entities['phone_numbers'])}")
                if entities.get('emails'):
                    md_lines.append(f"**Email Addresses:** {', '.join(entities['emails'])}")
                if entities.get('amounts'):
                    md_lines.append(f"**Amounts:** {', '.join(entities['amounts'])}")
                if entities.get('dates'):
                    md_lines.append(f"**Dates Mentioned:** {', '.join(entities['dates'])}")
                if entities.get('potential_names'):
                    md_lines.append(f"**Names:** {', '.join(entities['potential_names'][:5])}")
                md_lines.append("")

        # Metadata section
        if include_metadata:
            md_lines.append("---")
            md_lines.append("")
            md_lines.append("### Metadata")
            md_lines.append("")

            metadata = document.get('metadata', {})
            language_info = document.get('language_info', {})

            md_lines.append(f"- **Processed:** {metadata.get('created_at', 'Unknown')[:19]}")
            md_lines.append(f"- **Language:** {language_info.get('language', 'en-US')}")

            if include_technical:
                md_lines.append(f"- **Confidence:** {language_info.get('transcription_confidence', 0):.1%}")
                md_lines.append(f"- **Word Count:** {document.get('features', {}).get('metrics', {}).get('word_count', 0)}")
                md_lines.append(f"- **Speaking Rate:** {document.get('features', {}).get('metrics', {}).get('speaking_rate', 0):.1f} words/min")

            md_lines.append(f"- **Source:** {metadata.get('source', 'Unknown')}")
            md_lines.append(f"- **Schema Version:** {document.get('schema_version', '1.0')}")

        return "\n".join(md_lines)

    def _format_participant(self, participant: Dict[str, Any]) -> str:
        """Format participant information"""
        name = participant.get('name')
        number = participant.get('number', 'Unknown')
        extension = participant.get('extension')

        if name and extension:
            return f"{name} (ext. {extension})"
        elif name:
            return f"{name} ({number})"
        elif extension:
            return f"Extension {extension} ({number})"
        else:
            return number

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{int(seconds)} seconds"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}:{secs:02d}"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            secs = int(seconds % 60)
            return f"{hours}:{minutes:02d}:{secs:02d}"

    def _format_plain_transcript(self, text: str, segments: List[Dict]) -> List[str]:
        """Format plain transcript text"""
        lines = []

        # If we have segments with timestamps, use them
        if segments:
            for segment in segments:
                timestamp = self._format_timestamp(segment.get('start', 0))
                seg_text = segment.get('text', '').strip()
                if seg_text:
                    lines.append(f"**[{timestamp}]** {seg_text}")
                    lines.append("")
        else:
            # Just split into paragraphs
            paragraphs = text.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    lines.append(para.strip())
                    lines.append("")

        return lines

    def _format_diarized_transcript(self, segments: List[Dict]) -> List[str]:
        """Format transcript with speaker diarization"""
        lines = []
        current_speaker = None
        speaker_text = []

        for segment in segments:
            speaker = segment.get('speaker', 'Unknown')
            text = segment.get('text', '').strip()
            timestamp = segment.get('start', 0)

            if speaker != current_speaker:
                # Output previous speaker's text
                if current_speaker and speaker_text:
                    lines.append(f"**{current_speaker}:** {' '.join(speaker_text)}")
                    lines.append("")

                current_speaker = speaker
                speaker_text = [text] if text else []
            else:
                if text:
                    speaker_text.append(text)

        # Output last speaker's text
        if current_speaker and speaker_text:
            lines.append(f"**{current_speaker}:** {' '.join(speaker_text)}")
            lines.append("")

        return lines

    def _format_timestamp(self, seconds: float) -> str:
        """Format timestamp in MM:SS format"""
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def _format_sentiment(self, sentiment: Any) -> str:
        """Format sentiment analysis results"""
        if isinstance(sentiment, dict):
            score = sentiment.get('score', 0)
            label = sentiment.get('label', 'Neutral')

            emoji = "😊" if score > 0.3 else "😐" if score > -0.3 else "😟"
            return f"{emoji} **{label}** (Score: {score:.2f})"
        elif isinstance(sentiment, str):
            emoji_map = {
                'positive': '😊',
                'negative': '😟',
                'neutral': '😐',
                'mixed': '🤔'
            }
            emoji = emoji_map.get(sentiment.lower(), '😐')
            return f"{emoji} **{sentiment.title()}**"
        else:
            return str(sentiment)

    def save_markdown_transcript(
        self,
        document: Dict[str, Any],
        output_path: Path,
        **kwargs
    ) -> str:
        """
        Save transcript as markdown file

        Args:
            document: Structured document
            output_path: Path to save markdown file
            **kwargs: Additional arguments for generate_transcript_markdown

        Returns:
            Path to saved file
        """
        markdown_content = self.generate_transcript_markdown(document, **kwargs)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        logger.info(f"Saved markdown transcript to {output_path}")
        return str(output_path)