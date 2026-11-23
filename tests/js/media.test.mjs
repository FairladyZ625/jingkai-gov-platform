// CAP-09 媒体采集与上传组件的 Node 行为测试（无浏览器、假 MediaDevices / MediaRecorder）。
// 运行：node tests/js/media.test.mjs
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { installDom } from './dom-stub.mjs';

installDom();

// 补充 window 事件桩，用于验证离开页面自动释放设备轨道
const windowListeners = {};
globalThis.window = {
  location: { search: '', hash: '' },
  addEventListener(type, fn) {
    (windowListeners[type] ||= []).push(fn);
  },
  dispatchEvent(event) {
    for (const fn of windowListeners[event.type] || []) fn(event);
  },
};

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const mediaMod = await import(pathToFileURL(path.join(ROOT, 'core', 'sdk', 'js', 'preview', 'media.js')).href);
const haiknowMod = await import(pathToFileURL(path.join(ROOT, 'core', 'sdk', 'js', 'haiknow.js')).href);

const {
  MediaCapture,
  validateMediaFile,
  normalizeMediaError,
  upload: uploadMedia,
} = mediaMod;
const { createContext } = haiknowMod;

class FakeTrack {
  constructor(kind, deviceId, label) {
    this.kind = kind;
    this.deviceId = deviceId;
    this.label = label;
    this.stopped = false;
    this.listeners = {};
  }
  getSettings() {
    return { deviceId: this.deviceId };
  }
  stop() {
    this.stopped = true;
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  emit(type) {
    for (const fn of this.listeners[type] || []) fn({ type });
  }
}

class FakeStream {
  constructor(tracks) {
    this._tracks = tracks;
  }
  getTracks() {
    return this._tracks;
  }
}

function createFakeMediaDevices({ devices = [], onGetUserMedia } = {}) {
  const calls = [];
  const createdTracks = [];
  return {
    calls,
    createdTracks,
    async enumerateDevices() {
      return devices;
    },
    async getUserMedia(constraints) {
      calls.push(constraints);
      if (onGetUserMedia) {
        return onGetUserMedia(constraints, createdTracks);
      }
      const isVideo = Boolean(constraints && constraints.video);
      const kind = isVideo ? 'videoinput' : 'audioinput';
      const requestedId =
        constraints &&
        typeof constraints[isVideo ? 'video' : 'audio'] === 'object' &&
        constraints[isVideo ? 'video' : 'audio'].deviceId &&
        constraints[isVideo ? 'video' : 'audio'].deviceId.exact;
      const matched =
        devices.find((d) => d.kind === kind && (!requestedId || d.deviceId === requestedId)) ||
        devices.find((d) => d.kind === kind) || {
          deviceId: requestedId || (isVideo ? 'cam-default' : 'mic-default'),
          label: isVideo ? '默认摄像头' : '默认麦克风',
          kind,
        };
      const track = new FakeTrack(isVideo ? 'video' : 'audio', matched.deviceId, matched.label);
      createdTracks.push(track);
      return new FakeStream([track]);
    },
  };
}

class FakeMediaRecorder {
  static instances = [];
  constructor(stream, options = {}) {
    this.stream = stream;
    this.mimeType = options.mimeType || 'audio/webm';
    this.state = 'inactive';
    this.listeners = {};
    this.chunkBytes = new Uint8Array([26, 69, 223, 163, 1, 2, 3, 4]);
    FakeMediaRecorder.instances.push(this);
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  emit(type, event = {}) {
    for (const fn of this.listeners[type] || []) fn(event);
  }
  start() {
    this.state = 'recording';
  }
  stop() {
    if (this.state === 'inactive') return;
    this.state = 'inactive';
    this.emit('dataavailable', {
      data: new Blob([this.chunkBytes], { type: this.mimeType }),
    });
    this.emit('stop', {});
  }
}

// 1. 权限拒绝后说明中文原因，且仍可回退到本地文件上传
function assertCleanText(comp, where) {
  const text = comp.textContent || '';
  assert.ok(!/\b(null|undefined)\b/.test(text), `${where}：组件文本不得含 null/undefined，实际：${text}`);
}

async function testCameraPermissionDeniedAndFileFallback() {
  const fakeDevices = createFakeMediaDevices({
    onGetUserMedia: async () => {
      const err = new Error('Permission denied');
      err.name = 'NotAllowedError';
      throw err;
    },
  });
  const uploaded = [];
  const comp = MediaCapture({
    defaultMode: 'camera',
    mediaDevices: fakeDevices,
    onUpload: async (file, opts) => {
      uploaded.push({ file, opts });
      return {
        id: 'kb-entry-1',
        latestVersion: 1,
        latest: { fileId: 'file-fallback-1', version: 1, name: file.name, size: file.size, sha256: 'abc123' },
      };
    },
  });

  assert.equal(fakeDevices.calls.length, 0, '挂载组件时不得自动请求摄像头权限');
  assertCleanText(comp, '挂载后');
  comp.querySelector('[data-media-action="start-camera"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assertCleanText(comp, '权限被拒后');

  assert.equal(fakeDevices.calls.length, 1, '点击开启摄像头后才请求权限');
  const alertNode = comp.querySelector('[role="alert"]');
  assert.ok(alertNode, '权限被拒后应渲染告警提示');
  assert.ok(alertNode.textContent.includes('摄像头或麦克风权限被拒绝'), '应提示中文原因');
  assert.ok(!alertNode.textContent.includes('media_permission_denied'), '界面不得露出原始错误码');
  assert.ok(!alertNode.textContent.includes('NotAllowedError'), '界面不得露出浏览器异常名');

  // 点击「改用本地文件上传」回退按钮，切回文件选择并完成上传
  const fallbackBtn = comp.querySelector('[data-media-action="fallback-file"]');
  assert.ok(fallbackBtn, '权限被拒后必须保留本地文件回退按钮');
  fallbackBtn.click();
  assert.equal(comp.getState().mode, 'file');

  const localPhoto = new File([new Uint8Array([137, 80, 78, 71])], 'weld-check.png', { type: 'image/png' });
  comp.selectFile(localPhoto);
  assert.equal(comp.getState().phase, 'preview', '选文件后先进入预览，未确认前不上传');
  assert.equal(uploaded.length, 0);

  comp.querySelector('[data-media-action="confirm-upload"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(uploaded.length, 1, '点击确认上传后才发起上传');
  assert.equal(comp.getState().phase, 'uploaded');
  assert.equal(comp.getState().lastResult.fileId, 'file-fallback-1');
  assert.equal(comp.getState().lastResult.sourceMode, 'file');
  assertCleanText(comp, '上传完成后');
  const card = comp.querySelector('.hk-media-result');
  assert.ok(card, '应渲染已登记原件卡片');
  assert.ok(!card.textContent.includes('file-fallback-1'), '卡片不得展示文件号');
  assert.ok(!card.textContent.includes('kb-entry-1'), '卡片不得展示知识库条目 ID');
  assert.ok(card.textContent.includes('weld-check.png') && card.textContent.includes('来源') && card.textContent.includes('大小') && card.textContent.includes('上传时间'));
  const link = card.querySelector('.hk-media-result-link');
  assert.ok(link && link.textContent.includes('在知识库中查看'), '卡片应提供知识库查看链接');
}

// 2. 摄像头列出与切换设备、拍照后释放轨道、预览重拍与确认上传
async function testCameraDeviceSwitchAndPhotoLifecycle() {
  const fakeDevices = createFakeMediaDevices({
    devices: [
      { kind: 'videoinput', deviceId: 'cam-front', label: '内置前置摄像头' },
      { kind: 'videoinput', deviceId: 'cam-usb', label: '外接工业显微镜相机' },
    ],
  });
  let uploadCount = 0;
  let lastRef = null;
  const comp = MediaCapture({
    defaultMode: 'camera',
    mediaDevices: fakeDevices,
    onUpload: async (file, opts) => {
      uploadCount += 1;
      return {
        id: 'kb-cam-1',
        latestVersion: 2,
        latest: { fileId: 'file-cam-2', version: 2, name: file.name, size: file.size, sha256: 'sha-cam' },
        deviceLabel: opts.deviceLabel,
      };
    },
    onUploaded: (ref) => {
      lastRef = ref;
    },
  });

  comp.querySelector('[data-media-action="start-camera"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(comp.getState().phase, 'live');
  assert.equal(comp.getState().devices.length, 2, '应列出 2 个可用摄像头设备');
  assert.equal(fakeDevices.createdTracks.length, 1);
  assert.equal(fakeDevices.createdTracks[0].stopped, false);

  // 切换到外接工业显微镜相机：旧流轨道立即停止，新流按所选 deviceId 开启
  const selectEl = comp.querySelector('[data-media-device-select="camera"]');
  assert.ok(selectEl, '存在多台设备时应渲染设备切换下拉框');
  selectEl.value = 'cam-usb';
  selectEl.dispatchEvent({ type: 'change', target: selectEl });
  await new Promise((r) => setTimeout(r, 10));

  assert.equal(fakeDevices.createdTracks[0].stopped, true, '切换设备时旧摄像头轨道必须停止');
  assert.equal(fakeDevices.createdTracks.length, 2);
  assert.equal(fakeDevices.createdTracks[1].deviceId, 'cam-usb');
  assert.equal(comp.getState().activeDeviceLabel, '外接工业显微镜相机');

  // 点击拍照：抓帧后立即关闭摄像头轨道，进入预览态
  comp.querySelector('[data-media-action="take-photo"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(comp.getState().phase, 'preview');
  assert.equal(fakeDevices.createdTracks[1].stopped, true, '拍照完成后应立即释放摄像头轨道');
  assert.equal(uploadCount, 0, '确认前不自动上传');

  // 点击确认上传
  comp.querySelector('[data-media-action="confirm-upload"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(uploadCount, 1);
  assert.ok(lastRef);
  assert.equal(lastRef.fileId, 'file-cam-2');
  assert.equal(lastRef.entryId, 'kb-cam-1');
  assert.equal(lastRef.version, 2);
  assert.equal(lastRef.sourceMode, 'camera');
  assert.equal(lastRef.sourceLabel, '现场拍照');
  assert.equal(lastRef.deviceLabel, '外接工业显微镜相机');
}

// 3. 麦克风录音：停止后可试听、取消不留下原件、确认后才上传
async function testAudioRecordingCancelAndConfirm() {
  const fakeDevices = createFakeMediaDevices({
    devices: [{ kind: 'audioinput', deviceId: 'mic-1', label: '车间指向性麦克风' }],
  });
  let uploadCalls = 0;
  const comp = MediaCapture({
    defaultMode: 'audio',
    mediaDevices: fakeDevices,
    MediaRecorder: FakeMediaRecorder,
    onUpload: async (file) => {
      uploadCalls += 1;
      return {
        id: 'kb-audio-1',
        latestVersion: 1,
        latest: { fileId: 'file-audio-1', version: 1, name: file.name, size: file.size },
      };
    },
  });

  // 第一次录音 → 完成录音 → 试听预览 → 取消
  comp.querySelector('[data-media-action="start-audio"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(comp.getState().phase, 'recording');
  assert.equal(fakeDevices.createdTracks[0].stopped, false);

  comp.querySelector('[data-media-action="stop-audio"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(comp.getState().phase, 'preview', '停止录音后进入试听预览态');
  assert.equal(fakeDevices.createdTracks[0].stopped, true, '停止录音后麦克风轨道立即释放');
  assert.ok(comp.querySelector('[data-media-preview-audio]'), '预览态应提供 audio 试听控件');
  assert.equal(uploadCalls, 0, '未确认前不得上传');

  comp.querySelector('[data-media-action="cancel"]').click();
  assert.equal(comp.getState().phase, 'idle');
  assert.equal(comp.getState().pendingFile, null, '取消后清空临时音频');
  assert.equal(uploadCalls, 0, '取消录音不产生任何原件上传');

  // 第二次录音 → 完成录音 → 确认上传
  comp.querySelector('[data-media-action="start-audio"]').click();
  await new Promise((r) => setTimeout(r, 10));
  comp.querySelector('[data-media-action="stop-audio"]').click();
  await new Promise((r) => setTimeout(r, 10));
  comp.querySelector('[data-media-action="confirm-upload"]').click();
  await new Promise((r) => setTimeout(r, 10));

  assert.equal(uploadCalls, 1, '确认后上传一次');
  assert.equal(comp.getState().phase, 'uploaded');
  assert.equal(comp.getState().lastResult.fileId, 'file-audio-1');
  assert.equal(comp.getState().lastResult.sourceMode, 'audio');
  assert.equal(comp.getState().lastResult.sourceLabel, '现场录音');
}

// 4. 各类错误分支（无设备、被占用、格式/大小/时长超限、上传失败可重试）
async function testValidationAndUploadRetryErrors() {
  assert.equal(normalizeMediaError({ name: 'NotFoundError' }).code, 'media_device_not_found');
  assert.equal(normalizeMediaError({ name: 'NotReadableError' }).code, 'media_device_in_use');
  assert.equal(normalizeMediaError({ name: 'NotSupportedError' }).code, 'media_not_supported');

  assert.throws(
    () => validateMediaFile(new File(['x'], 'malware.exe', { type: 'application/x-msdownload' })),
    (err) => err.code === 'media_invalid_type'
  );
  assert.throws(
    () => validateMediaFile(new File([new Uint8Array(2048)], 'big.png', { type: 'image/png' }), { maxSizeBytes: 1024 }),
    (err) => err.code === 'media_too_large'
  );
  assert.throws(
    () =>
      validateMediaFile(new File([new Uint8Array(64)], 'long.webm', { type: 'audio/webm' }), {
        maxDurationSec: 30,
        durationSec: 45,
      }),
    (err) => err.code === 'media_duration_exceeded'
  );

  // 上传失败时保留预览原件并支持一键重试
  let attempts = 0;
  const comp = MediaCapture({
    defaultMode: 'file',
    onUpload: async (file) => {
      attempts += 1;
      if (attempts === 1) {
        const err = new Error('network failed');
        err.code = 'media_upload_failed';
        throw err;
      }
      return {
        id: 'kb-retry-ok',
        latestVersion: 1,
        latest: { fileId: 'file-retry-ok', version: 1, name: file.name, size: file.size },
      };
    },
  });

  comp.selectFile(new File([new Uint8Array([1, 2, 3, 4])], 'retry.png', { type: 'image/png' }));
  comp.querySelector('[data-media-action="confirm-upload"]').click();
  await new Promise((r) => setTimeout(r, 10));

  assert.equal(attempts, 1);
  assert.equal(comp.getState().phase, 'preview', '上传失败后应保留在预览态，不丢失待传文件');
  const alertNode = comp.querySelector('[role="alert"]');
  assert.ok(alertNode.textContent.includes('媒体原件上传失败'));

  const retryBtn = comp.querySelector('[data-media-action="retry-upload"]');
  assert.ok(retryBtn, '上传失败后应提供重试上传按钮');
  retryBtn.click();
  await new Promise((r) => setTimeout(r, 10));

  assert.equal(attempts, 2);
  assert.equal(comp.getState().phase, 'uploaded');
  assert.equal(comp.getState().lastResult.fileId, 'file-retry-ok');
}

// 5. 离开页面（pagehide / release）自动停止活跃设备轨道
async function testReleaseStopsActiveTracksOnLeave() {
  const fakeDevices = createFakeMediaDevices();
  const comp = MediaCapture({
    defaultMode: 'camera',
    mediaDevices: fakeDevices,
  });

  comp.querySelector('[data-media-action="start-camera"]').click();
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(comp.getState().hasActiveStream, true);
  assert.equal(fakeDevices.createdTracks[0].stopped, false);

  globalThis.window.dispatchEvent({ type: 'pagehide' });
  assert.equal(fakeDevices.createdTracks[0].stopped, true, '页面隐藏/离开时摄像头轨道必须立即停止');
  assert.equal(comp.getState().hasActiveStream, false);
  assert.equal(comp.getState().phase, 'idle');
}

// 6. ctx.preview.media 绑定应用 ID 与知识库上传路径
async function testContextPreviewMediaUpload() {
  const requests = [];
  const origFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts = {}) => {
    requests.push({ url, opts });
    return {
      ok: true,
      status: 201,
      headers: { get: () => 'application/json' },
      json: async () => ({
        id: 'kb-ctx-1',
        latestVersion: 1,
        visibility: 'internal',
        project: 'sample-project',
        category: '05-制造质量交付',
        title: '现场照片',
        latest: {
          fileId: 'f-ctx-1',
          version: 1,
          name: 'site.png',
          size: 8,
          sha256: 'deadbeef',
          status: 'unreviewed',
        },
      }),
    };
  };
  try {
    const ctx = createContext({ id: 'sample-app', actions: ['view', 'operate'] }, { id: 'sampleoperator' }, () => {});
    const file = new File([new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8])], 'site.png', { type: 'image/png' });
    const ref = await ctx.preview.media.upload(file, {
      title: '现场照片',
      project: 'sample-project',
      category: '05-制造质量交付',
      sourceMode: 'camera',
    });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/api/v1/knowledge/entries');
    assert.equal(requests[0].opts.body.get('sourceApp'), 'sample-app');
    assert.equal(ref.fileId, 'f-ctx-1');
    assert.equal(ref.entryId, 'kb-ctx-1');
    assert.equal(ref.version, 1);
    assert.equal(ref.sourceMode, 'camera');
    assert.equal(ref.sourceLabel, '现场拍照');
  } finally {
    globalThis.fetch = origFetch;
  }
}

await testCameraPermissionDeniedAndFileFallback();
await testCameraDeviceSwitchAndPhotoLifecycle();
await testAudioRecordingCancelAndConfirm();
await testValidationAndUploadRetryErrors();
await testReleaseStopsActiveTracksOnLeave();
await testContextPreviewMediaUpload();
console.log('media capture & upload tests: 6 suites passed');
