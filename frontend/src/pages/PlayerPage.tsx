import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { tasksApi } from '../api/tasks';
import { APIError } from '../api/client';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyState } from '../components/EmptyState';
import { encodePathSegments, formatBytes } from '../lib/utils';
import type { FileEntry } from '../types';
import styles from './PlayerPage.module.css';

export function PlayerPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const [searchParams] = useSearchParams();
  const relpath = searchParams.get('file') ?? '';
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('Ready');

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    tasksApi
      .getFiles(taskId)
      .then((data) => setEntries(data.entries))
      .catch((e: unknown) => setError(e instanceof APIError ? e.message : 'Failed to load file info'))
      .finally(() => setLoading(false));
  }, [taskId]);

  const file = useMemo(() => entries.find((entry) => entry.rel === relpath), [entries, relpath]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !taskId || !relpath) return;

    const storageKey = `video-position-${taskId}-${relpath}`;
    const onLoadedMetadata = () => {
      const savedTime = localStorage.getItem(storageKey);
      if (savedTime) {
        const time = Number(savedTime);
        if (!Number.isNaN(time) && time > 0 && time < video.duration) {
          video.currentTime = time;
          setStatus(`Resumed at ${formatTime(time)}`);
        }
      }
    };
    const onPlay = () => setStatus('Playing');
    const onPause = () => {
      localStorage.setItem(storageKey, String(video.currentTime));
      setStatus('Paused');
    };
    const onSeeking = () => setStatus('Seeking');
    const onSeeked = () => {
      localStorage.setItem(storageKey, String(video.currentTime));
      setStatus(`At ${formatTime(video.currentTime)}`);
    };
    const onWaiting = () => setStatus('Buffering');
    const onCanPlay = () => setStatus(video.paused ? 'Ready' : 'Playing');
    const onEnded = () => {
      localStorage.removeItem(storageKey);
      setStatus('Ended');
    };
    const onError = () => setStatus('Playback error');

    const interval = window.setInterval(() => {
      if (!video.paused) {
        localStorage.setItem(storageKey, String(video.currentTime));
      }
    }, 10000);

    video.addEventListener('loadedmetadata', onLoadedMetadata);
    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('seeking', onSeeking);
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('canplay', onCanPlay);
    video.addEventListener('ended', onEnded);
    video.addEventListener('error', onError);

    return () => {
      window.clearInterval(interval);
      video.removeEventListener('loadedmetadata', onLoadedMetadata);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('seeking', onSeeking);
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('waiting', onWaiting);
      video.removeEventListener('canplay', onCanPlay);
      video.removeEventListener('ended', onEnded);
      video.removeEventListener('error', onError);
    };
  }, [taskId, relpath]);

  if (!relpath) {
    return <EmptyState message="No file selected for playback." />;
  }

  const encodedRelpath = encodePathSegments(relpath);
  const streamUrl = taskId ? `/files/${taskId}/stream/${encodedRelpath}` : '';
  const downloadUrl = taskId ? `/files/${taskId}/raw/${encodedRelpath}` : '';

  return (
    <div className={styles.page}>
      <section className={styles.topBar}>
        <div>
          <h1 className={styles.title}>{file?.rel.split('/').pop() ?? 'Player'}</h1>
          <p className={styles.subtitle}>{relpath}</p>
        </div>
        <div className={styles.actions}>
          {taskId && <Link to={`/tasks/${taskId}/files`} className="btn">Back to Files</Link>}
          <a className="btn btn-good" href={downloadUrl} download>
            Download
          </a>
        </div>
      </section>

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <section className={styles.panel}>
        {loading ? (
          <div className="flex flex-center gap-2 muted" style={{ padding: 40 }}>
            <span className="spinner" />
            Loading player…
          </div>
        ) : !file ? (
          <EmptyState message="File not found." />
        ) : (
          <>
            <div className={styles.videoWrap}>
              <video ref={videoRef} controls preload="metadata" playsInline className={styles.video}>
                <source src={streamUrl} />
              </video>
            </div>
            <div className={styles.metaGrid}>
              <div className={styles.metaItem}><span>File</span><strong>{file.rel}</strong></div>
              <div className={styles.metaItem}><span>Size</span><strong>{formatBytes(file.size)}</strong></div>
              <div className={styles.metaItem}><span>Status</span><strong>{status}</strong></div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(remainingSeconds).padStart(2, '0')}`;
}
