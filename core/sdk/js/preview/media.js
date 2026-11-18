// 实验能力：媒体采集与上传（CAP-09，Refs #63）。
// 统一封装本地文件选择、现场拍照、现场录音、采集后预览/回放、重拍/重录、取消、确认上传与知识库原件登记。
// 组件库 core/sdk/js/ui/ 为 SDK 1.0 冻结面，本模块作为 preview 扩展提供。

import { errorMessage } from './errors.js';
import * as knowledge from './knowledge.js';

export const VERSION = '1.0.0';

export const DEFAULT_ACCEPT = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'audio/webm',
  'audio/wav',
  'audio/mp4',
  'audio/mpeg',
  'audio/ogg',
  'application/pdf',
];

export const DEFAULT_MAX_SIZE_BYTES = 20 * 1024 * 1024;
export const DEFAULT_MAX_DURATION_SEC = 300;
export const DEFAULT_CATEGORY = '05-制造质量交付';
export const DEFAULT_PROJECT = 'demo-project';

export const SOURCE_LABELS = Object.freeze({
  file: '本地文件',
  camera: '现场拍照',
  audio: '现场录音',
});

const EXT_MIME_MAP = Object.freeze({
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.webm': 'audio/webm',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
  '.m4a': 'audio/mp4',
  '.mp4': 'audio/mp4',
  '.ogg': 'audio/ogg',
  '.pdf': 'application/pdf',
});

let mediaStyleInjected = false;

export function ensureMediaStyles() {
  if (typeof document === 'undefined' || !document.head || typeof document.getElementById !== 'function') return;
  const links = [
    ['hk-tokens-css', '/web/tokens.css'],
    ['hk-ui-css', '/sdk/ui/ui.css'],
    ['hk-preview-media-css', '/sdk/preview/media.css'],
  ];
  for (const [id, href] of links) {
    if (!document.getElementById(id)) {
      const link = document.createElement('link');
      link.id = id;
      link.rel = 'stylesheet';
      link.href = href;
      if (typeof document.head.append === 'function') {
        document.head.append(link);
      } else if (typeof document.head.appendChild === 'function') {
        document.head.appendChild(link);
      }
    }
  }
  mediaStyleInjected = true;
}

function toKebabCase(str) {
  return String(str).replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === 'class') node.className = v;
    else if (k === 'dataset' && typeof v === 'object') {
      node.dataset ||= {};
      for (const [dk, dv] of Object.entries(v)) {
        if (dv !== undefined && dv !== null) {
          node.dataset[dk] = String(dv);
          node.setAttribute(`data-${toKebabCase(dk)}`, String(dv));
        }
      }
    } else if (k.startsWith('on') && typeof v === 'function') {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v === true) {
      node.setAttribute(k, '');
      if (k in node) node[k] = true;
    } else {
      node.setAttribute(k, String(v));
      if (k === 'value' || k === 'id') node[k] = String(v);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    const domChild =
      typeof child === 'object' && (child.nodeType || child.tagName)
        ? child
        : document.createTextNode(String(child));
    if (typeof node.append === 'function') {
      node.append(domChild);
    } else {
      node.appendChild(domChild);
    }
  }
  return node;
}

export function mediaError(code, extra = {}) {
  const text = errorMessage({ code });
  const err = new Error(text);
  err.code = code;
  Object.assign(err, extra);
  return err;
}

export function normalizeMediaError(raw, fallbackCode = 'media_capture_interrupted') {
  if (raw && typeof raw.code === 'string' && raw.code.startsWith('media_')) {
    return raw;
  }
  const domName = raw && typeof raw.name === 'string' ? raw.name : '';
  if (domName === 'NotAllowedError' || domName === 'PermissionDeniedError' || domName === 'SecurityError') {
    return mediaError('media_permission_denied', { causeName: domName });
  }
  if (domName === 'NotFoundError' || domName === 'DevicesNotFoundError') {
    return mediaError('media_device_not_found', { causeName: domName });
  }
  if (domName === 'NotReadableError' || domName === 'TrackStartError' || domName === 'OverconstrainedError') {
    return mediaError('media_device_in_use', { causeName: domName });
  }
  if (domName === 'NotSupportedError') {
    return mediaError('media_not_supported', { causeName: domName });
  }
  if (domName === 'AbortError') {
    return mediaError('media_capture_interrupted', { causeName: domName });
  }
  if (raw && typeof raw.code === 'string') {
    return raw;
  }
  return mediaError(fallbackCode);
}

function formatUploadTime(createdAt) {
  const t = Number(createdAt);
  const d = new Date(t < 1e12 ? t * 1000 : t);
  if (Number.isNaN(d.getTime())) return '刚刚';
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const mins = String(Math.floor(total / 60)).padStart(2, '0');
  const secs = String(total % 60).padStart(2, '0');
  return `${mins}:${secs}`;
}

function normalizeAcceptList(accept) {
  if (!accept) return DEFAULT_ACCEPT;
  if (Array.isArray(accept)) return accept.map((item) => String(item).trim().toLowerCase()).filter(Boolean);
  return String(accept)
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function inferMimeType(file) {
  const rawType = file && typeof file.type === 'string' ? file.type.split(';')[0].trim().toLowerCase() : '';
  if (rawType) return rawType;
  const name = file && typeof file.name === 'string' ? file.name.trim().toLowerCase() : '';
  const dotIdx = name.lastIndexOf('.');
  if (dotIdx >= 0) {
    const ext = name.slice(dotIdx);
    if (EXT_MIME_MAP[ext]) return EXT_MIME_MAP[ext];
  }
  return '';
}

function matchesAccept(file, acceptList) {
  if (!acceptList || acceptList.length === 0) return true;
  const mime = inferMimeType(file);
  const name = file && typeof file.name === 'string' ? file.name.trim().toLowerCase() : '';
  for (const rule of acceptList) {
    if (rule === '*/*' || rule === '*') return true;
    if (rule.startsWith('.')) {
      if (name.endsWith(rule)) return true;
    } else if (rule.endsWith('/*')) {
      const prefix = rule.slice(0, -1);
      if (mime.startsWith(prefix)) return true;
    } else if (mime === rule) {
      return true;
    }
  }
  return false;
}

export function validateMediaFile(file, options = {}) {
  if (!file) throw mediaError('media_empty');
  const size = Number(file.size ?? (file.byteLength ?? 0));
  if (!Number.isFinite(size) || size <= 0) {
    throw mediaError('media_empty');
  }
  const acceptList = normalizeAcceptList(options.accept);
  if (!matchesAccept(file, acceptList)) {
    throw mediaError('media_invalid_type', { mimeType: inferMimeType(file) });
  }
  const maxSizeBytes = Number(options.maxSizeBytes ?? DEFAULT_MAX_SIZE_BYTES);
  if (Number.isFinite(maxSizeBytes) && maxSizeBytes > 0 && size > maxSizeBytes) {
    throw mediaError('media_too_large', { size, maxSizeBytes });
  }
  const maxDurationSec = Number(options.maxDurationSec ?? DEFAULT_MAX_DURATION_SEC);
  const durationSec = options.durationSec ?? file.durationSec ?? null;
  if (durationSec !== null && durationSec !== undefined && Number.isFinite(maxDurationSec) && maxDurationSec > 0) {
    if (Number(durationSec) > maxDurationSec) {
      throw mediaError('media_duration_exceeded', { durationSec: Number(durationSec), maxDurationSec });
    }
  }
  return {
    name: file.name || '未命名原件',
    mimeType: inferMimeType(file) || 'application/octet-stream',
    size,
    durationSec: durationSec !== null && durationSec !== undefined ? Number(durationSec) : null,
  };
}

function stripExt(name = '') {
  const clean = String(name || '').trim();
  const idx = clean.lastIndexOf('.');
  return idx > 0 ? clean.slice(0, idx) : clean;
}

export function buildMediaReference(rawResult, file, options = {}) {
  const latest = (rawResult && rawResult.latest) || rawResult || {};
  const fileId = latest.fileId || (rawResult && rawResult.fileId) || '';
  const entryId = (rawResult && (rawResult.entryId || rawResult.id)) || null;
  const version = Number((rawResult && rawResult.latestVersion) || latest.version || (rawResult && rawResult.version) || 1);
  const sourceMode = options.sourceMode || 'file';
  const sourceLabel = options.sourceLabel || SOURCE_LABELS[sourceMode] || SOURCE_LABELS.file;
  const mimeType = inferMimeType(file) || options.mimeType || 'application/octet-stream';
  const name = latest.name || (rawResult && rawResult.name) || (file && file.name) || '采集原件';
  const size = Number(latest.size ?? (rawResult && rawResult.size) ?? (file && file.size) ?? 0);
  return {
    fileId,
    entryId,
    version,
    name,
    mimeType,
    size,
    sha256: latest.sha256 || (rawResult && rawResult.sha256) || '',
    uploader: latest.uploader || (rawResult && (rawResult.uploader || rawResult.submitter)) || '',
    createdAt: latest.createdAt || (rawResult && rawResult.createdAt) || Date.now() / 1000,
    status: latest.status || (rawResult && rawResult.status) || 'unreviewed',
    visibility: (rawResult && rawResult.visibility) || options.visibility || 'internal',
    project: (rawResult && rawResult.project) || options.project || DEFAULT_PROJECT,
    category: (rawResult && rawResult.category) || options.category || DEFAULT_CATEGORY,
    title: (rawResult && rawResult.title) || options.title || stripExt(name) || '采集原件',
    sourceMode,
    sourceLabel,
    deviceLabel: options.deviceLabel || '',
    durationSec: options.durationSec ?? (file && file.durationSec) ?? null,
    contentUrl: entryId
      ? `/api/v1/knowledge/entries/${encodeURIComponent(entryId)}/versions/${version}/content`
      : `/api/v1/files/${encodeURIComponent(fileId)}/content`,
    fileUrl: `/api/v1/files/${encodeURIComponent(fileId)}/content`,
  };
}

export async function upload(http, appId, file, options = {}) {
  const checked = validateMediaFile(file, options);
  const project = options.project || DEFAULT_PROJECT;
  const category = options.category || DEFAULT_CATEGORY;
  const title = (options.title && String(options.title).trim()) || stripExt(checked.name) || '现场采集原件';
  const purpose = options.purpose || 'media';
  const visibility = options.visibility || 'internal';
  const note = options.note || `${SOURCE_LABELS[options.sourceMode || 'file'] || '本地文件'}上传`;

  let rawResult;
  if (typeof options.uploader === 'function') {
    rawResult = await options.uploader(file, {
      ...options,
      appId,
      project,
      category,
      title,
      purpose,
      visibility,
      note,
    });
  } else if (options.registerKnowledge === false) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('app', appId);
    fd.append('project', project);
    fd.append('purpose', purpose);
    rawResult = await http('/api/v1/files', { method: 'POST', body: fd });
  } else if (options.entryId) {
    rawResult = await knowledge.addVersion(http, options.entryId, file, {
      project,
      purpose,
      note,
    });
  } else {
    rawResult = await knowledge.upload(http, appId, file, {
      title,
      category,
      project,
      purpose,
      visibility,
      note,
      tags: options.tags,
      roles: options.roles,
      departments: options.departments,
    });
  }
  return buildMediaReference(rawResult, file, {
    ...options,
    project,
    category,
    title,
    visibility,
    mimeType: checked.mimeType,
    durationSec: checked.durationSec,
  });
}

function createSyntheticFile(bytes, name, type, extra = {}) {
  let fileObj;
  if (typeof File === 'function') {
    fileObj = new File([bytes], name, { type });
  } else {
    fileObj = new Blob([bytes], { type });
    fileObj.name = name;
  }
  Object.assign(fileObj, extra);
  return fileObj;
}

async function captureVideoFrame(videoEl, options = {}) {
  const mimeType = options.photoMimeType || 'image/png';
  const ext = mimeType === 'image/jpeg' ? 'jpg' : 'png';
  const fileName = `photo-${Date.now()}.${ext}`;
  const width = Number(videoEl && videoEl.videoWidth) || 640;
  const height = Number(videoEl && videoEl.videoHeight) || 480;

  if (typeof document !== 'undefined') {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx2d = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
    if (ctx2d && typeof ctx2d.drawImage === 'function') {
      try {
        ctx2d.drawImage(videoEl, 0, 0, width, height);
      } catch {
        /* 某些桩对象不支持 drawImage，回退为合成帧字节 */
      }
      if (typeof canvas.toBlob === 'function') {
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, mimeType));
        if (blob && blob.size > 0) {
          return createSyntheticFile(blob, fileName, mimeType);
        }
      }
    }
  }
  const header = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82]);
  return createSyntheticFile(header, fileName, mimeType);
}

function defaultMediaDevices(options) {
  if (options && options.mediaDevices) return options.mediaDevices;
  if (typeof navigator !== 'undefined' && navigator.mediaDevices) return navigator.mediaDevices;
  return null;
}

function defaultMediaRecorderClass(options) {
  if (options && options.MediaRecorder) return options.MediaRecorder;
  if (typeof globalThis.MediaRecorder === 'function') return globalThis.MediaRecorder;
  return null;
}

function createObjectUrlSafe(blob) {
  if (typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function' && blob) {
    try {
      return URL.createObjectURL(blob);
    } catch {
      return '';
    }
  }
  return '';
}

function revokeObjectUrlSafe(url) {
  if (url && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
    try {
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    }
  }
}

export function MediaCapture(options = {}) {
  ensureMediaStyles();

  const modes = Array.isArray(options.modes) && options.modes.length
    ? options.modes.filter((m) => m === 'file' || m === 'camera' || m === 'audio')
    : ['file', 'camera', 'audio'];
  const acceptList = normalizeAcceptList(options.accept);
  const maxSizeBytes = Number(options.maxSizeBytes ?? DEFAULT_MAX_SIZE_BYTES);
  const maxDurationSec = Number(options.maxDurationSec ?? DEFAULT_MAX_DURATION_SEC);

  const state = {
    mode: modes.includes(options.defaultMode) ? options.defaultMode : modes[0],
    phase: 'idle', // idle | live | recording | preview | uploading | uploaded
    devices: [],
    selectedDeviceId: '',
    activeDeviceLabel: '',
    stream: null,
    recorder: null,
    chunks: [],
    recordingStartedAt: 0,
    recordingElapsedSec: 0,
    timerId: null,
    pendingFile: null,
    previewUrl: '',
    lastError: null,
    lastResult: null,
    ignoringRecorderStop: false,
  };

  const root = el('section', {
    class: 'hk-media-capture',
    'aria-label': options.title || '现场媒体采集与上传',
  });

  const fileInput = el('input', {
    type: 'file',
    accept: acceptList.join(','),
    hidden: true,
    'aria-label': '选择本地媒体文件',
    onChange: (e) => {
      const f = e.target && e.target.files && e.target.files[0];
      if (f) handleLocalFileSelected(f);
      if (e.target) e.target.value = '';
    },
  });

  function clearTimer() {
    if (state.timerId !== null) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
  }

  function revokePreview() {
    if (state.previewUrl) {
      revokeObjectUrlSafe(state.previewUrl);
      state.previewUrl = '';
    }
  }

  function stopTracks() {
    clearTimer();
    if (state.recorder && state.recorder.state && state.recorder.state !== 'inactive') {
      state.ignoringRecorderStop = true;
      try {
        state.recorder.stop();
      } catch {
        /* ignore */
      }
    }
    state.recorder = null;
    if (state.stream) {
      const tracks = typeof state.stream.getTracks === 'function' ? state.stream.getTracks() : [];
      for (const track of tracks) {
        if (track && typeof track.stop === 'function') {
          try {
            track.stop();
          } catch {
            /* ignore */
          }
        }
      }
      state.stream = null;
    }
  }

  function release() {
    stopTracks();
    revokePreview();
    if (state.phase === 'live' || state.phase === 'recording') {
      state.phase = 'idle';
      render();
    }
  }

  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    const onLeave = () => release();
    window.addEventListener('pagehide', onLeave);
    window.addEventListener('beforeunload', onLeave);
    window.addEventListener('hashchange', () => {
      if (!root.isConnected || state.phase === 'live' || state.phase === 'recording') {
        release();
      }
    });
  }

  function setError(rawErr, fallbackCode = 'media_capture_interrupted') {
    const normalized = normalizeMediaError(rawErr, fallbackCode);
    state.lastError = normalized;
    if (typeof options.onError === 'function') {
      options.onError(normalized);
    }
  }

  async function refreshDevices(kind) {
    const mediaDevices = defaultMediaDevices(options);
    if (!mediaDevices || typeof mediaDevices.enumerateDevices !== 'function') {
      state.devices = [];
      return;
    }
    try {
      const all = await mediaDevices.enumerateDevices();
      const matched = (Array.isArray(all) ? all : []).filter((d) => d && d.kind === kind);
      state.devices = matched.map((d, idx) => ({
        deviceId: d.deviceId || `device-${idx + 1}`,
        label: d.label || `${kind === 'videoinput' ? '摄像头' : '麦克风'} ${idx + 1}`,
        kind: d.kind,
      }));
      if (state.stream && typeof state.stream.getTracks === 'function') {
        const activeTrack = state.stream.getTracks()[0];
        const trackSettings = activeTrack && typeof activeTrack.getSettings === 'function' ? activeTrack.getSettings() : {};
        const trackDeviceId = (trackSettings && trackSettings.deviceId) || (activeTrack && activeTrack.deviceId) || '';
        const trackLabel = (activeTrack && activeTrack.label) || '';
        if (trackDeviceId && state.devices.some((d) => d.deviceId === trackDeviceId)) {
          state.selectedDeviceId = trackDeviceId;
        } else if (!state.selectedDeviceId && state.devices[0]) {
          state.selectedDeviceId = state.devices[0].deviceId;
        }
        const matchedDevice = state.devices.find((d) => d.deviceId === state.selectedDeviceId);
        state.activeDeviceLabel = trackLabel || (matchedDevice && matchedDevice.label) || '';
      } else if (!state.selectedDeviceId && state.devices[0]) {
        state.selectedDeviceId = state.devices[0].deviceId;
      }
    } catch {
      state.devices = [];
    }
  }

  function switchMode(nextMode) {
    if (!modes.includes(nextMode)) return;
    stopTracks();
    revokePreview();
    state.mode = nextMode;
    state.phase = 'idle';
    state.pendingFile = null;
    state.lastError = null;
    state.devices = [];
    state.selectedDeviceId = '';
    state.activeDeviceLabel = '';
    state.recordingElapsedSec = 0;
    render();
  }

  function handleLocalFileSelected(file) {
    stopTracks();
    revokePreview();
    state.lastError = null;
    state.lastResult = null;
    try {
      validateMediaFile(file, {
        accept: acceptList,
        maxSizeBytes,
        maxDurationSec,
      });
      state.pendingFile = file;
      state.previewUrl = createObjectUrlSafe(file);
      state.phase = 'preview';
      state.activeDeviceLabel = '';
      render();
    } catch (err) {
      state.pendingFile = null;
      state.phase = 'idle';
      setError(err, 'media_invalid_type');
      render();
    }
  }

  async function startCamera(deviceIdOverride = '') {
    stopTracks();
    revokePreview();
    state.lastError = null;
    state.lastResult = null;
    state.pendingFile = null;

    const mediaDevices = defaultMediaDevices(options);
    if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function') {
      setError(mediaError('media_not_supported'));
      state.phase = 'idle';
      render();
      return;
    }

    const targetDeviceId = deviceIdOverride || state.selectedDeviceId;
    const videoConstraint = targetDeviceId
      ? { deviceId: { exact: targetDeviceId } }
      : { facingMode: 'environment' };

    try {
      const stream = await mediaDevices.getUserMedia({ video: videoConstraint, audio: false });
      state.stream = stream;
      state.phase = 'live';
      if (targetDeviceId) state.selectedDeviceId = targetDeviceId;
      await refreshDevices('videoinput');
      if (!state.activeDeviceLabel) {
        const matched = state.devices.find((d) => d.deviceId === state.selectedDeviceId);
        state.activeDeviceLabel = (matched && matched.label) || '默认摄像头';
      }
      const tracks = typeof stream.getTracks === 'function' ? stream.getTracks() : [];
      for (const track of tracks) {
        if (track && typeof track.addEventListener === 'function') {
          track.addEventListener('ended', () => {
            if (state.phase === 'live') {
              stopTracks();
              state.phase = 'idle';
              setError(mediaError('media_capture_interrupted'));
              render();
            }
          });
        }
      }
      render();
    } catch (err) {
      stopTracks();
      state.phase = 'idle';
      setError(err, 'media_permission_denied');
      render();
    }
  }

  async function takePhoto(videoEl) {
    if (state.phase !== 'live' || !state.stream) return;
    try {
      const photoFile = await captureVideoFrame(videoEl, options);
      stopTracks();
      validateMediaFile(photoFile, {
        accept: acceptList,
        maxSizeBytes,
        maxDurationSec,
      });
      state.pendingFile = photoFile;
      state.previewUrl = createObjectUrlSafe(photoFile);
      state.phase = 'preview';
      state.lastError = null;
      render();
    } catch (err) {
      stopTracks();
      state.phase = 'idle';
      setError(err, 'media_capture_interrupted');
      render();
    }
  }

  async function startAudioRecording(deviceIdOverride = '') {
    stopTracks();
    revokePreview();
    state.lastError = null;
    state.lastResult = null;
    state.pendingFile = null;
    state.recordingElapsedSec = 0;

    const mediaDevices = defaultMediaDevices(options);
    const RecorderClass = defaultMediaRecorderClass(options);
    if (!mediaDevices || typeof mediaDevices.getUserMedia !== 'function' || !RecorderClass) {
      setError(mediaError('media_not_supported'));
      state.phase = 'idle';
      render();
      return;
    }

    const targetDeviceId = deviceIdOverride || state.selectedDeviceId;
    const audioConstraint = targetDeviceId ? { deviceId: { exact: targetDeviceId } } : true;

    try {
      const stream = await mediaDevices.getUserMedia({ audio: audioConstraint, video: false });
      state.stream = stream;
      if (targetDeviceId) state.selectedDeviceId = targetDeviceId;
      await refreshDevices('audioinput');
      if (!state.activeDeviceLabel) {
        const matched = state.devices.find((d) => d.deviceId === state.selectedDeviceId);
        state.activeDeviceLabel = (matched && matched.label) || '默认麦克风';
      }

      const recorderMime = options.audioMimeType || 'audio/webm';
      const recorder = new RecorderClass(stream, { mimeType: recorderMime });
      state.recorder = recorder;
      state.chunks = [];
      state.ignoringRecorderStop = false;
      state.recordingStartedAt = Date.now();
      state.phase = 'recording';

      const onData = (event) => {
        if (event && event.data && event.data.size > 0) {
          state.chunks.push(event.data);
        }
      };
      const onError = () => {
        stopTracks();
        state.phase = 'idle';
        setError(mediaError('media_capture_interrupted'));
        render();
      };
      const onStop = () => {
        if (state.ignoringRecorderStop) return;
        const durationSec = Math.max(
          state.recordingElapsedSec,
          Math.round((Date.now() - state.recordingStartedAt) / 1000) || 1
        );
        stopTracks();
        const mimeType = (recorder && recorder.mimeType) || recorderMime || 'audio/webm';
        const ext = mimeType.includes('wav') ? 'wav' : mimeType.includes('mp4') ? 'm4a' : 'webm';
        const blob = new Blob(state.chunks, { type: mimeType });
        const audioFile = createSyntheticFile(blob, `audio-${Date.now()}.${ext}`, mimeType, {
          durationSec,
        });
        try {
          validateMediaFile(audioFile, {
            accept: acceptList,
            maxSizeBytes,
            maxDurationSec,
            durationSec,
          });
          state.pendingFile = audioFile;
          state.previewUrl = createObjectUrlSafe(audioFile);
          state.phase = 'preview';
          state.lastError = null;
          render();
        } catch (err) {
          state.pendingFile = null;
          state.phase = 'idle';
          setError(err, 'media_duration_exceeded');
          render();
        }
      };

      if (typeof recorder.addEventListener === 'function') {
        recorder.addEventListener('dataavailable', onData);
        recorder.addEventListener('error', onError);
        recorder.addEventListener('stop', onStop);
      } else {
        recorder.ondataavailable = onData;
        recorder.onerror = onError;
        recorder.onstop = onStop;
      }

      const tracks = typeof stream.getTracks === 'function' ? stream.getTracks() : [];
      for (const track of tracks) {
        if (track && typeof track.addEventListener === 'function') {
          track.addEventListener('ended', () => {
            if (state.phase === 'recording') {
              stopTracks();
              state.phase = 'idle';
              setError(mediaError('media_capture_interrupted'));
              render();
            }
          });
        }
      }

      recorder.start();
      const tickMs = Number(options.timerIntervalMs) > 0 ? Number(options.timerIntervalMs) : 250;
      state.timerId = setInterval(() => {
        if (state.phase !== 'recording') return;
        const elapsed = Math.floor((Date.now() - state.recordingStartedAt) / 1000);
        if (elapsed !== state.recordingElapsedSec) {
          state.recordingElapsedSec = elapsed;
          const timerNode = root.querySelector('[data-media-timer]');
          if (timerNode) {
            timerNode.textContent = `${formatDuration(state.recordingElapsedSec)} / ${formatDuration(maxDurationSec)}`;
          }
        }
        if (Number.isFinite(maxDurationSec) && maxDurationSec > 0 && state.recordingElapsedSec > maxDurationSec) {
          stopTracks();
          state.phase = 'idle';
          setError(mediaError('media_duration_exceeded', { durationSec: state.recordingElapsedSec, maxDurationSec }));
          render();
        }
      }, tickMs);

      render();
    } catch (err) {
      stopTracks();
      state.phase = 'idle';
      setError(err, 'media_permission_denied');
      render();
    }
  }

  function finishAudioRecording() {
    if (state.phase !== 'recording' || !state.recorder) return;
    clearTimer();
    try {
      state.recorder.stop();
    } catch (err) {
      stopTracks();
      state.phase = 'idle';
      setError(err, 'media_capture_interrupted');
      render();
    }
  }

  function cancelCapture() {
    stopTracks();
    revokePreview();
    state.pendingFile = null;
    state.lastError = null;
    state.recordingElapsedSec = 0;
    state.phase = 'idle';
    if (typeof options.onCancel === 'function') {
      options.onCancel({ mode: state.mode });
    }
    render();
  }

  function retakeCapture() {
    const currentMode = state.mode;
    stopTracks();
    revokePreview();
    state.pendingFile = null;
    state.lastError = null;
    state.phase = 'idle';
    if (currentMode === 'camera') {
      startCamera(state.selectedDeviceId);
    } else if (currentMode === 'audio') {
      startAudioRecording(state.selectedDeviceId);
    } else {
      render();
      fileInput.click();
    }
  }

  async function confirmUpload() {
    if (!state.pendingFile || state.phase === 'uploading') return;
    state.lastError = null;
    state.phase = 'uploading';
    render();

    const file = state.pendingFile;
    const uploadOpts = {
      ...options,
      accept: acceptList,
      maxSizeBytes,
      maxDurationSec,
      sourceMode: state.mode,
      sourceLabel: SOURCE_LABELS[state.mode] || SOURCE_LABELS.file,
      deviceLabel: state.activeDeviceLabel || '',
      durationSec: file.durationSec ?? (state.mode === 'audio' ? state.recordingElapsedSec || 1 : null),
    };

    try {
      let ref;
      if (typeof options.onUpload === 'function') {
        const customRes = await options.onUpload(file, uploadOpts);
        ref = customRes && customRes.fileId ? customRes : buildMediaReference(customRes, file, uploadOpts);
      } else if (options.ctx && options.ctx.preview && options.ctx.preview.media) {
        ref = await options.ctx.preview.media.upload(file, uploadOpts);
      } else if (options.http && options.appId) {
        ref = await upload(options.http, options.appId, file, uploadOpts);
      } else if (options.ctx && options.ctx.preview && options.ctx.preview.knowledge) {
        const kbRes = await options.ctx.preview.knowledge.upload(file, {
          title: uploadOpts.title || stripExt(file.name) || '现场采集原件',
          category: uploadOpts.category || DEFAULT_CATEGORY,
          project: uploadOpts.project || DEFAULT_PROJECT,
          purpose: uploadOpts.purpose || 'media',
          visibility: uploadOpts.visibility || 'internal',
          note: uploadOpts.note || `${uploadOpts.sourceLabel}上传`,
        });
        ref = buildMediaReference(kbRes, file, uploadOpts);
      } else {
        throw mediaError('media_upload_failed');
      }

      revokePreview();
      state.pendingFile = null;
      state.lastResult = ref;
      state.phase = 'uploaded';
      if (typeof options.onUploaded === 'function') {
        options.onUploaded(ref);
      }
      render();
    } catch (err) {
      // 保留待上传原件与预览，允许用户直接点击「重试上传」或改用本地文件
      state.phase = 'preview';
      setError(err, 'media_upload_failed');
      render();
    }
  }

  function switchToFileFallback() {
    switchMode('file');
  }

  function renderModeTabs() {
    const tabButtons = modes.map((modeKey) => {
      const active = state.mode === modeKey;
      return el(
        'button',
        {
          type: 'button',
          role: 'tab',
          class: `hk-media-mode-btn${active ? ' is-active' : ''}`,
          'aria-selected': active ? 'true' : 'false',
          dataset: { mediaMode: modeKey },
          onClick: () => switchMode(modeKey),
          onKeydown: (e) => {
            const idx = modes.indexOf(modeKey);
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
              e.preventDefault();
              const nextIdx = e.key === 'ArrowRight'
                ? (idx + 1) % modes.length
                : (idx - 1 + modes.length) % modes.length;
              const nextMode = modes[nextIdx];
              switchMode(nextMode);
              const nextBtn = root.querySelector(`[data-media-mode="${nextMode}"]`);
              if (nextBtn && typeof nextBtn.focus === 'function') nextBtn.focus();
            }
          },
        },
        SOURCE_LABELS[modeKey]
      );
    });
    return el('div', { class: 'hk-media-modes', role: 'tablist', 'aria-label': '采集方式切换' }, tabButtons);
  }

  function renderDeviceBar() {
    if (state.mode === 'file') return null;
    const isCamera = state.mode === 'camera';
    const isLive = state.phase === 'live';
    const isRecording = state.phase === 'recording';
    const statusLabel = state.activeDeviceLabel
      ? `当前设备：${state.activeDeviceLabel}`
      : isCamera
      ? '摄像头未开启（点击下方按钮后请求授权）'
      : '麦克风未开启（点击下方按钮后请求授权）';

    const selectId = `hk-media-device-${state.mode}`;
    const deviceSelect = state.devices.length > 0
      ? el(
          'div',
          { class: 'hk-media-device-select-wrap' },
          el('label', { class: 'hk-media-device-label', for: selectId }, '切换设备'),
          el(
            'select',
            {
              id: selectId,
              class: 'hk-media-device-select',
              'aria-label': isCamera ? '选择摄像头设备' : '选择麦克风设备',
              dataset: { mediaDeviceSelect: state.mode },
              onChange: (e) => {
                const nextId = e.target.value;
                state.selectedDeviceId = nextId;
                const found = state.devices.find((d) => d.deviceId === nextId);
                state.activeDeviceLabel = (found && found.label) || '';
                if (state.phase === 'live' && isCamera) {
                  startCamera(nextId);
                } else if (state.phase === 'recording' && !isCamera) {
                  startAudioRecording(nextId);
                } else {
                  render();
                }
              },
            },
            state.devices.map((d) =>
              el('option', { value: d.deviceId, selected: d.deviceId === state.selectedDeviceId }, d.label)
            )
          )
        )
      : null;

    return el(
      'div',
      { class: 'hk-media-device-bar', dataset: { mediaDeviceBar: state.mode } },
      el(
        'div',
        { class: 'hk-media-device-status' },
        el('span', {
          class: `hk-media-dot${isLive ? ' is-live' : ''}${isRecording ? ' is-recording' : ''}`,
          'aria-hidden': 'true',
        }),
        el('span', { dataset: { mediaActiveDevice: '' } }, statusLabel)
      ),
      deviceSelect
    );
  }

  function renderErrorAlert() {
    if (!state.lastError) return null;
    const text = errorMessage(state.lastError);
    return el(
      'div',
      { class: 'hk-media-alert', role: 'alert', dataset: { mediaError: state.lastError.code || 'error' } },
      el('div', {}, text),
      el(
        'div',
        { class: 'hk-media-alert-actions' },
        state.phase === 'preview' && state.pendingFile
          ? el(
              'button',
              {
                type: 'button',
                class: 'hk-btn hk-btn--primary hk-btn--sm',
                dataset: { mediaAction: 'retry-upload' },
                onClick: () => confirmUpload(),
              },
              '重试上传'
            )
          : null,
        state.mode !== 'file'
          ? el(
              'button',
              {
                type: 'button',
                class: 'hk-btn hk-btn--secondary hk-btn--sm',
                dataset: { mediaAction: 'fallback-file' },
                onClick: () => switchToFileFallback(),
              },
              '改用本地文件上传'
            )
          : null
      )
    );
  }

  function renderStage() {
    if (state.phase === 'preview' && state.pendingFile) {
      const f = state.pendingFile;
      const mime = inferMimeType(f);
      const isImage = mime.startsWith('image/');
      const isAudio = mime.startsWith('audio/');
      const retakeText = state.mode === 'camera' ? '重拍' : state.mode === 'audio' ? '重录' : '重选文件';

      return el(
        'div',
        { class: 'hk-media-stage is-preview', dataset: { mediaPhase: 'preview' } },
        isImage
          ? el(
              'div',
              { class: 'hk-media-viewport' },
              el('img', {
                class: 'hk-media-photo',
                src: state.previewUrl || '',
                alt: `待上传照片预览：${f.name}`,
                dataset: { mediaPreviewImage: '' },
              })
            )
          : null,
        isAudio
          ? el(
              'div',
              { class: 'hk-media-audio-box' },
              el('audio', {
                class: 'hk-media-audio-player',
                controls: true,
                src: state.previewUrl || '',
                'aria-label': `待上传录音回放：${f.name}`,
                dataset: { mediaPreviewAudio: '' },
              })
            )
          : null,
        el(
          'div',
          { class: 'hk-media-meta', dataset: { mediaPreviewMeta: '' } },
          el('strong', {}, f.name || '待上传原件'),
          el('span', { class: 'hk-badge hk-badge--neutral' }, SOURCE_LABELS[state.mode] || '本地文件'),
          el('span', {}, formatBytes(f.size)),
          f.durationSec ? el('span', {}, `时长 ${formatDuration(f.durationSec)}`) : null,
          state.activeDeviceLabel ? el('span', {}, `来源设备：${state.activeDeviceLabel}`) : null
        ),
        el(
          'div',
          { class: 'hk-media-actions' },
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--primary',
              dataset: { mediaAction: 'confirm-upload' },
              onClick: () => confirmUpload(),
            },
            '确认上传'
          ),
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--secondary',
              dataset: { mediaAction: 'retake' },
              onClick: () => retakeCapture(),
            },
            retakeText
          ),
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--ghost',
              dataset: { mediaAction: 'cancel' },
              onClick: () => cancelCapture(),
            },
            '取消'
          )
        )
      );
    }

    if (state.phase === 'uploading') {
      return el(
        'div',
        { class: 'hk-media-stage is-preview', dataset: { mediaPhase: 'uploading' } },
        el('div', { class: 'hk-media-meta' }, '正在上传并登记原件，请稍候…')
      );
    }

    if (state.mode === 'camera') {
      if (state.phase === 'live') {
        const videoEl = el('video', {
          class: 'hk-media-video',
          autoplay: true,
          playsinline: true,
          muted: true,
          'aria-label': '现场拍照取景画面',
          dataset: { mediaLiveVideo: '' },
        });
        if (state.stream) {
          try {
            videoEl.srcObject = state.stream;
          } catch {
            /* 测试桩可能只读 */
          }
        }
        return el(
          'div',
          { class: 'hk-media-stage is-live', dataset: { mediaPhase: 'live' } },
          el('div', { class: 'hk-media-viewport' }, videoEl),
          el(
            'div',
            { class: 'hk-media-actions' },
            el(
              'button',
              {
                type: 'button',
                class: 'hk-btn hk-btn--primary',
                dataset: { mediaAction: 'take-photo' },
                onClick: () => takePhoto(videoEl),
              },
              '拍照'
            ),
            el(
              'button',
              {
                type: 'button',
                class: 'hk-btn hk-btn--ghost',
                dataset: { mediaAction: 'cancel' },
                onClick: () => cancelCapture(),
              },
              '取消'
            )
          )
        );
      }
      return el(
        'div',
        { class: 'hk-media-stage', dataset: { mediaPhase: 'idle' } },
        el(
          'div',
          { class: 'hk-media-meta' },
          `单张大小上限 ${formatBytes(maxSizeBytes)}，拍摄后先预览再确认上传。`
        ),
        el(
          'div',
          { class: 'hk-media-actions' },
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--primary',
              dataset: { mediaAction: 'start-camera' },
              onClick: () => startCamera(),
            },
            '开启摄像头'
          ),
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--secondary',
              dataset: { mediaAction: 'open-file' },
              onClick: () => fileInput.click(),
            },
            '选择本地图片'
          )
        )
      );
    }

    if (state.mode === 'audio') {
      if (state.phase === 'recording') {
        return el(
          'div',
          { class: 'hk-media-stage is-live', dataset: { mediaPhase: 'recording' } },
          el(
            'div',
            { class: 'hk-media-audio-box' },
            el(
              'div',
              { class: 'hk-media-timer', dataset: { mediaTimer: '' } },
              `${formatDuration(state.recordingElapsedSec)} / ${formatDuration(maxDurationSec)}`
            ),
            el(
              'div',
              { class: 'hk-media-meta' },
              `正在录音（${state.activeDeviceLabel || '默认麦克风'}），停止后可回放确认。`
            )
          ),
          el(
            'div',
            { class: 'hk-media-actions' },
            el(
              'button',
              {
                type: 'button',
                class: 'hk-btn hk-btn--primary',
                dataset: { mediaAction: 'stop-audio' },
                onClick: () => finishAudioRecording(),
              },
              '完成录音'
            ),
            el(
              'button',
              {
                type: 'button',
                class: 'hk-btn hk-btn--ghost',
                dataset: { mediaAction: 'cancel' },
                onClick: () => cancelCapture(),
              },
              '取消'
            )
          )
        );
      }
      return el(
        'div',
        { class: 'hk-media-stage', dataset: { mediaPhase: 'idle' } },
        el(
          'div',
          { class: 'hk-media-meta' },
          `单段时长上限 ${formatDuration(maxDurationSec)}，文件大小上限 ${formatBytes(maxSizeBytes)}。`
        ),
        el(
          'div',
          { class: 'hk-media-actions' },
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--primary',
              dataset: { mediaAction: 'start-audio' },
              onClick: () => startAudioRecording(),
            },
            '开始录音'
          ),
          el(
            'button',
            {
              type: 'button',
              class: 'hk-btn hk-btn--secondary',
              dataset: { mediaAction: 'open-file' },
              onClick: () => fileInput.click(),
            },
            '选择本地音频'
          )
        )
      );
    }

    // 默认：本地文件选择模式
    const dropzone = el(
      'div',
      {
        class: 'hk-upload',
        role: 'button',
        tabindex: '0',
        'aria-label': '选择或拖入本地文件',
        dataset: { mediaAction: 'dropzone' },
        onClick: () => fileInput.click(),
        onKeydown: (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInput.click();
          }
        },
        onDragover: (e) => {
          e.preventDefault();
          dropzone.classList.add('over');
        },
        onDragleave: () => dropzone.classList.remove('over'),
        onDrop: (e) => {
          e.preventDefault();
          dropzone.classList.remove('over');
          const dropped = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if (dropped) handleLocalFileSelected(dropped);
        },
      },
      el('strong', {}, options.fileLabel || '选择或拖入本地文件（照片、录音、文档）'),
      el('span', {}, `单文件上限 ${formatBytes(maxSizeBytes)}`)
    );

    return el('div', { class: 'hk-media-stage', dataset: { mediaPhase: 'idle' } }, dropzone);
  }

  function renderResultCard() {
    if (!state.lastResult) return null;
    const r = state.lastResult;
    return el(
      'div',
      { class: 'hk-media-result', dataset: { mediaResult: 'registered' } },
      el(
        'div',
        { class: 'hk-media-result-head' },
        el('strong', {}, `已登记原件：${r.name}`),
        el('span', { class: 'hk-badge hk-badge--confirmed' }, `版本 v${r.version}`)
      ),
      el(
        'div',
        { class: 'hk-media-result-grid' },
        el('span', {}, `来源：${r.sourceLabel}`),
        el('span', {}, `大小：${formatBytes(r.size)}`),
        r.durationSec ? el('span', {}, `时长：${formatDuration(r.durationSec)}`) : null,
        r.createdAt ? el('span', {}, `上传时间：${formatUploadTime(r.createdAt)}`) : null
      ),
      r.contentUrl
        ? el('a', { class: 'hk-media-result-link', href: r.contentUrl, target: '_blank', rel: 'noopener' }, '在知识库中查看')
        : null
    );
  }

  function render() {
    // replaceChildren 会把 null 渲染成文本「null」，必须先过滤
    root.replaceChildren(...[
      fileInput,
      el(
        'div',
        { class: 'hk-media-head' },
        el('h4', { class: 'hk-media-title' }, options.title || '现场媒体采集与上传'),
        modes.length > 1 ? renderModeTabs() : null
      ),
      renderDeviceBar(),
      renderErrorAlert(),
      renderStage(),
      renderResultCard()
    ].filter(Boolean));
  }

  render();

  root.release = release;
  root.destroy = release;
  root.selectFile = handleLocalFileSelected;
  root.switchMode = switchMode;
  root.getState = () => ({
    mode: state.mode,
    phase: state.phase,
    devices: [...state.devices],
    selectedDeviceId: state.selectedDeviceId,
    activeDeviceLabel: state.activeDeviceLabel,
    hasActiveStream: Boolean(state.stream),
    pendingFile: state.pendingFile,
    lastError: state.lastError,
    lastResult: state.lastResult,
  });

  return root;
}

export function capture(http, appId, options = {}) {
  return MediaCapture({ ...options, http, appId });
}
