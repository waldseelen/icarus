/**
 * Gamepower Icarus — Web GUI Core Controller
 * Handles WAI-ARIA tab navigation, REST API state synchronization,
 * PixArt PMW3325 57-step DPI snapping, 11 RGB lighting modes,
 * and button remapping modal with focus trap.
 */

let state = {
  connected: false,
  devicePath: '',
  firmware: 'V901',
  activeProfile: 1,
  config: null,
  validDpis: [],
  pins: {},
  currentRemapK: 1,
};

let lastActiveElementBeforeModal = null;

const PIN_COORDINATES = {
  1: { x: 70, y: 97, name: 'Left Click', desc: 'Primary Left Switch' },
  2: { x: 170, y: 97, name: 'Right Click', desc: 'Primary Right Switch' },
  3: { x: 119, y: 126, name: 'Middle Click', desc: 'Scroll Wheel Click' },
  4: { x: 50, y: 219, name: 'Forward (Front Thumb)', desc: 'Front Thumb Button' },
  5: { x: 55, y: 275, name: 'Back (Rear Thumb)', desc: 'Rear Thumb Button' },
  6: { x: 132, y: 166, name: 'DPI +', desc: 'DPI Increment' },
  7: { x: 138, y: 207, name: 'DPI -', desc: 'DPI Decrement' },
  8: { x: 25, y: 186, name: 'Fire Key', desc: 'Rapid Fire Burst' },
  9: { x: 11, y: 260, name: 'Sniper / DPI Lock', desc: 'Sniper Paddle' },
};

const RGB_NAMES = {
  STREAMING: 'Colorful Streaming (Gökkuşağı)',
  STEADY: 'Steady (Sabit Tek Renk)',
  BREATHING: 'Breathing (Nefes Alma)',
  NEON: 'Neon (Spektral Döngü)',
  OFF: 'LED OFF (Işık Kapalı)',
};

function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2800);
}

async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    state.connected = data.connected;
    state.devicePath = data.device_path || '';
    state.firmware = data.firmware || 'V901';
    state.config = data.config || null;
    state.validDpis = data.valid_dpis || [];
    state.pins = data.pins || PIN_COORDINATES;
    state.activeProfile = (data.config && data.config.active_profile) || 1;
    renderAll();
  } catch (e) {
    state.connected = false;
    renderHeader();
    showToast('Failed to connect to Icarus daemon');
  }
}

function renderAll() {
  renderHeader();
  renderPins();
  const prof = getCurrentProfile();
  if (prof) {
    renderButtons(prof);
    renderDpi(prof);
    renderLighting(prof);
    renderPerformance(prof);
  }
}

function getCurrentProfile() {
  if (!state.config || !state.config.profiles) return null;
  return state.config.profiles[String(state.activeProfile)];
}

function renderHeader() {
  const badge = document.getElementById('device-badge');
  const txt = document.getElementById('device-status-text');
  if (!badge || !txt) return;

  if (state.connected) {
    badge.className = 'device-badge';
    txt.textContent = `Connected (${state.firmware}) • ${state.devicePath}`;
  } else {
    badge.className = 'device-badge disconnected';
    txt.textContent = 'Mouse Disconnected';
  }

  document.querySelectorAll('.profile-btn').forEach((btn) => {
    const p = parseInt(btn.dataset.profile, 10);
    const isActive = p === state.activeProfile;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-checked', isActive ? 'true' : 'false');
  });
}

function renderPins() {
  const container = document.getElementById('mouse-pins-container');
  if (!container) return;
  container.innerHTML = '';

  for (let k = 1; k <= 9; k++) {
    const pos = PIN_COORDINATES[k] || { x: 100, y: 100, name: `K${k}` };
    const pin = document.createElement('button');
    pin.type = 'button';
    pin.className = 'mouse-pin';
    pin.id = `pin-k${k}`;
    pin.textContent = k;
    pin.style.left = `${pos.x}px`;
    pin.style.top = `${pos.y}px`;
    pin.setAttribute('aria-label', `Button K${k}: ${pos.name}`);
    pin.title = `K${k}: ${pos.name}`;

    pin.addEventListener('click', () => openRemapModal(k));
    pin.addEventListener('mouseenter', () => highlightButtonRow(k));
    pin.addEventListener('mouseleave', () => unhighlightButtonRow(k));
    pin.addEventListener('focus', () => highlightButtonRow(k));
    pin.addEventListener('blur', () => unhighlightButtonRow(k));

    container.appendChild(pin);
  }
}

function highlightButtonRow(k) {
  document.querySelectorAll('.button-row').forEach((r) => r.classList.remove('highlight'));
  const row = document.getElementById(`btn-row-${k}`);
  if (row) row.classList.add('highlight');
  const pin = document.getElementById(`pin-k${k}`);
  if (pin) pin.classList.add('active');
}

function unhighlightButtonRow(k) {
  const row = document.getElementById(`btn-row-${k}`);
  if (row) row.classList.remove('highlight');
  const pin = document.getElementById(`pin-k${k}`);
  if (pin) pin.classList.remove('active');
}

function renderButtons(prof) {
  const container = document.getElementById('buttons-list');
  if (!container) return;
  container.innerHTML = '';

  for (let k = 1; k <= 9; k++) {
    const bInfo = (prof.buttons && prof.buttons[`K${k}`]) || { summary: 'Default', btype: 'MOUSE_CLICK' };
    const pInfo = PIN_COORDINATES[k] || { name: `Button ${k}`, desc: '' };
    const row = document.createElement('div');
    row.className = 'button-row';
    row.id = `btn-row-${k}`;
    row.setAttribute('role', 'listitem');

    row.innerHTML = `
      <div class="button-info">
        <span class="k-badge">K${k}</span>
        <div>
          <div class="btn-name">${pInfo.name}</div>
          <div class="btn-summary">${bInfo.summary || bInfo.btype}</div>
        </div>
      </div>
      <button type="button" class="btn-remap" onclick="openRemapModal(${k})" aria-label="Remap Button K${k} (${pInfo.name})">Remap</button>
    `;

    row.addEventListener('mouseenter', () => highlightButtonRow(k));
    row.addEventListener('mouseleave', () => unhighlightButtonRow(k));
    container.appendChild(row);
  }
}

function snapToValidDpi(dpi) {
  if (!state.validDpis || !state.validDpis.length) {
    const clamped = Math.max(400, Math.min(10000, dpi));
    return Math.round(clamped / 100) * 100;
  }
  return state.validDpis.reduce((prev, curr) => (Math.abs(curr - dpi) < Math.abs(prev - dpi) ? curr : prev));
}

function renderDpi(prof) {
  const container = document.getElementById('dpi-stages-list');
  if (!container) return;
  container.innerHTML = '';
  const active = prof.active_dpi_stage || 1;

  prof.dpi_stages.forEach((s) => {
    const isActive = s.stage === active;
    const row = document.createElement('div');
    row.className = `dpi-row ${isActive ? 'active' : ''}`;
    row.id = `dpi-stage-row-${s.stage}`;

    row.innerHTML = `
      <input type="radio" name="dpi-active-stage" ${isActive ? 'checked' : ''} onchange="setActiveDpiStage(${s.stage})" aria-label="Select Stage ${s.stage} as Active">
      <label style="display:flex; align-items:center; gap:4px">
        <input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="toggleDpiStage(${s.stage}, this.checked)" aria-label="Enable Stage ${s.stage}">
        <span class="dpi-stage-tag">S${s.stage}</span>
      </label>
      <input type="range" min="400" max="10000" step="100" value="${s.dpi}" class="form-range" oninput="onDpiSlider(${s.stage}, this.value)" aria-label="Stage ${s.stage} DPI Sensitivity Slider">
      <span class="dpi-val mono-text" id="dpi-val-${s.stage}">${s.dpi} DPI</span>
      <input type="color" value="${s.color || '#ff0000'}" class="form-color" oninput="onDpiColor(${s.stage}, this.value)" aria-label="Stage ${s.stage} Indicator Color">
    `;

    container.appendChild(row);
  });
}

function setActiveDpiStage(st) {
  const p = getCurrentProfile();
  if (p) {
    p.active_dpi_stage = st;
    renderDpi(p);
  }
}

function toggleDpiStage(st, en) {
  const p = getCurrentProfile();
  if (p && p.dpi_stages[st - 1]) {
    p.dpi_stages[st - 1].enabled = en;
  }
}

function onDpiSlider(st, val) {
  const snapped = snapToValidDpi(parseInt(val, 10));
  const p = getCurrentProfile();
  if (p && p.dpi_stages[st - 1]) {
    p.dpi_stages[st - 1].dpi = snapped;
  }
  const disp = document.getElementById(`dpi-val-${st}`);
  if (disp) disp.textContent = `${snapped} DPI`;
}

let liveApplyTimer = null;
function debounceLiveApply() {
  clearTimeout(liveApplyTimer);
  liveApplyTimer = setTimeout(async () => {
    if (!state.config) return;
    try {
      await fetch('/api/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.config),
      });
      showToast('Live preview updated');
    } catch (e) {}
  }, 200);
}

let scrollTimer = null;
function debounceSetScroll(factor) {
  clearTimeout(scrollTimer);
  scrollTimer = setTimeout(async () => {
    try {
      await fetch('/api/scroll', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ factor: parseFloat(factor) }),
      });
      showToast(`Scroll speed: ${factor}x`);
    } catch (e) {}
  }, 150);
}

function onDpiColor(st, col) {
  const p = getCurrentProfile();
  if (p && p.dpi_stages[st - 1]) {
    p.dpi_stages[st - 1].color = col;
    debounceLiveApply();
  }
}

function renderLighting(prof) {
  const sel = document.getElementById('rgb-effect-select');
  if (sel && sel.options.length === 0) {
    Object.keys(RGB_NAMES).forEach((k) => {
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = RGB_NAMES[k];
      sel.appendChild(opt);
    });
  }
  if (!sel) return;

  sel.value = prof.rgb.effect || 'STREAMING';
  const bri = document.getElementById('rgb-brightness');
  const spd = document.getElementById('rgb-speed');
  const dir = document.getElementById('rgb-direction-select');
  const sc = document.getElementById('rgb-static-color');
  const scHex = document.getElementById('rgb-static-hex');

  bri.value = prof.rgb.brightness || 4;
  spd.value = prof.rgb.speed || 2;
  dir.value = String(prof.rgb.direction || 0);
  sc.value = prof.rgb.single_color || '#ff0000';
  if (scHex) scHex.textContent = sc.value;

  document.getElementById('rgb-bri-val').textContent = bri.value;
  document.getElementById('rgb-spd-val').textContent = spd.value;

  const chOrder = document.getElementById('channel-order-select');
  if (chOrder) {
    chOrder.value = prof.channel_order || 'RGB';
    chOrder.onchange = () => {
      prof.channel_order = chOrder.value;
      debounceLiveApply();
    };
  }

  sel.onchange = () => {
    prof.rgb.effect = sel.value;
    updateRgbVisibility(sel.value);
    debounceLiveApply();
  };
  bri.oninput = () => {
    prof.rgb.brightness = parseInt(bri.value, 10);
    document.getElementById('rgb-bri-val').textContent = bri.value;
    debounceLiveApply();
  };
  spd.oninput = () => {
    prof.rgb.speed = parseInt(spd.value, 10);
    document.getElementById('rgb-spd-val').textContent = spd.value;
    debounceLiveApply();
  };
  dir.onchange = () => {
    prof.rgb.direction = parseInt(dir.value, 10);
    debounceLiveApply();
  };
  sc.oninput = () => {
    prof.rgb.single_color = sc.value;
    if (prof.rgb.effect === 'BREATHING') {
      if (!prof.rgb.breathing_colors) prof.rgb.breathing_colors = [];
      prof.rgb.breathing_colors[0] = sc.value;
    }
    if (scHex) scHex.textContent = sc.value;
    debounceLiveApply();
  };

  updateRgbVisibility(sel.value);
  renderSwatches(prof);
}

function updateRgbVisibility(eff) {
  const isOff = eff === 'OFF';
  const isStreaming = eff === 'STREAMING';
  const isSteady = eff === 'STEADY';
  const isReaction = eff === 'REACTION';
  const isBreathing = eff === 'BREATHING';
  const isNeon = eff === 'NEON';

  const showBrightness = !isOff;
  const showSpeed = !isOff && !isSteady;
  const showDirection = isStreaming;
  const showStaticColor = isSteady || isReaction || isBreathing;

  const grpBri = document.getElementById('grp-rgb-brightness');
  const grpSpd = document.getElementById('grp-rgb-speed');
  const grpDir = document.getElementById('grp-rgb-direction');
  const grpColor = document.getElementById('grp-rgb-static-color');
  const grpBreath = document.getElementById('grp-rgb-breathing-colors');
  const grpZone = document.getElementById('grp-rgb-zone-colors');
  const grpFlicker = document.getElementById('grp-rgb-flicker-colors');
  const grpOff = document.getElementById('grp-rgb-off-notice');

  if (grpBri) grpBri.style.display = showBrightness ? 'block' : 'none';
  if (grpSpd) grpSpd.style.display = showSpeed ? 'block' : 'none';
  if (grpDir) grpDir.style.display = showDirection ? 'block' : 'none';
  if (grpColor) grpColor.style.display = showStaticColor ? 'block' : 'none';
  if (grpBreath) grpBreath.style.display = isBreathing ? 'block' : 'none';
  if (grpZone) grpZone.style.display = 'none';
  if (grpFlicker) grpFlicker.style.display = 'none';
  if (grpOff) grpOff.style.display = isOff ? 'flex' : 'none';

  const rainbowNotice = document.getElementById('rainbow-effect-notice');
  if (rainbowNotice) {
    rainbowNotice.style.display = (isStreaming || isNeon) ? 'block' : 'none';
  }
}

function renderSwatches(prof) {
  const bCont = document.getElementById('breathing-swatches');
  if (bCont) {
    bCont.innerHTML = '';
    (prof.rgb.breathing_colors || []).forEach((c, i) => {
      const item = document.createElement('div');
      item.className = 'swatch-item';
      item.innerHTML = `
        <input type="color" value="${c}" class="form-color" aria-label="Breathing Color ${i + 1}" onchange="updateBreathingColor(${i}, this.value)">
        <span>#${i + 1}</span>
      `;
      bCont.appendChild(item);
    });
  }

  const zCont = document.getElementById('zone-swatches');
  if (zCont) {
    zCont.innerHTML = '';
    (prof.rgb.zone_colors || []).forEach((c, i) => {
      const item = document.createElement('div');
      item.className = 'swatch-item';
      item.innerHTML = `
        <input type="color" value="${c}" class="form-color" aria-label="Zone ${i + 1} Color" onchange="updateZoneColor(${i}, this.value)">
        <span>Z${i + 1}</span>
      `;
      zCont.appendChild(item);
    });
  }

  const fCont = document.getElementById('flicker-swatches');
  if (fCont) {
    fCont.innerHTML = '';
    (prof.rgb.flicker_colors || []).forEach((c, i) => {
      const item = document.createElement('div');
      item.className = 'swatch-item';
      item.innerHTML = `
        <input type="color" value="${c}" class="form-color" aria-label="Flicker Color ${i + 1}" onchange="updateFlickerColor(${i}, this.value)">
        <span>C${i + 1}</span>
      `;
      fCont.appendChild(item);
    });
  }
}

function updateBreathingColor(idx, val) {
  const p = getCurrentProfile();
  if (p && p.rgb && p.rgb.breathing_colors) {
    p.rgb.breathing_colors[idx] = val;
    debounceLiveApply();
  }
}

function updateZoneColor(idx, val) {
  const p = getCurrentProfile();
  if (p && p.rgb && p.rgb.zone_colors) {
    p.rgb.zone_colors[idx] = val;
    debounceLiveApply();
  }
}

function updateFlickerColor(idx, val) {
  const p = getCurrentProfile();
  if (p && p.rgb && p.rgb.flicker_colors) {
    p.rgb.flicker_colors[idx] = val;
    debounceLiveApply();
  }
}

function renderPerformance(prof) {
  const scrollSlider = document.getElementById('scroll-factor-slider');
  const scrollVal = document.getElementById('scroll-factor-val');
  if (scrollSlider) {
    const curScroll = state.config && state.config.scroll_factor !== undefined ? state.config.scroll_factor : 1.0;
    scrollSlider.value = curScroll;
    if (scrollVal) scrollVal.textContent = parseFloat(curScroll).toFixed(1);

    scrollSlider.oninput = () => {
      const val = parseFloat(scrollSlider.value).toFixed(1);
      if (scrollVal) scrollVal.textContent = val;
      if (state.config) state.config.scroll_factor = parseFloat(val);
      debounceSetScroll(val);
    };
  }

  document.querySelectorAll('#polling-rate-group .radio-pill').forEach((pill) => {
    const hz = parseInt(pill.dataset.hz, 10);
    const isSel = hz === prof.polling_rate_hz;
    pill.classList.toggle('selected', isSel);
    pill.setAttribute('aria-checked', isSel ? 'true' : 'false');
    pill.onclick = () => {
      prof.polling_rate_hz = hz;
      renderPerformance(prof);
    };
  });

  document.querySelectorAll('#lod-group .radio-pill').forEach((pill) => {
    const lod = pill.dataset.lod;
    const isSel = lod === prof.lod;
    pill.classList.toggle('selected', isSel);
    pill.setAttribute('aria-checked', isSel ? 'true' : 'false');
    pill.onclick = () => {
      prof.lod = lod;
      renderPerformance(prof);
    };
  });
}

function openRemapModal(k) {
  state.currentRemapK = k;
  lastActiveElementBeforeModal = document.activeElement;
  const pInfo = PIN_COORDINATES[k] || { name: `Button ${k}` };
  const title = document.getElementById('remap-modal-title');
  if (title) title.textContent = `Remap K${k} — ${pInfo.name}`;

  const prof = getCurrentProfile();
  const curBtn = prof && prof.buttons ? prof.buttons[`K${k}`] : null;
  const sel = document.getElementById('modal-action-select');
  if (sel) {
    if (curBtn) {
      if (curBtn.btype === 'MULTIMEDIA') {
        const key = `${curBtn.data0},${curBtn.data1},${curBtn.data2}`;
        if (curBtn.data1 !== 0 || curBtn.data2 !== 0) {
          sel.value = 'system';
          const sysSel = document.getElementById('modal-system-select');
          if (sysSel) {
            const sysMap = {
              '0,2,0': 'explorer',
              '0,32,0': 'calculator',
              '0,16,0': 'mail',
              '0,0,1': 'web_search',
              '0,0,2': 'web_home',
              '0,0,4': 'web_back',
              '0,0,8': 'web_forward',
              '0,0,16': 'web_stop',
              '0,0,32': 'web_refresh',
              '0,0,64': 'web_favorites',
            };
            if (sysMap[key]) sysSel.value = sysMap[key];
          }
        } else {
          sel.value = 'multimedia';
          const medSel = document.getElementById('modal-media-select');
          if (medSel) {
            const medMap = {
              '8,0,0': 'play_pause',
              '1,0,0': 'next_track',
              '2,0,0': 'prev_track',
              '4,0,0': 'stop',
              '64,0,0': 'volume_up',
              '128,0,0': 'volume_down',
              '16,0,0': 'mute',
              '0,1,0': 'media_player',
            };
            if (medMap[key]) medSel.value = medMap[key];
          }
        }
      } else if (curBtn.btype === 'SPECIAL') {
        sel.value = 'special';
        const specSel = document.getElementById('modal-special-select');
        if (specSel) {
          const specMap = {
            1: 'profile_switch',
            2: 'polling_rate_switch',
            4: 'lighting_toggle',
            6: 'lighting_effect_switch',
            7: 'lighting_color_switch',
            8: 'lighting_speed_switch',
            9: 'lighting_brightness_switch',
          };
          if (specMap[curBtn.data0]) specSel.value = specMap[curBtn.data0];
        }
      } else if (curBtn.btype === 'MULTI_CLICK') {
        sel.value = 'click';
        const clkSel = document.getElementById('modal-click-select');
        if (clkSel) clkSel.value = curBtn.data0 === 2 ? 'TRIPLE' : 'DOUBLE';
      } else if (curBtn.btype === 'REPEATED' || curBtn.btype === 'FIRE') {
        sel.value = 'fire';
      } else if (curBtn.btype === 'DPI_LOCK' || curBtn.btype === 'SNIPER') {
        sel.value = 'sniper';
      } else if (curBtn.btype === 'DPI_SWITCH') {
        sel.value = 'dpi';
      } else if (curBtn.btype === 'MACRO') {
        sel.value = 'macro';
      } else if (curBtn.btype === 'DISABLED') {
        sel.value = 'disabled';
      } else {
        sel.value = 'click';
        const clkSel = document.getElementById('modal-click-select');
        if (clkSel) {
          const clkMap = { 1: 'LEFT', 2: 'RIGHT', 4: 'MIDDLE', 8: 'BACK', 16: 'FORWARD' };
          if (clkMap[curBtn.data0]) clkSel.value = clkMap[curBtn.data0];
        }
      }
    } else {
      sel.value = k === 8 ? 'fire' : (k === 9 ? 'sniper' : 'click');
    }
    updateModalSections(sel.value);
  }

  const modal = document.getElementById('remap-modal');
  modal.style.display = 'flex';
  modal.classList.add('open');

  // Focus trap: focus first interactive control
  setTimeout(() => {
    const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusable.length) focusable[0].focus();
  }, 20);
}

function closeRemapModal() {
  const modal = document.getElementById('remap-modal');
  modal.classList.remove('open');
  modal.style.display = 'none';
  if (lastActiveElementBeforeModal) {
    lastActiveElementBeforeModal.focus();
  }
}

function setScrollPreset(factor) {
  const scrollSlider = document.getElementById('scroll-factor-slider');
  const scrollVal = document.getElementById('scroll-factor-val');
  if (scrollSlider) scrollSlider.value = factor;
  if (scrollVal) scrollVal.textContent = parseFloat(factor).toFixed(1);
  if (state.config) state.config.scroll_factor = parseFloat(factor);
  debounceSetScroll(factor);
}

function updateModalSections(act) {
  ['click', 'multimedia', 'system', 'special', 'fire', 'sniper', 'dpi', 'macro', 'key'].forEach((s) => {
    const el = document.getElementById(`modal-sec-${s}`);
    if (el) el.style.display = act === s ? 'block' : 'none';
  });
}

async function saveRemapModal() {
  const act = document.getElementById('modal-action-select').value;
  const k = state.currentRemapK;
  let payload = { profile: state.activeProfile, k: k, action: act };

  if (act === 'click') {
    const clk = document.getElementById('modal-click-select').value;
    if (clk === 'DOUBLE') {
      payload = { profile: state.activeProfile, k: k, action: 'multiclick', count: 2 };
    } else if (clk === 'TRIPLE') {
      payload = { profile: state.activeProfile, k: k, action: 'multiclick', count: 3 };
    } else {
      const masks = { LEFT: 1, RIGHT: 2, MIDDLE: 4, BACK: 8, FORWARD: 16 };
      payload = {
        profile: state.activeProfile,
        k: k,
        btype: 'MOUSE_CLICK',
        data0: masks[clk] || 1,
        data1: 0,
        data2: 0,
      };
    }
  } else if (act === 'multimedia') {
    const mediaAct = document.getElementById('modal-media-select').value;
    payload = {
      profile: state.activeProfile,
      k: k,
      action: 'multimedia',
      sub_action: mediaAct,
    };
  } else if (act === 'system') {
    const sysAct = document.getElementById('modal-system-select').value;
    payload = {
      profile: state.activeProfile,
      k: k,
      action: 'multimedia',
      sub_action: sysAct,
    };
  } else if (act === 'special') {
    const specAct = document.getElementById('modal-special-select').value;
    payload = {
      profile: state.activeProfile,
      k: k,
      action: 'special',
      sub_action: specAct,
    };
  } else if (act === 'fire') {
    payload.repeat = parseInt(document.getElementById('modal-fire-repeat').value, 10);
    payload.interval_ms = parseInt(document.getElementById('modal-fire-interval').value, 10);
  } else if (act === 'sniper') {
    payload.stage = parseInt(document.getElementById('modal-sniper-stage').value, 10);
  } else if (act === 'dpi') {
    const dMap = { CYCLE: 0, UP: 1, DOWN: 2 };
    payload = {
      profile: state.activeProfile,
      k: k,
      btype: 'DPI_SWITCH',
      data0: dMap[document.getElementById('modal-dpi-action').value],
      data1: 0,
      data2: 0,
    };
  } else if (act === 'macro') {
    payload.macro_slot = parseInt(document.getElementById('modal-macro-slot').value, 10);
    payload.loop_mode = parseInt(document.getElementById('modal-macro-loop').value, 10);
  } else if (act === 'key') {
    const keyVal = document.getElementById('modal-key-input').value.trim();
    payload = {
      profile: state.activeProfile,
      k: k,
      btype: 'KEYBOARD_COMBO',
      data0: 0,
      key_combo: keyVal,
    };
  } else if (act === 'disabled') {
    payload = {
      profile: state.activeProfile,
      k: k,
      btype: 'DISABLED',
      data0: 0,
      data1: 0,
      data2: 0,
    };
  }

  showToast(`Binding K${k}...`);
  try {
    const res = await fetch('/api/bind', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (d.success) {
      showToast(`K${k} bound: ${d.summary}`);
      closeRemapModal();
      loadStatus();
    } else {
      showToast('Bind error: ' + (d.error || ''));
    }
  } catch (e) {
    showToast('Failed to bind button');
  }
}

async function applyToHardware() {
  if (!state.config) return;
  showToast('Writing configuration to mouse flash...');
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.config),
    });
    const result = await res.json();
    if (result.success) {
      showToast('Hardware successfully committed!');
      loadStatus();
    } else {
      showToast('Error applying: ' + (result.error || ''));
    }
  } catch (e) {
    showToast('Communication failure');
  }
}

function setupA11yTabs() {
  const tabs = Array.from(document.querySelectorAll('.nav-tab'));
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab));

    tab.addEventListener('keydown', (e) => {
      let nextIndex = null;
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        nextIndex = (index + 1) % tabs.length;
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        nextIndex = (index - 1 + tabs.length) % tabs.length;
      } else if (e.key === 'Home') {
        e.preventDefault();
        nextIndex = 0;
      } else if (e.key === 'End') {
        e.preventDefault();
        nextIndex = tabs.length - 1;
      }
      if (nextIndex !== null) {
        tabs[nextIndex].focus();
        activateTab(tabs[nextIndex]);
      }
    });
  });
}

function activateTab(targetTab) {
  const targetId = targetTab.dataset.tab;
  document.querySelectorAll('.nav-tab').forEach((t) => {
    const isCurrent = t === targetTab;
    t.classList.toggle('active', isCurrent);
    t.setAttribute('aria-selected', isCurrent ? 'true' : 'false');
    t.setAttribute('tabindex', isCurrent ? '0' : '-1');
  });

  document.querySelectorAll('.tab-pane').forEach((p) => {
    p.classList.toggle('active', p.id === targetId);
  });
}

function setupModalFocusTrap() {
  const modal = document.getElementById('remap-modal');
  if (!modal) return;

  modal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeRemapModal();
      return;
    }
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault();
      saveRemapModal();
      return;
    }
    if (e.key === 'Tab') {
      const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setupA11yTabs();
  setupModalFocusTrap();

  document.querySelectorAll('.profile-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const p = parseInt(btn.dataset.profile, 10);
      state.activeProfile = p;
      renderAll();
      try {
        await fetch('/api/switch-profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profile: p }),
        });
        showToast(`Switched to Profile ${p}`);
      } catch (e) {
        showToast('Error switching profile');
      }
    });
  });

  const selAction = document.getElementById('modal-action-select');
  if (selAction) {
    selAction.onchange = (e) => updateModalSections(e.target.value);
  }

  const btnCloseModal = document.getElementById('btn-close-modal');
  if (btnCloseModal) btnCloseModal.onclick = closeRemapModal;

  const btnCancelModal = document.getElementById('btn-cancel-modal');
  if (btnCancelModal) btnCancelModal.onclick = closeRemapModal;

  const btnSaveModal = document.getElementById('btn-save-modal');
  if (btnSaveModal) btnSaveModal.onclick = saveRemapModal;

  const btnApplyAll = document.getElementById('btn-apply-all');
  if (btnApplyAll) btnApplyAll.onclick = applyToHardware;

  const btnReload = document.getElementById('btn-reload-status');
  if (btnReload) btnReload.onclick = loadStatus;

  const btnExit = document.getElementById('btn-exit-app');
  if (btnExit) {
    btnExit.onclick = async () => {
      try {
        await fetch('/api/exit', { method: 'POST' });
      } catch (e) {}
      window.close();
    };
  }

  const btnPull = document.getElementById('btn-pull-json');
  if (btnPull) {
    btnPull.onclick = async () => {
      showToast('Pulling from mouse...');
      try {
        await fetch('/api/pull', { method: 'POST' });
        showToast('Saved to ~/.config/icarus/config.json');
        loadStatus();
      } catch (e) {
        showToast('Pull failed');
      }
    };
  }

  const btnApply = document.getElementById('btn-apply-json');
  if (btnApply) {
    btnApply.onclick = async () => {
      showToast('Applying config.json...');
      try {
        await fetch('/api/apply', { method: 'POST' });
        showToast('Applied to mouse flash!');
        loadStatus();
      } catch (e) {
        showToast('Apply failed');
      }
    };
  }

  const mSel = document.getElementById('modal-macro-slot');
  if (mSel) {
    mSel.innerHTML = '';
    for (let s = 1; s <= 16; s++) {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = `Macro Slot ${s}`;
      mSel.appendChild(opt);
    }
  }

  loadStatus();
});
