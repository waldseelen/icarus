/**
 * Gamepower Icarus — Macro Studio Controller
 * Handles 16-slot onboard flash management, step-by-step timeline,
 * live keystroke recording with 12-bit ms delays, and OEM .BKM import.
 */

let macroState = {
  activeSlot: 1,
  macros: [],
  recording: false,
  lastRecordTime: 0,
};

async function loadMacros() {
  try {
    const res = await fetch('/api/macros');
    const data = await res.json();
    macroState.macros = data.macros || [];
    renderMacroSlots();
    renderActiveMacroDetail();
  } catch (e) {
    showToast('Failed to load onboard macros');
  }
}

function renderMacroSlots() {
  const cont = document.getElementById('macro-slot-container');
  if (!cont) return;
  cont.innerHTML = '';

  for (let s = 1; s <= 16; s++) {
    const m = macroState.macros.find((x) => x.id === s) || { id: s, name: `Macro ${s}`, events: [] };
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `macro-slot-btn ${s === macroState.activeSlot ? 'active' : ''}`;
    btn.id = `macro-slot-btn-${s}`;
    btn.setAttribute('role', 'listitem');
    btn.setAttribute('aria-label', `Select Slot ${s}: ${m.name}`);

    const count = m.events ? m.events.length : 0;
    btn.innerHTML = `
      <span style="font-weight:600">Slot ${s}: ${m.name || `Macro ${s}`}</span>
      <span class="slot-badge">${count} ev</span>
    `;

    btn.onclick = () => {
      macroState.activeSlot = s;
      renderMacroSlots();
      renderActiveMacroDetail();
    };

    cont.appendChild(btn);
  }
}

function getActiveMacro() {
  let m = macroState.macros.find((x) => x.id === macroState.activeSlot);
  if (!m) {
    m = {
      id: macroState.activeSlot,
      name: `Macro ${macroState.activeSlot}`,
      loop_mode: 'REPEAT_COUNT',
      repeat_count: 1,
      events: [],
    };
    macroState.macros.push(m);
  }
  return m;
}

function renderActiveMacroDetail() {
  const m = getActiveMacro();
  const title = document.getElementById('macro-title-input');
  if (title) {
    title.value = m.name || `Macro ${m.id}`;
    title.oninput = () => {
      m.name = title.value;
      const slotBtn = document.getElementById(`macro-slot-btn-${m.id}`);
      if (slotBtn) {
        const count = m.events ? m.events.length : 0;
        slotBtn.innerHTML = `
          <span style="font-weight:600">Slot ${m.id}: ${m.name}</span>
          <span class="slot-badge">${count} ev</span>
        `;
      }
    };
  }

  const loopMode = m.loop_mode || 'REPEAT_COUNT';
  document.querySelectorAll('#macro-loop-group .radio-pill').forEach((pill) => {
    const isSelected = pill.dataset.mode === loopMode;
    pill.classList.toggle('selected', isSelected);
    pill.setAttribute('aria-checked', isSelected ? 'true' : 'false');
    pill.onclick = () => {
      m.loop_mode = pill.dataset.mode;
      renderActiveMacroDetail();
    };
  });

  const repGroup = document.getElementById('grp-repeat-count');
  if (repGroup) {
    repGroup.style.display = loopMode === 'REPEAT_COUNT' ? 'block' : 'none';
    const repInput = document.getElementById('macro-repeat-count');
    if (repInput) {
      repInput.value = m.repeat_count || 1;
      repInput.oninput = () => {
        m.repeat_count = Math.max(1, Math.min(255, parseInt(repInput.value, 10) || 1));
      };
    }
  }

  const badge = document.getElementById('timeline-count-badge');
  if (badge) {
    badge.textContent = `${(m.events && m.events.length) || 0} / 168`;
  }

  renderTimelineEvents(m);
}

function renderTimelineEvents(m) {
  const list = document.getElementById('timeline-events-list');
  if (!list) return;
  list.innerHTML = '';

  if (!m.events || !m.events.length) {
    list.innerHTML = `
      <div style="padding:28px 16px; text-align:center; color:var(--text-faint); font-size:11px">
        No events in this macro slot. Click <strong>Record</strong> to capture keystrokes or <strong>+ Step</strong> to add manually.
      </div>
    `;
    return;
  }

  m.events.forEach((ev, idx) => {
    const row = document.createElement('div');
    row.className = 'event-row';
    row.setAttribute('role', 'listitem');
    const act = ev.action || 'KEY_DOWN';
    const code = ev.code !== undefined ? ev.code : 'a';
    const delay = ev.delay_ms || 15;

    row.innerHTML = `
      <span class="ev-idx">#${idx + 1}</span>
      <select class="ev-type" onchange="updateEventAction(${idx}, this.value)" aria-label="Event ${idx + 1} Action">
        <option value="KEY_DOWN" ${act === 'KEY_DOWN' ? 'selected' : ''}>KeyDown</option>
        <option value="KEY_UP" ${act === 'KEY_UP' ? 'selected' : ''}>KeyUp</option>
        <option value="BTN_DOWN" ${act === 'BTN_DOWN' ? 'selected' : ''}>BtnDown</option>
        <option value="BTN_UP" ${act === 'BTN_UP' ? 'selected' : ''}>BtnUp</option>
        <option value="WHEEL" ${act === 'WHEEL' ? 'selected' : ''}>Wheel</option>
        <option value="MOVE_X" ${act === 'MOVE_X' ? 'selected' : ''}>MoveX</option>
        <option value="MOVE_Y" ${act === 'MOVE_Y' ? 'selected' : ''}>MoveY</option>
      </select>
      <input type="text" class="ev-code" value="${code}" onchange="updateEventCode(${idx}, this.value)" aria-label="Event ${idx + 1} Scancode">
      <div class="ev-delay">
        <input type="number" min="1" max="4095" value="${delay}" onchange="updateEventDelay(${idx}, this.value)" aria-label="Event ${idx + 1} Delay Milliseconds">
        <span>ms</span>
      </div>
      <button type="button" class="btn-del-ev" onclick="deleteMacroEvent(${idx})" aria-label="Delete Event ${idx + 1}">&times;</button>
    `;

    list.appendChild(row);
  });
}

function updateEventAction(idx, val) {
  const m = getActiveMacro();
  if (m.events && m.events[idx]) m.events[idx].action = val;
}

function updateEventCode(idx, val) {
  const m = getActiveMacro();
  if (m.events && m.events[idx]) m.events[idx].code = val;
}

function updateEventDelay(idx, val) {
  const m = getActiveMacro();
  if (m.events && m.events[idx]) {
    m.events[idx].delay_ms = Math.max(1, Math.min(4095, parseInt(val, 10) || 15));
  }
}

function deleteMacroEvent(idx) {
  const m = getActiveMacro();
  m.events.splice(idx, 1);
  renderActiveMacroDetail();
  renderMacroSlots();
}

function addMacroEvent() {
  const m = getActiveMacro();
  if (m.events.length >= 168) {
    showToast('Maximum 168 events reached for hardware slot');
    return;
  }
  m.events.push({ action: 'KEY_DOWN', code: 'space', delay_ms: 20 });
  m.events.push({ action: 'KEY_UP', code: 'space', delay_ms: 20 });
  renderActiveMacroDetail();
  renderMacroSlots();
}

function toggleKeystrokeRecording() {
  macroState.recording = !macroState.recording;
  const btn = document.getElementById('btn-record-macro');
  const txt = document.getElementById('rec-btn-text');

  if (macroState.recording) {
    btn.classList.add('recording');
    if (txt) txt.textContent = 'Stop Rec';
    macroState.lastRecordTime = performance.now();
    window.addEventListener('keydown', onRecordKeyDown, true);
    window.addEventListener('keyup', onRecordKeyUp, true);
    showToast('Recording keystrokes... press keys on keyboard');
  } else {
    btn.classList.remove('recording');
    if (txt) txt.textContent = 'Record';
    window.removeEventListener('keydown', onRecordKeyDown, true);
    window.removeEventListener('keyup', onRecordKeyUp, true);
    showToast('Recording finished');
  }
}

function normalizeKey(key) {
  if (key === ' ') return 'space';
  return key.toLowerCase();
}

function onRecordKeyDown(e) {
  if (!macroState.recording) return;
  // Ignore Tab / Escape so user can still exit recording or navigate
  if (e.key === 'Escape') {
    toggleKeystrokeRecording();
    return;
  }
  e.preventDefault();
  e.stopPropagation();

  const now = performance.now();
  const delay = Math.max(1, Math.min(4095, Math.round(now - macroState.lastRecordTime)));
  macroState.lastRecordTime = now;

  const m = getActiveMacro();
  if (m.events.length < 168) {
    m.events.push({
      action: 'KEY_DOWN',
      code: normalizeKey(e.key),
      delay_ms: delay,
    });
    renderTimelineEvents(m);
    renderMacroSlots();
  } else {
    showToast('Slot full (168 events max)');
    toggleKeystrokeRecording();
  }
}

function onRecordKeyUp(e) {
  if (!macroState.recording) return;
  if (e.key === 'Escape') return;
  e.preventDefault();
  e.stopPropagation();

  const now = performance.now();
  const delay = Math.max(1, Math.min(4095, Math.round(now - macroState.lastRecordTime)));
  macroState.lastRecordTime = now;

  const m = getActiveMacro();
  if (m.events.length < 168) {
    m.events.push({
      action: 'KEY_UP',
      code: normalizeKey(e.key),
      delay_ms: delay,
    });
    renderTimelineEvents(m);
    renderMacroSlots();
  }
}

async function saveAndFlashActiveMacro() {
  const m = getActiveMacro();
  showToast(`Saving & flashing Slot ${m.id} ('${m.name}')...`);
  try {
    const saveRes = await fetch('/api/macros', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(m),
    });
    const saveJson = await saveRes.json();
    if (!saveJson.success) {
      showToast('Failed to save macro');
      return;
    }

    // Try direct slot flash first, fallback to /api/macros/flash
    let flashRes = await fetch(`/api/macros/slot/${m.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: m.id, macro: m }),
    });

    if (flashRes.status === 404) {
      flashRes = await fetch('/api/macros/flash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: m.id, macro: m }),
      });
    }

    const flashJson = await flashRes.json();
    if (flashJson.success) {
      showToast(`Macro #${m.id} flashed to mouse hardware (${m.events.length} events)!`);
      loadMacros();
    } else {
      showToast('Flash failed: ' + (flashJson.error || ''));
    }
  } catch (e) {
    showToast('Communication error during macro flash');
  }
}

function initBkmHandlers() {
  const dropzone = document.getElementById('bkm-drop-target');
  const fileInput = document.getElementById('bkm-file-input');
  if (!dropzone || !fileInput) return;

  dropzone.onclick = () => fileInput.click();
  dropzone.onkeydown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  };

  dropzone.ondragover = (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  };
  dropzone.ondragleave = () => dropzone.classList.remove('dragover');
  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadBkmFile(e.dataTransfer.files[0]);
    }
  };

  fileInput.onchange = (e) => {
    if (e.target.files && e.target.files[0]) {
      uploadBkmFile(e.target.files[0]);
    }
  };

  document.querySelectorAll('.bkm-chip').forEach((chip) => {
    chip.onclick = async () => {
      const p = chip.dataset.path;
      showToast(`Importing ${p}...`);
      try {
        const res = await fetch('/api/import-bkm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: p, profile: state.activeProfile }),
        });
        const d = await res.json();
        if (d.success) {
          showToast(`Imported ${d.macro_count} macros from backup!`);
          loadMacros();
          loadStatus();
        } else {
          showToast('Import error: ' + (d.error || ''));
        }
      } catch (err) {
        showToast('Failed to import backup');
      }
    };
  });
}

function uploadBkmFile(file) {
  showToast(`Reading ${file.name}...`);
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = reader.result.split(',')[1];
    try {
      const res = await fetch('/api/import-bkm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data_b64: b64, filename: file.name, profile: state.activeProfile }),
      });
      const d = await res.json();
      if (d.success) {
        showToast(`Imported ${d.macro_count} macros from ${file.name}!`);
        loadMacros();
        loadStatus();
      } else {
        showToast('BKM import failed: ' + (d.error || ''));
      }
    } catch (e) {
      showToast('Error uploading BKM');
    }
  };
  reader.readAsDataURL(file);
}

document.addEventListener('DOMContentLoaded', () => {
  const btnRec = document.getElementById('btn-record-macro');
  if (btnRec) btnRec.onclick = toggleKeystrokeRecording;
  const btnAdd = document.getElementById('btn-add-event');
  if (btnAdd) btnAdd.onclick = addMacroEvent;
  const btnFlash = document.getElementById('btn-flash-macro');
  if (btnFlash) btnFlash.onclick = saveAndFlashActiveMacro;

  initBkmHandlers();
  loadMacros();
});
