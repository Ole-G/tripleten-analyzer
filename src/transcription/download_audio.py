"""Download audio from YouTube, Instagram, and TikTok using yt-dlp."""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


def download_audio(
    url: str,
    output_dir: str,
    video_id: str,
    cookies_file: str = None,
    timeout: int = 120,
) -> dict:
    """
    Download audio from a video URL using yt-dlp.

    Args:
        url: Video URL (YouTube, Instagram, TikTok).
        output_dir: Directory to save the audio file.
        video_id: Unique video identifier (used as filename).
        cookies_file: Path to cookies file for restricted content.
        timeout: Subprocess timeout in seconds.

    Returns:
        Dict with keys: success, audio_path, error.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Check if already downloaded
    output_path = os.path.join(output_dir, f"{video_id}.mp3")
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        logger.debug("Audio already exists, skipping: %s", output_path)
        return {"success": True, "audio_path": output_path, "error": None}

    # Check yt-dlp is available
    if not shutil.which("yt-dlp"):
        return {
            "success": False,
            "audio_path": None,
            "error": "yt-dlp not found. Install with: pip install yt-dlp",
        }

    output_template = os.path.join(output_dir, f"{video_id}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--output", output_template,
        "--no-playlist",
        "--socket-timeout", "30",
        "--retries", "3",
        "--quiet",
        "--no-warnings",
    ]

    if cookies_file:
        cmd.extend(["--cookies", cookies_file])

    cmd.append(url)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )

        if result.returncode != 0:
            # For Instagram: retry with cookies if not already using them
            if "instagram.com" in url.lower() and not cookies_file:
                logger.debug(
                    "Instagram download failed without cookies, "
                    "set instagram_cookies_file in config if needed"
                )

            error_msg = (result.stderr or result.stdout or "Unknown error")[:500]
            return {
                "success": False,
                "audio_path": None,
                "error": f"yt-dlp exit code {result.returncode}: {error_msg}",
            }

        # Verify file was created
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return {"success": True, "audio_path": output_path, "error": None}

        return {
            "success": False,
            "audio_path": None,
            "error": "yt-dlp completed but output file not found",
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "audio_path": None,
            "error": f"Download timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "success": False,
            "audio_path": None,
            "error": str(e),
        }


def download_all_audio(
    items: list[dict],
    output_dir: str,
    cookies_file: str = None,
) -> list[dict]:
    """
    Download audio for multiple videos.

    Args:
        items: List of dicts with keys: video_id, url, platform.
        output_dir: Directory to save audio files.
        cookies_file: Path to cookies file for restricted content.

    Returns:
        List of result dicts, each with video_id, platform, and download result.
    """
    results = []
    success_count = 0
    fail_count = 0

    for i, item in enumerate(items, 1):
        video_id = item["video_id"]
        url = item["url"]
        platform = item.get("platform", "unknown")

        logger.info(
            "Downloading %d/%d: %s (%s)",
            i, len(items), video_id, platform,
        )

        result = download_audio(
            url=url,
            output_dir=output_dir,
            video_id=video_id,
            cookies_file=cookies_file,
        )
        result["video_id"] = video_id
        result["platform"] = platform
        results.append(result)

        if result["success"]:
            success_count += 1
        else:
            fail_count += 1
            logger.warning(
                "Download failed for %s: %s", video_id, result["error"],
            )

    logger.info(
        "Download complete: %d success, %d failed out of %d",
        success_count, fail_count, len(items),
    )
    return results
