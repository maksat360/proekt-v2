/* Сканирование камерой телефона: кнопка 📷 у полей сканера.
   Код с камеры попадает в поле и «нажимается Enter» — дальше работает та же логика, что у ручного сканера.
   Android Chrome — встроенный BarcodeDetector; iPhone и остальные — zxing (грузится только по нажатию). */
'use strict';

const CAM_FIELDS = '#wh-q, #ad-scan, #rev-scan, #wh-box, #wh-prod, #wh-out-prod, #fbs-scan';
const CAM = { stream: null, raf: 0 };

function camLoadZxing() {
  if (window.ZXing) return Promise.resolve();
  return new Promise((ok, bad) => {
    const s = document.createElement('script');
    s.src = '/static/zxing.min.js?v=0.21.3';
    s.onload = ok;
    s.onerror = () => bad(new Error('Не загрузился сканер камеры'));
    document.head.appendChild(s);
  });
}

async function camDecoder() {
  if ('BarcodeDetector' in window) {
    const want = ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'itf', 'qr_code', 'data_matrix'];
    const have = await BarcodeDetector.getSupportedFormats();
    const fmts = want.filter((f) => have.includes(f));
    if (fmts.length) {
      const det = new BarcodeDetector({ formats: fmts });
      return async (video) => { const r = await det.detect(video); return r.length ? r[0].rawValue : ''; };
    }
  }
  await camLoadZxing();
  const Z = window.ZXing;
  const reader = new Z.MultiFormatReader();
  const hints = new Map();
  hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.CODE_128,
    Z.BarcodeFormat.CODE_39, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.ITF, Z.BarcodeFormat.QR_CODE, Z.BarcodeFormat.DATA_MATRIX]);
  hints.set(Z.DecodeHintType.TRY_HARDER, true);
  reader.setHints(hints);
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  return async (video) => {
    const w = video.videoWidth, h = video.videoHeight;
    if (!w) return '';
    const k = Math.min(1, 960 / w);  // меньше кадр — быстрее разбор
    cv.width = Math.round(w * k); cv.height = Math.round(h * k);
    ctx.drawImage(video, 0, 0, cv.width, cv.height);
    try {
      const bmp = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(cv)));
      return reader.decode(bmp).getText();
    } catch (e) { return ''; }  // в кадре нет кода — пробуем следующий
  };
}

function camStop() {
  cancelAnimationFrame(CAM.raf);
  if (CAM.stream) CAM.stream.getTracks().forEach((t) => t.stop());
  CAM.stream = null;
  const o = document.getElementById('cam-overlay');
  if (o) o.remove();
}

async function camOpen(input) {
  if (!window.isSecureContext || !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    toast('Камера работает только по защищённому адресу https://…:8443', 'err');
    return;
  }
  camStop();
  const o = document.createElement('div');
  o.id = 'cam-overlay';
  o.className = 'cam-overlay';
  o.innerHTML = `<video playsinline muted autoplay></video><div class="cam-frame"></div>
    <div class="cam-bar"><span>Наведите на штрихкод</span><button class="btn" type="button">Закрыть</button></div>`;
  document.body.appendChild(o);
  o.querySelector('button').addEventListener('click', () => { camStop(); input.focus(); });
  const video = o.querySelector('video');
  try {
    CAM.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    video.srcObject = CAM.stream;
    await video.play();
    const decode = await camDecoder();
    let busy = false;
    const tick = async () => {
      if (!CAM.stream) return;
      if (!busy && video.readyState >= 2) {
        busy = true;
        const code = await decode(video).catch(() => '');
        busy = false;
        if (code && CAM.stream) {
          if (navigator.vibrate) navigator.vibrate(60);
          camStop();
          input.value = code;
          input.focus();
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
          return;
        }
      }
      CAM.raf = requestAnimationFrame(tick);
    };
    tick();
  } catch (e) {
    camStop();
    toast(e.name === 'NotAllowedError' ? 'Нет доступа к камере — разрешите её в настройках браузера' : (e.message || 'Камера недоступна'), 'err');
  }
}

function camAttach() {
  document.querySelectorAll(CAM_FIELDS).forEach((inp) => {
    if (inp.dataset.cam) return;
    inp.dataset.cam = '1';
    const wrap = document.createElement('span');
    wrap.className = 'cam-wrap';
    inp.parentNode.insertBefore(wrap, inp);
    wrap.appendChild(inp);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'cam-btn';
    b.title = 'Сканировать камерой';
    b.setAttribute('aria-label', 'Сканировать камерой');
    b.textContent = '📷';
    b.addEventListener('click', () => camOpen(inp));
    wrap.appendChild(b);
  });
}

new MutationObserver(camAttach).observe(document.documentElement, { childList: true, subtree: true });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && CAM.stream) camStop(); });
