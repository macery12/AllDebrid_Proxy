"""
Tests for frontend/transcoding.py
"""
import pathlib
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Add the repo root to sys.path so we can import frontend.transcoding
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import frontend.transcoding as tc


class TestMediaExtensions(unittest.TestCase):
    def test_browser_native_mp4(self):
        self.assertTrue(tc.is_browser_compatible("video.mp4"))

    def test_browser_native_webm(self):
        self.assertTrue(tc.is_browser_compatible("video.webm"))

    def test_browser_native_mp3(self):
        self.assertTrue(tc.is_browser_compatible("audio.mp3"))

    def test_browser_native_m4a(self):
        self.assertTrue(tc.is_browser_compatible("audio.m4a"))

    def test_not_native_mkv(self):
        self.assertFalse(tc.is_browser_compatible("movie.mkv"))

    def test_not_native_avi(self):
        self.assertFalse(tc.is_browser_compatible("movie.avi"))

    def test_not_native_wmv(self):
        self.assertFalse(tc.is_browser_compatible("movie.wmv"))

    def test_case_insensitive(self):
        self.assertTrue(tc.is_browser_compatible("video.MP4"))
        self.assertFalse(tc.is_browser_compatible("video.MKV"))

    def test_is_media_file_native(self):
        self.assertTrue(tc.is_media_file("video.mp4"))

    def test_is_media_file_transcodable(self):
        self.assertTrue(tc.is_media_file("video.mkv"))
        self.assertTrue(tc.is_media_file("video.avi"))

    def test_is_media_file_not_media(self):
        self.assertFalse(tc.is_media_file("archive.zip"))
        self.assertFalse(tc.is_media_file("document.pdf"))


class TestJobIdStability(unittest.TestCase):
    def test_same_inputs_produce_same_id(self):
        jid1 = tc.job_id_for("task-abc", "files/video.mkv")
        jid2 = tc.job_id_for("task-abc", "files/video.mkv")
        self.assertEqual(jid1, jid2)

    def test_different_task_produces_different_id(self):
        jid1 = tc.job_id_for("task-abc", "video.mkv")
        jid2 = tc.job_id_for("task-xyz", "video.mkv")
        self.assertNotEqual(jid1, jid2)

    def test_different_relpath_produces_different_id(self):
        jid1 = tc.job_id_for("task-abc", "video1.mkv")
        jid2 = tc.job_id_for("task-abc", "video2.mkv")
        self.assertNotEqual(jid1, jid2)

    def test_id_is_hex_string(self):
        jid = tc.job_id_for("task", "file.mkv")
        self.assertRegex(jid, r'^[0-9a-f]+$')

    def test_id_length(self):
        jid = tc.job_id_for("task", "file.mkv")
        self.assertEqual(len(jid), 16)


class TestSystemLoad(unittest.TestCase):
    def test_get_system_load_returns_float(self):
        load = tc.get_system_load()
        self.assertIsInstance(load, float)
        self.assertGreaterEqual(load, 0.0)

    def test_is_overloaded_false_when_low(self):
        with patch.object(tc, "get_system_load", return_value=0.1):
            self.assertFalse(tc.is_overloaded())

    def test_is_overloaded_true_when_high(self):
        with patch.object(tc, "get_system_load", return_value=999.0):
            self.assertTrue(tc.is_overloaded())


class TestFfmpegAvailability(unittest.TestCase):
    def setUp(self):
        # Reset the cache before each test
        tc._reset_for_testing()

    def test_ffmpeg_available_true_when_binary_works(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            self.assertTrue(tc.ffmpeg_available())

    def test_ffmpeg_available_false_when_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            # Force cache miss
            tc._reset_for_testing()
            self.assertFalse(tc.ffmpeg_available())

    def test_ffmpeg_available_false_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            tc._reset_for_testing()
            self.assertFalse(tc.ffmpeg_available())

    def test_ffmpeg_cache_is_used(self):
        # Warm the cache
        tc._ffmpeg_cache = (True, time.monotonic())
        # subprocess.run should NOT be called if the cache is fresh
        with patch("subprocess.run", side_effect=AssertionError("should not be called")):
            result = tc.ffmpeg_available()
        self.assertTrue(result)


class TestActiveJobCount(unittest.TestCase):
    def setUp(self):
        tc._reset_for_testing()

    def test_empty_registry_gives_zero(self):
        self.assertEqual(tc.active_job_count(), 0)

    def test_queued_job_counts(self):
        with tc._jobs_lock:
            tc._jobs["aaa"] = {"status": "queued"}
        self.assertEqual(tc.active_job_count(), 1)

    def test_transcoding_job_counts(self):
        with tc._jobs_lock:
            tc._jobs["bbb"] = {"status": "transcoding"}
        self.assertEqual(tc.active_job_count(), 1)

    def test_done_job_not_counted(self):
        with tc._jobs_lock:
            tc._jobs["ccc"] = {"status": "done"}
        self.assertEqual(tc.active_job_count(), 0)

    def test_error_job_not_counted(self):
        with tc._jobs_lock:
            tc._jobs["ddd"] = {"status": "error"}
        self.assertEqual(tc.active_job_count(), 0)


class TestGetJob(unittest.TestCase):
    def setUp(self):
        tc._reset_for_testing()

    def test_returns_none_for_unknown(self):
        self.assertIsNone(tc.get_job("nonexistent"))

    def test_returns_copy_not_reference(self):
        with tc._jobs_lock:
            tc._jobs["xyz"] = {"status": "done", "job_id": "xyz"}
        result = tc.get_job("xyz")
        self.assertEqual(result["job_id"], "xyz")
        # Modify the copy; original should be unchanged
        result["status"] = "modified"
        with tc._jobs_lock:
            self.assertEqual(tc._jobs["xyz"]["status"], "done")


class TestStartTranscode(unittest.TestCase):
    def setUp(self):
        tc._reset_for_testing()

    def _fake_source(self, tmp_path, name="test.mkv"):
        p = pathlib.Path(tmp_path) / name
        p.write_bytes(b"fake video content")
        return p

    def test_raises_if_ffmpeg_unavailable(self):
        with patch.object(tc, "ffmpeg_available", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                tc.start_transcode("t1", "video.mkv", pathlib.Path("/fake/path"))
            self.assertIn("ffmpeg", str(ctx.exception).lower())

    def test_raises_if_overloaded(self):
        with patch.object(tc, "ffmpeg_available", return_value=True), \
             patch.object(tc, "active_job_count", return_value=0), \
             patch.object(tc, "is_overloaded", return_value=True):
            with self.assertRaises(RuntimeError) as ctx:
                tc.start_transcode("t1", "video.mkv", pathlib.Path("/fake/path"))
            self.assertIn("load", str(ctx.exception).lower())

    def test_raises_if_at_concurrency_limit(self):
        with patch.object(tc, "ffmpeg_available", return_value=True), \
             patch.object(tc, "active_job_count", return_value=tc.MAX_CONCURRENT_TRANSCODES), \
             patch.object(tc, "is_overloaded", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                tc.start_transcode("t1", "video.mkv", pathlib.Path("/fake/path"))
            self.assertIn("busy", str(ctx.exception).lower())

    def test_returns_existing_queued_job(self):
        jid = tc.job_id_for("t1", "video.mkv")
        existing = {"job_id": jid, "task_id": "t1", "relpath": "video.mkv", "status": "queued"}
        with tc._jobs_lock:
            tc._jobs[jid] = existing
        with patch.object(tc, "ffmpeg_available", return_value=True), \
             patch.object(tc, "cleanup_old_jobs", return_value=0):
            job = tc.start_transcode("t1", "video.mkv", pathlib.Path("/fake/path"))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["job_id"], jid)

    def test_returns_existing_done_job(self):
        jid = tc.job_id_for("t2", "movie.mkv")
        done_job = {"job_id": jid, "task_id": "t2", "relpath": "movie.mkv", "status": "done"}
        with tc._jobs_lock:
            tc._jobs[jid] = done_job
        with patch.object(tc, "ffmpeg_available", return_value=True), \
             patch.object(tc, "cleanup_old_jobs", return_value=0):
            job = tc.start_transcode("t2", "movie.mkv", pathlib.Path("/fake/path"))
        self.assertEqual(job["status"], "done")

    def test_new_job_gets_queued_status(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            src = self._fake_source(tmpdir)
            # Patch _run_transcode so we don't actually call ffmpeg
            with patch.object(tc, "ffmpeg_available", return_value=True), \
                 patch.object(tc, "is_overloaded", return_value=False), \
                 patch.object(tc, "active_job_count", return_value=0), \
                 patch.object(tc, "cleanup_old_jobs", return_value=0), \
                 patch("threading.Thread") as mock_thread:
                mock_thread.return_value = MagicMock()
                job = tc.start_transcode("t3", "sub/video.mkv", src)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["task_id"], "t3")
        self.assertEqual(job["relpath"], "sub/video.mkv")


class TestCleanupOldJobs(unittest.TestCase):
    def setUp(self):
        tc._reset_for_testing()

    def test_removes_old_done_job(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = pathlib.Path(tmpdir) / "old_job"
            out_dir.mkdir()
            old_time = time.time() - tc.TRANSCODE_TTL_SECONDS - 10
            with tc._jobs_lock:
                tc._jobs["old1"] = {
                    "status": "done",
                    "finished_at": old_time,
                    "output_dir": str(out_dir),
                }
            removed = tc.cleanup_old_jobs()
            self.assertEqual(removed, 1)
            self.assertNotIn("old1", tc._jobs)

    def test_keeps_recent_done_job(self):
        with tc._jobs_lock:
            tc._jobs["new1"] = {
                "status": "done",
                "finished_at": time.time(),
                "output_dir": "/nonexistent",
            }
        removed = tc.cleanup_old_jobs()
        self.assertEqual(removed, 0)
        self.assertIn("new1", tc._jobs)

    def test_keeps_active_job(self):
        with tc._jobs_lock:
            tc._jobs["active1"] = {
                "status": "transcoding",
                "finished_at": None,
                "output_dir": "/nonexistent",
            }
        removed = tc.cleanup_old_jobs()
        self.assertEqual(removed, 0)
        self.assertIn("active1", tc._jobs)

    def test_removes_old_error_job(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            old_time = time.time() - tc.TRANSCODE_TTL_SECONDS - 1
            with tc._jobs_lock:
                tc._jobs["err1"] = {
                    "status": "error",
                    "finished_at": old_time,
                    "output_dir": tmpdir,
                }
            removed = tc.cleanup_old_jobs()
            self.assertEqual(removed, 1)


class TestParseTimeProgress(unittest.TestCase):
    def test_standard_format(self):
        line = "frame=  100 fps=25 q=23.0 size=1024kB time=00:01:05.50 bitrate=999"
        result = tc._parse_time_progress(line)
        self.assertAlmostEqual(result, 65.5, places=1)

    def test_hours(self):
        line = "time=01:00:00.00"
        result = tc._parse_time_progress(line)
        self.assertEqual(result, 3600.0)

    def test_no_match(self):
        result = tc._parse_time_progress("some random ffmpeg output line")
        self.assertIsNone(result)


class TestCountSegments(unittest.TestCase):
    def test_counts_ts_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            d = pathlib.Path(tmpdir)
            (d / "seg00000.ts").write_bytes(b"data")
            (d / "seg00001.ts").write_bytes(b"data")
            (d / "index.m3u8").write_text("#EXTM3U\n")
            self.assertEqual(tc._count_segments(d), 2)

    def test_returns_zero_on_missing_dir(self):
        self.assertEqual(tc._count_segments(pathlib.Path("/nonexistent/dir")), 0)

    def test_only_counts_seg_prefix(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            d = pathlib.Path(tmpdir)
            (d / "seg00000.ts").write_bytes(b"data")
            (d / "other.ts").write_bytes(b"data")   # should not count
            self.assertEqual(tc._count_segments(d), 1)


class TestPlayableThreshold(unittest.TestCase):
    """Verify that the playable / segments_ready fields work as expected."""

    def test_new_job_has_playable_false(self):
        tc._reset_for_testing()
        with patch.object(tc, "ffmpeg_available", return_value=True), \
             patch.object(tc, "is_overloaded", return_value=False), \
             patch.object(tc, "active_job_count", return_value=0), \
             patch.object(tc, "cleanup_old_jobs", return_value=0), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                src = pathlib.Path(tmpdir) / "video.mkv"
                src.write_bytes(b"x")
                job = tc.start_transcode("t", "video.mkv", src)
        self.assertFalse(job["playable"])
        self.assertEqual(job["segments_ready"], 0)

    def test_min_segments_constant(self):
        self.assertGreaterEqual(tc.MIN_SEGMENTS_TO_PLAY, 1)

    def test_playable_set_on_done_even_without_progress_line(self):
        """Short files may finish before any stderr progress line; playable must still be set."""
        import tempfile
        tc._reset_for_testing()
        # Create a real output dir so _count_segments works
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = pathlib.Path(tmpdir) / "job99"
            out_dir.mkdir()
            # Pre-populate segments to simulate what ffmpeg would write
            for i in range(tc.MIN_SEGMENTS_TO_PLAY):
                (out_dir / f"seg{i:05d}.ts").write_bytes(b"ts-data")

            jid = "job99test"
            with tc._jobs_lock:
                tc._jobs[jid] = {
                    "job_id": jid,
                    "status": "transcoding",
                    "started_at": time.time(),
                    "finished_at": None,
                    "transcoded_seconds": 0.0,
                    "segments_ready": 0,
                    "playable": False,
                    "output_dir": str(out_dir),
                    "playlist": str(out_dir / "index.m3u8"),
                    "error": None,
                    "pid": None,
                }
            # Simulate the completion path in _run_transcode
            with tc._jobs_lock:
                tc._jobs[jid]["status"] = "done"
                tc._jobs[jid]["playable"] = True
                tc._jobs[jid]["segments_ready"] = tc._count_segments(out_dir)
                tc._jobs[jid]["finished_at"] = time.time()

            job = tc.get_job(jid)
            self.assertTrue(job["playable"])
            self.assertEqual(job["segments_ready"], tc.MIN_SEGMENTS_TO_PLAY)

    def test_playable_transitions_when_segment_threshold_reached(self):
        """Simulate the progress-line loop setting playable=True once enough segments appear."""
        import tempfile
        tc._reset_for_testing()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = pathlib.Path(tmpdir) / "livejob"
            out_dir.mkdir()
            jid = "livejobtest"
            with tc._jobs_lock:
                tc._jobs[jid] = {
                    "job_id": jid,
                    "status": "transcoding",
                    "started_at": time.time(),
                    "finished_at": None,
                    "transcoded_seconds": 0.0,
                    "segments_ready": 0,
                    "playable": False,
                    "output_dir": str(out_dir),
                    "playlist": str(out_dir / "index.m3u8"),
                    "error": None,
                    "pid": None,
                }

            # Write one segment — not yet playable
            (out_dir / "seg00000.ts").write_bytes(b"ts-data")
            seg_count = tc._count_segments(out_dir)
            with tc._jobs_lock:
                tc._jobs[jid]["segments_ready"] = seg_count
                if not tc._jobs[jid].get("playable", False) and seg_count >= tc.MIN_SEGMENTS_TO_PLAY:
                    tc._jobs[jid]["playable"] = True

            self.assertFalse(tc.get_job(jid)["playable"])
            self.assertEqual(tc.get_job(jid)["segments_ready"], 1)

            # Write the second segment — now meets MIN_SEGMENTS_TO_PLAY
            (out_dir / "seg00001.ts").write_bytes(b"ts-data")
            seg_count = tc._count_segments(out_dir)
            with tc._jobs_lock:
                tc._jobs[jid]["segments_ready"] = seg_count
                if not tc._jobs[jid].get("playable", False) and seg_count >= tc.MIN_SEGMENTS_TO_PLAY:
                    tc._jobs[jid]["playable"] = True

            self.assertTrue(tc.get_job(jid)["playable"])
            self.assertEqual(tc.get_job(jid)["segments_ready"], 2)


class TestHeartbeatAndCancel(unittest.TestCase):
    def setUp(self):
        tc._reset_for_testing()
        self._make_job("hb01", "transcoding")

    def _make_job(self, jid, status):
        with tc._jobs_lock:
            tc._jobs[jid] = {
                "job_id": jid,
                "task_id": "t",
                "relpath": "v.mkv",
                "status": status,
                "queued_at": time.time(),
                "started_at": time.time(),
                "finished_at": None,
                "transcoded_seconds": 0.0,
                "segments_ready": 0,
                "playable": False,
                "output_dir": "/tmp/fake",
                "playlist": None,
                "error": None,
                "pid": None,
                "last_heartbeat": time.time(),
            }

    def test_touch_heartbeat_updates_timestamp(self):
        before = time.time()
        time.sleep(0.01)
        ok = tc.touch_heartbeat("hb01")
        self.assertTrue(ok)
        with tc._jobs_lock:
            hb = tc._jobs["hb01"]["last_heartbeat"]
        self.assertGreater(hb, before)

    def test_touch_heartbeat_returns_false_for_unknown(self):
        self.assertFalse(tc.touch_heartbeat("no-such-job"))

    def test_cancel_job_marks_cancelled(self):
        result = tc.cancel_job("hb01")
        self.assertTrue(result)
        job = tc.get_job("hb01")
        self.assertEqual(job["status"], "cancelled")
        self.assertIsNotNone(job["finished_at"])

    def test_cancel_job_no_pid_still_works(self):
        # Job has no pid yet (still queued)
        self._make_job("hb02", "queued")
        result = tc.cancel_job("hb02")
        self.assertTrue(result)
        self.assertEqual(tc.get_job("hb02")["status"], "cancelled")

    def test_cancel_job_returns_false_for_done(self):
        self._make_job("hb03", "done")
        with tc._jobs_lock:
            tc._jobs["hb03"]["finished_at"] = time.time()
        result = tc.cancel_job("hb03")
        self.assertFalse(result)

    def test_cancel_job_returns_false_for_unknown(self):
        self.assertFalse(tc.cancel_job("no-such-job"))

    def test_stale_heartbeat_kills_job(self):
        # Set last_heartbeat to far in the past
        with tc._jobs_lock:
            tc._jobs["hb01"]["last_heartbeat"] = time.time() - tc.HEARTBEAT_TIMEOUT - 10
        tc._kill_stale_jobs()
        self.assertEqual(tc.get_job("hb01")["status"], "cancelled")

    def test_fresh_heartbeat_not_killed(self):
        # Recent heartbeat — must not be cancelled
        tc._kill_stale_jobs()
        self.assertEqual(tc.get_job("hb01")["status"], "transcoding")

    def test_no_heartbeat_field_not_killed(self):
        # Job without last_heartbeat (e.g. created without heartbeat field)
        with tc._jobs_lock:
            tc._jobs["hb01"].pop("last_heartbeat")
        tc._kill_stale_jobs()
        self.assertEqual(tc.get_job("hb01")["status"], "transcoding")

    def test_cleanup_removes_cancelled_jobs(self):
        old_time = time.time() - tc.TRANSCODE_TTL_SECONDS - 10
        with tc._jobs_lock:
            tc._jobs["hb01"]["status"] = "cancelled"
            tc._jobs["hb01"]["finished_at"] = old_time
            tc._jobs["hb01"]["output_dir"] = "/nonexistent"
        removed = tc.cleanup_old_jobs()
        self.assertEqual(removed, 1)
        self.assertNotIn("hb01", tc._jobs)

    def test_new_job_has_last_heartbeat(self):
        tc._reset_for_testing()
        import tempfile
        before = time.time()
        with patch.object(tc, "ffmpeg_available", return_value=True), \
             patch.object(tc, "is_overloaded", return_value=False), \
             patch.object(tc, "active_job_count", return_value=0), \
             patch.object(tc, "cleanup_old_jobs", return_value=0), \
             patch("threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            with tempfile.TemporaryDirectory() as tmpdir:
                src = pathlib.Path(tmpdir) / "video.mkv"
                src.write_bytes(b"x")
                job = tc.start_transcode("t", "video.mkv", src)
        self.assertIn("last_heartbeat", job)
        self.assertGreaterEqual(job["last_heartbeat"], before)


if __name__ == "__main__":
    unittest.main()
