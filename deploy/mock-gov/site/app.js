const sections = [...document.querySelectorAll('section')];
const steps = [...document.querySelectorAll('aside li')];
const byId = id => document.getElementById(id);
const op = name => document.querySelector(`[data-op="${name}"]`);

function show(id) {
  const current = byId(id);
  for (const section of sections) section.hidden = section !== current;
  steps.forEach((step, index) => {
    if (sections[index] === current) step.setAttribute('aria-current', 'step');
    else step.removeAttribute('aria-current');
  });
  current.querySelector('h2').focus();
}

op('login').onclick = () => show('apply');
op('service').onchange = () => { op('apply-next').disabled = !op('service').value; };
op('apply-next').onclick = () => show('upload');
op('upload-back').onclick = () => show('apply');
function acceptSample() {
  byId('upload-status').textContent = '样例附件已就绪';
  op('upload-next').disabled = false;
}
op('upload').onclick = () => {
  op('attachment').value = '';
  acceptSample();
};
op('attachment').onchange = () => {
  const selected = op('attachment').files[0];
  const isSample = selected?.name === '演示申请书.txt';
  op('attachment').value = '';
  if (isSample) {
    acceptSample();
  } else {
    byId('upload-status').textContent = '请选择演示申请书.txt，或使用预设附件。';
    op('upload-next').disabled = true;
  }
};
op('upload-next').onclick = () => show('captcha');
op('captcha-back').onclick = () => show('upload');
op('verify').onclick = () => {
  if (op('captcha').value !== '2468') {
    byId('error').textContent = '演练码不正确，请重新输入。';
    op('captcha').focus();
    return;
  }
  byId('error').textContent = '';
  op('captcha').value = '';
  byId('summary').textContent = op('service').value;
  show('confirm');
};
op('confirm-back').onclick = () => show('apply');
op('submit').onclick = () => {
  byId('receipt').textContent = 'SIM-' + crypto.randomUUID().slice(0, 8).toUpperCase();
  show('done');
};
op('restart').onclick = () => location.reload();
