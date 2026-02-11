"""YouTube parser: fetches metadata, statistics, and transcripts."""

import logging
import re
import time
from typing import Optional

import isodate
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from src.config_loader import get_project_root, load_config
from src.parsers.base_parser import BaseParser


class YouTubeParser(BaseParser):
    """
    Parser for YouTube video integrations.

    Fetches video metadata via YouTube Data API v3 and transcripts
    via youtube-transcript-api.  Supports batching (50 IDs per API
    call), exponential-backoff retries, and graceful error recovery.
    """

    def __init__(self, config: dict = None):
        super().__init__(config)
        yt_cfg = self.config["youtube"]

        api_key = yt_cfg.get("api_key", "")
        if not api_key:
            raise ValueError(
                "YouTube API key not found. Set the YOUTUBE_API_KEY "
                "environment variable or check config.yaml."
            )

        self._youtube_client = build("youtube", "v3", developerKey=api_key)
        self._transcript_api = YouTubeTranscriptApi()
        self._languages = yt_cfg.get("transcript_languages", ["uk", "ru", "en"])
        self._batch_size = yt_cfg.get("batch_size", 50)
        self._output_file = yt_cfg.get("output_file")

    @property
    def platform_name(self) -> str:
        return "youtube"

    # ── Public API ─────────────────────────────────────────────

    def parse_single(self, url: str) -> dict:
        """Parse a single YouTube video URL."""
        video_id = self.extract_video_id(url)
        if not video_id:
            return {
                "url": url,
                "platform": "youtube",
                "error": f"Could not extract video_id from URL: {url}",
            }

        metadata = self._fetch_video_metadata(video_id)
        if "error" in metadata:
            metadata["url"] = url
            return metadata

        channel_id = metadata.get("channel_id")
        if channel_id:
            metadata["channel_subscribers"] = self._fetch_channel_subscribers(
                channel_id
            )

        transcript_data = self._fetch_transcript(video_id)
        metadata.update(transcript_data)
        metadata["url"] = url
        return metadata

    def parse_batch(self, urls: list[str]) -> list[dict]:
        """
        Optimized batch parsing: fetches video metadata in groups of 50,
        batch-fetches channel subscribers, then fetches transcripts one
        by one.
        """
        # Step 1 — extract video IDs
        url_id_pairs: list[tuple[str, str]] = []
        results: list[dict] = []
        for url in urls:
            vid = self.extract_video_id(url)
            if vid:
                url_id_pairs.append((url, vid))
            else:
                results.append(
                    {
                        "url": url,
                        "platform": "youtube",
                        "error": f"Could not extract video_id from URL: {url}",
                    }
                )

        # Step 2 — batch-fetch metadata (groups of 50)
        video_ids = [vid for _, vid in url_id_pairs]
        metadata_map = self._batch_fetch_metadata(video_ids)

        # Step 3 — batch-fetch channel subscribers
        channel_ids = set()
        for vid in video_ids:
            cid = metadata_map.get(vid, {}).get("channel_id")
            if cid:
                channel_ids.add(cid)
        subscriber_map = self._batch_fetch_subscribers(list(channel_ids))

        # Step 4 — fetch transcripts individually
        total = len(url_id_pairs)
        for idx, (url, vid) in enumerate(url_id_pairs, 1):
            meta = metadata_map.get(vid)
            if meta is None:
                results.append(
                    {
                        "url": url,
                        "video_id": vid,
                        "platform": "youtube",
                        "error": "Video not found in API response",
                    }
                )
                continue

            meta["url"] = url

            # Attach subscriber count
            cid = meta.get("channel_id")
            if cid and cid in subscriber_map:
                meta["channel_subscribers"] = subscriber_map[cid]

            # Fetch transcript
            self.logger.info(
                "Fetching transcript %d/%d for %s", idx, total, vid
            )
            transcript_data = self._safe_fetch_transcript(vid)
            meta.update(transcript_data)

            results.append(meta)

        return results

    def run(self, urls: list[str]) -> list[dict]:
        """Full parse pipeline: parse batch and save to output file."""
        results = self.parse_batch(urls)

        if self._output_file:
            output_path = str(get_project_root() / self._output_file)
            self.save_results(results, output_path)

        success = sum(1 for r in results if "error" not in r)
        failed = sum(1 for r in results if "error" in r)
        with_transcript = sum(
            1 for r in results if r.get("has_transcript", False)
        )
        self.logger.info(
            "YouTube parsing complete: %d success, %d failed, "
            "%d with transcript (of %d total)",
            success, failed, with_transcript, len(results),
        )
        return results

    # ── Video ID Extraction ────────────────────────────────────

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """
        Extract YouTube video ID from various URL formats.

        Handles: watch?v=, youtu.be/, /embed/, /shorts/
        """
        patterns = [
            r"(?:youtube\.com/watch\?.*v=)([a-zA-Z0-9_-]{11})",
            r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
            r"(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
            r"(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    # ── YouTube Data API Calls ─────────────────────────────────

    def _fetch_video_metadata(self, video_id: str) -> dict:
        """Fetch metadata for a single video."""
        try:
            response = (
                self._youtube_client.videos()
                .list(part="snippet,statistics,contentDetails", id=video_id)
                .execute()
            )
        except HttpError as e:
            return {
                "video_id": video_id,
                "platform": "youtube",
                "error": f"YouTube API error: {e.resp.status} {e.reason}",
            }

        items = response.get("items", [])
        if not items:
            return {
                "video_id": video_id,
                "platform": "youtube",
                "error": "Video not found (may be private or deleted)",
            }

        return self._parse_video_item(items[0])

    def _batch_fetch_metadata(self, video_ids: list[str]) -> dict:
        """
        Batch-fetch video metadata in groups of up to 50 IDs.

        Returns dict mapping video_id -> parsed metadata dict.
        """
        metadata_map: dict[str, dict] = {}

        for i in range(0, len(video_ids), self._batch_size):
            batch = video_ids[i : i + self._batch_size]
            ids_str = ",".join(batch)

            self.logger.info(
                "Fetching metadata batch %d–%d of %d",
                i + 1,
                min(i + self._batch_size, len(video_ids)),
                len(video_ids),
            )

            try:
                response = (
                    self._youtube_client.videos()
                    .list(
                        part="snippet,statistics,contentDetails",
                        id=ids_str,
                    )
                    .execute()
                )
            except HttpError as e:
                self.logger.error("Batch metadata fetch failed: %s", str(e))
                for vid in batch:
                    metadata_map[vid] = {
                        "video_id": vid,
                        "platform": "youtube",
                        "error": f"Batch API error: {e.resp.status}",
                    }
                continue

            for item in response.get("items", []):
                parsed = self._parse_video_item(item)
                metadata_map[parsed["video_id"]] = parsed

        return metadata_map

    def _parse_video_item(self, item: dict) -> dict:
        """Parse a single video resource from the API response."""
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})

        # Parse ISO 8601 duration
        duration_iso = content.get("duration", "PT0S")
        try:
            duration_td = isodate.parse_duration(duration_iso)
            duration_seconds = int(duration_td.total_seconds())
        except Exception:
            duration_seconds = 0

        # Get best available thumbnail
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url", "")
        )

        return {
            "video_id": item["id"],
            "platform": "youtube",
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channel_name": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "publish_date": snippet.get("publishedAt", ""),
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "duration_iso": duration_iso,
            "duration_seconds": duration_seconds,
            "tags": snippet.get("tags", []),
            "thumbnail_url": thumbnail_url,
            "category_id": snippet.get("categoryId", ""),
        }

    # ── Channel Subscribers ────────────────────────────────────

    def _fetch_channel_subscribers(self, channel_id: str) -> int:
        """Fetch subscriber count for a single channel."""
        try:
            response = (
                self._youtube_client.channels()
                .list(part="statistics", id=channel_id)
                .execute()
            )
            items = response.get("items", [])
            if items:
                stats = items[0].get("statistics", {})
                if stats.get("hiddenSubscriberCount", False):
                    return -1
                return int(stats.get("subscriberCount", 0))
        except HttpError as e:
            self.logger.warning(
                "Failed to fetch subscribers for channel %s: %s",
                channel_id,
                str(e),
            )
        return 0

    def _batch_fetch_subscribers(
        self, channel_ids: list[str]
    ) -> dict[str, int]:
        """Batch-fetch subscriber counts for channels (groups of 50)."""
        sub_map: dict[str, int] = {}

        for i in range(0, len(channel_ids), self._batch_size):
            batch = channel_ids[i : i + self._batch_size]
            ids_str = ",".join(batch)

            try:
                response = (
                    self._youtube_client.channels()
                    .list(part="statistics", id=ids_str)
                    .execute()
                )
                for item in response.get("items", []):
                    cid = item["id"]
                    stats = item.get("statistics", {})
                    if stats.get("hiddenSubscriberCount", False):
                        sub_map[cid] = -1
                    else:
                        sub_map[cid] = int(stats.get("subscriberCount", 0))
            except HttpError as e:
                self.logger.warning(
                    "Batch subscriber fetch failed: %s", str(e)
                )

        return sub_map

    # ── Transcript Fetching ────────────────────────────────────

    def _fetch_transcript(self, video_id: str) -> dict:
        """
        Fetch transcript for a video with language fallback.

        Returns dict with: transcript_full, transcript_text,
        has_transcript, transcript_language, transcript_error.
        """
        try:
            transcript = self._transcript_api.fetch(
                video_id, languages=self._languages
            )

            entries = [
                {
                    "text": entry.text,
                    "start": entry.start,
                    "duration": entry.duration,
                }
                for entry in transcript
            ]

            full_text = " ".join(entry["text"] for entry in entries)

            language = self._detect_transcript_language(video_id)

            return {
                "transcript_full": entries,
                "transcript_text": full_text,
                "has_transcript": True,
                "transcript_language": language,
                "transcript_error": None,
            }

        except TranscriptsDisabled:
            return self._transcript_error_result(
                "Transcripts are disabled for this video"
            )
        except NoTranscriptFound:
            return self._transcript_error_result(
                f"No transcript found in languages: {self._languages}"
            )
        except VideoUnavailable:
            return self._transcript_error_result(
                "Video is unavailable (private or deleted)"
            )
        except Exception as e:
            return self._transcript_error_result(
                f"Unexpected transcript error: {str(e)}"
            )

    def _safe_fetch_transcript(self, video_id: str) -> dict:
        """
        Fetch transcript with retry logic.
        Skips retries for permanent errors (disabled, not found).
        """
        for attempt in range(1, self.max_retries + 1):
            result = self._fetch_transcript(video_id)
            if result["has_transcript"]:
                return result

            error_msg = result.get("transcript_error", "")
            # Don't retry permanent errors
            if "disabled" in error_msg or "not found" in error_msg.lower() or "unavailable" in error_msg.lower():
                return result

            if attempt < self.max_retries:
                wait = min(self.backoff_base ** attempt, self.backoff_max)
                self.logger.warning(
                    "Transcript attempt %d/%d failed for %s, retrying in %.1fs",
                    attempt,
                    self.max_retries,
                    video_id,
                    wait,
                )
                time.sleep(wait)

        return result

    def _detect_transcript_language(self, video_id: str) -> Optional[str]:
        """Try to detect which language the fetched transcript is in."""
        try:
            transcript_list = self._transcript_api.list(video_id)
            for t in transcript_list:
                if t.language_code in self._languages:
                    return t.language_code
        except Exception:
            pass
        return None

    @staticmethod
    def _transcript_error_result(error_msg: str) -> dict:
        return {
            "transcript_full": [],
            "transcript_text": "",
            "has_transcript": False,
            "transcript_language": None,
            "transcript_error": error_msg,
        }
