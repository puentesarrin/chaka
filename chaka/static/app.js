'use strict';

// ── Tab switching ──────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
    if (tab === 'clients') refreshClients();
    if (tab === 'channels') startChannelsPolling();
    if (tab === 'voice-log') loadVoiceLog(1);
    if (tab === 'logs') loadLogs(1);
    if (tab === 'server-log') refreshServerLog();
  });
});

// ── Helpers ───────────────────────────────────────────────────
function fmtDatetime(iso) {
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  if (localStorage.getItem('tzMode') === 'utc') {
    return d.toLocaleString(undefined, { timeZone: 'UTC' }) + ' UTC';
  }
  return d.toLocaleString();
}
function fmtDuration(iso) {
  const secs = Math.floor((Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()) / 1000);
  if (secs < 60) return secs + 's';
  const m = Math.floor(secs / 60), s = secs % 60;
  if (m < 60) return m + 'm ' + s + 's';
  const h = Math.floor(m / 60), mm = m % 60;
  return h + 'h ' + mm + 'm';
}
function refreshTokenTimestamps() {
  document.querySelectorAll('span.ts[data-ts]').forEach(el => {
    el.textContent = fmtDatetime(el.dataset.ts);
  });
}

function refreshActiveTab() {
  if (document.getElementById('tab-clients').classList.contains('active')) refreshClients();
  else if (document.getElementById('tab-logs').classList.contains('active')) loadLogs(currentLogPage);
}

function updateTzBtn() {
  const btn = document.getElementById('tz-toggle');
  if (!btn) return;
  const isUtc = localStorage.getItem('tzMode') === 'utc';
  btn.textContent = isUtc ? 'UTC' : 'Local';
  btn.title = isUtc ? 'Showing UTC — click for local time' : 'Showing local time — click for UTC';
}

window.toggleTzMode = function() {
  const next = localStorage.getItem('tzMode') === 'utc' ? 'local' : 'utc';
  localStorage.setItem('tzMode', next);
  updateTzBtn();
  refreshActiveTab();
  refreshTokenTimestamps();
  if (_eventsTokenId && document.getElementById('events-modal').style.display === 'flex') {
    loadEvents(_eventsTokenId, 1);
  }
  if (_connectionLogOpen) loadConnectionLog(_connectionLogPage);
};

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function trunc(s, n) { return s && s.length > n ? s.slice(0, n) + '…' : (s || ''); }

// ── Toast ─────────────────────────────────────────────────────
function toast(msg, type = 'success') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    el.addEventListener('animationend', () => el.remove());
  }, 3000);
}

// ── Confirm modal ─────────────────────────────────────────────
function showConfirm(msg) {
  return new Promise((resolve) => {
    document.getElementById('confirm-message').textContent = msg;
    const modal = document.getElementById('confirm-modal');
    modal.style.display = 'flex';

    function done(result) {
      modal.style.display = 'none';
      document.getElementById('confirm-ok').removeEventListener('click', onOk);
      document.getElementById('confirm-cancel').removeEventListener('click', onCancel);
      document.getElementById('confirm-modal').querySelector('.modal-overlay').removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    }
    function onOk() { done(true); }
    function onCancel() { done(false); }
    function onKey(e) { if (e.key === 'Escape') done(false); }

    document.getElementById('confirm-ok').addEventListener('click', onOk);
    document.getElementById('confirm-cancel').addEventListener('click', onCancel);
    document.getElementById('confirm-modal').querySelector('.modal-overlay').addEventListener('click', onCancel);
    document.addEventListener('keydown', onKey);
  });
}

// ── Copy to clipboard ─────────────────────────────────────────
function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = orig; }, 1500);
    } else {
      toast('Copied to clipboard');
    }
  }).catch(() => toast('Failed to copy', 'error'));
}

// ── Send message modal ────────────────────────────────────────
window.openSendModal = async function() {
  document.getElementById('send-modal').style.display = 'flex';
  document.getElementById('send-form').reset();
  document.getElementById('send-btn').disabled = false;
  document.getElementById('send-form').querySelector('[name="scope"]').focus();

  const container = document.getElementById('send-recipients');
  container.innerHTML = '<span class="muted" style="font-size:12px">Loading…</span>';
  try {
    const r = await fetch('/api/clients');
    if (!r.ok) throw new Error();
    const clients = await r.json();
    const receivable = clients.filter(c => c.can_receive);
    if (receivable.length === 0) {
      container.innerHTML = '<span class="muted" style="font-size:12px">No connected clients with receive permission</span>';
      return;
    }
    container.innerHTML = `
      <label style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;cursor:pointer">
        <input type="checkbox" id="send-all" checked onchange="toggleAllRecipients(this)">
        All clients (${receivable.length})
      </label>
      <div style="height:1px;background:var(--border);margin:2px 0"></div>
      ${receivable.map(c => `
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;font-weight:400;cursor:pointer">
          <input type="checkbox" class="send-recipient" value="${c.token_id}" checked onchange="updateAllRecipientsCheckbox()">
          ${esc(c.token_name)}
        </label>
      `).join('')}
    `;
  } catch (_) {
    container.innerHTML = '<span class="muted" style="font-size:12px">Failed to load clients</span>';
  }
};
window.closeSendModal = function() {
  document.getElementById('send-modal').style.display = 'none';
};
window.toggleAllRecipients = function(el) {
  document.querySelectorAll('.send-recipient').forEach(cb => { cb.checked = el.checked; });
};
window.updateAllRecipientsCheckbox = function() {
  const cbs = [...document.querySelectorAll('.send-recipient')];
  const allCb = document.getElementById('send-all');
  if (!allCb || cbs.length === 0) return;
  const checkedCount = cbs.filter(c => c.checked).length;
  allCb.indeterminate = checkedCount > 0 && checkedCount < cbs.length;
  allCb.checked = checkedCount === cbs.length;
};

window.submitSendMessage = async function(e) {
  e.preventDefault();
  const form = e.target;
  const btn = document.getElementById('send-btn');
  btn.disabled = true;

  const allCb = document.getElementById('send-all');
  const recipientCbs = [...document.querySelectorAll('.send-recipient')];
  const checkedCbs = recipientCbs.filter(cb => cb.checked);
  if (recipientCbs.length > 0 && checkedCbs.length === 0) {
    toast('Select at least one recipient', 'error');
    btn.disabled = false;
    return;
  }
  const isAll = !allCb || allCb.checked;
  const tokenIds = isAll ? undefined : checkedCbs.map(cb => parseInt(cb.value));

  const payload = {
    scope: form.scope.value.trim() || undefined,
    title: form.title.value.trim(),
    body: form.body.value.trim() || undefined,
    package: form.package.value.trim() || undefined,
    timestamp: Date.now(),
    token_ids: tokenIds,
  };
  Object.keys(payload).forEach(k => payload[k] === undefined && delete payload[k]);
  try {
    const r = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(await r.text());
    const { sent } = await r.json();
    closeSendModal();
    toast(`Sent to ${sent} client${sent !== 1 ? 's' : ''}`);
  } catch (err) {
    toast('Error: ' + err.message, 'error');
    btn.disabled = false;
  }
};

// ── Token reveal ──────────────────────────────────────────────
window.toggleToken = function(btn) {
  const span = btn.previousElementSibling;
  if (span.dataset.revealed) {
    span.textContent = '••••••••••••••••';
    delete span.dataset.revealed;
    btn.textContent = '👁';
  } else {
    span.textContent = span.dataset.token;
    span.dataset.revealed = '1';
    btn.textContent = '🙈';
  }
};

window.copyTokenValue = function(btn) {
  const span = btn.closest('td').querySelector('.masked');
  copyToClipboard(span.dataset.token, btn);
};

window.copyWsUrl = function(btn, token) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + window.location.host + '/ws?token=' + token;
  copyToClipboard(url, btn);
};

// ── Create token modal ────────────────────────────────────────
window.openCreateModal = function() {
  document.getElementById('create-modal').style.display = 'flex';
  document.getElementById('token-result').style.display = 'none';
  document.getElementById('new-token-name').value = '';
  document.getElementById('create-btn').disabled = false;
  document.getElementById('new-token-name').focus();
};
window.closeCreateModal = function() {
  document.getElementById('create-modal').style.display = 'none';
  location.reload();
};
window.copyToken = function(btn) {
  const val = document.getElementById('token-value').textContent;
  copyToClipboard(val, btn);
};

window.submitCreateToken = async function(e) {
  e.preventDefault();
  const name = document.getElementById('new-token-name').value.trim();
  if (!name) return;
  document.getElementById('create-btn').disabled = true;
  try {
    const r = await fetch('/api/tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    document.getElementById('token-value').textContent = data.token;
    document.getElementById('token-result').style.display = 'block';
    document.querySelector('#create-form button[type="submit"]').style.display = 'none';
  } catch (err) {
    toast('Error: ' + err.message, 'error');
    document.getElementById('create-btn').disabled = false;
  }
};

// ── Rename modal ──────────────────────────────────────────────
window.openRenameModal = function(id, currentName) {
  document.getElementById('rename-token-id').value = id;
  document.getElementById('rename-input').value = currentName;
  document.getElementById('rename-modal').style.display = 'flex';
  document.getElementById('rename-input').focus();
};
window.closeRenameModal = function() {
  document.getElementById('rename-modal').style.display = 'none';
};

window.submitRename = async function(e) {
  e.preventDefault();
  const id = document.getElementById('rename-token-id').value;
  const name = document.getElementById('rename-input').value.trim();
  if (!name) return;
  try {
    const r = await fetch('/api/tokens/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(await r.text());
    closeRenameModal();
    location.reload();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

// ── Revoke token ──────────────────────────────────────────────
window.revokeToken = async function(id) {
  const ok = await showConfirm('Revoke this token? Connected clients will be disconnected on next send.');
  if (!ok) return;
  try {
    const r = await fetch('/api/tokens/' + id, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

// ── Restore token ─────────────────────────────────────────────
window.restoreToken = async function(id) {
  const ok = await showConfirm('Restore this token? It will become active again.');
  if (!ok) return;
  try {
    const r = await fetch('/api/tokens/' + id + '/restore', { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

// ── Token permissions ─────────────────────────────────────────
window.togglePermission = async function(id, field, newValue, btn) {
  const td = btn.closest('td');
  const sendBtn = td.querySelector('[onclick*="can_send"]');
  const receiveBtn = td.querySelector('[onclick*="can_receive"]');
  const talkBtn = td.querySelector('[onclick*="can_talk"]');
  const hearBtn = td.querySelector('[onclick*="can_hear"]');
  let canTalk = talkBtn === btn ? newValue : talkBtn.classList.contains('perm-on');
  let canHear = hearBtn === btn ? newValue : hearBtn.classList.contains('perm-on');
  // Enforce: can_talk implies can_hear
  if (field === 'can_talk' && newValue === true) canHear = true;
  if (field === 'can_hear' && newValue === false) canTalk = false;
  const body = {
    can_send: sendBtn === btn ? newValue : sendBtn.classList.contains('perm-on'),
    can_receive: receiveBtn === btn ? newValue : receiveBtn.classList.contains('perm-on'),
    can_talk: canTalk,
    can_hear: canHear,
  };
  try {
    const r = await fetch('/api/tokens/' + id + '/permissions', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    function applyBtn(b, val) {
      b.classList.toggle('perm-on', val);
      b.classList.toggle('perm-off', !val);
      b.setAttribute('onclick', b.getAttribute('onclick').replace(/,\s*(true|false),/, ', ' + (val ? 'false' : 'true') + ','));
    }
    applyBtn(talkBtn, canTalk);
    applyBtn(hearBtn, canHear);
    if (btn !== talkBtn && btn !== hearBtn) applyBtn(btn, newValue);
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

// ── Connected clients ─────────────────────────────────────────
let clientsTimer = null;

async function refreshClients() {
  try {
    const r = await fetch('/api/clients');
    if (!r.ok) return;
    const clients = await r.json();
    const tbody = document.getElementById('clients-tbody');
    const countEl = document.getElementById('client-count');
    if (!tbody) return;
    countEl.textContent = clients.length + ' connected';
    if (clients.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No clients connected</td></tr>';
      return;
    }
    tbody.innerHTML = clients.map(c => {
      const clientLabel = [c.client, c.version].filter(Boolean).join(' ');
      return `
      <tr>
        <td>${esc(c.token_name)}</td>
        <td class="muted">${esc(clientLabel || '—')}</td>
        <td>${esc(c.ip)}</td>
        <td>${fmtDatetime(c.connected_at)}</td>
        <td class="duration" data-ts="${c.connected_at}">${fmtDuration(c.connected_at)}</td>
      </tr>`;
    }).join('');
  } catch (_) {}
}

function startClientsPolling() {
  if (clientsTimer) clearInterval(clientsTimer);
  refreshClients();
  clientsTimer = setInterval(() => {
    if (document.getElementById('tab-clients').classList.contains('active')) {
      refreshClients();
      // also update duration cells without full refresh
      document.querySelectorAll('.duration').forEach(td => {
        td.textContent = fmtDuration(td.dataset.ts);
      });
    }
  }, 5000);
}

// ── Notification log ──────────────────────────────────────────
let currentLogPage = 1;
let logTimer = null;

window.loadLogs = async function(page) {
  currentLogPage = page;
  const tokenId = document.getElementById('log-filter-token')?.value || '';
  const params = new URLSearchParams({ page, per_page: 50 });
  if (tokenId) params.set('token_id', tokenId);
  try {
    const r = await fetch('/api/logs?' + params);
    if (!r.ok) return;
    const data = await r.json();
    const tbody = document.getElementById('logs-tbody');
    const pageDiv = document.getElementById('logs-pagination');
    const infoDiv = document.getElementById('logs-info');
    if (!tbody) return;

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No notifications logged</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(l => `
        <tr class="clickable-row" onclick='openLogDetailModal(${JSON.stringify(l)})'>
          <td style="white-space:nowrap">${fmtDatetime(l.received_at)}</td>
          <td><span class="badge ${l.source === 'admin' ? 'source-admin' : 'source-device'}">${esc(l.source)}</span></td>
          <td>${esc(l.token_name || '—')}</td>
          <td>${esc(l.payload.scope || '')}</td>
          <td>${esc(trunc(l.payload.title || '', 60))}</td>
          <td style="color:var(--muted)">${esc(trunc(l.payload.body || '', 80))}</td>
        </tr>`
      ).join('');
    }

    infoDiv.textContent = data.total + ' total entries';
    pageDiv.innerHTML = '';
    if (data.pages > 1) {
      if (page > 1) {
        const prev = document.createElement('button');
        prev.textContent = '← Prev';
        prev.className = 'secondary small';
        prev.onclick = () => loadLogs(page - 1);
        pageDiv.appendChild(prev);
      }
      const info = document.createElement('span');
      info.className = 'page-info';
      info.textContent = 'Page ' + page + ' of ' + data.pages;
      pageDiv.appendChild(info);
      if (page < data.pages) {
        const next = document.createElement('button');
        next.textContent = 'Next →';
        next.className = 'secondary small';
        next.onclick = () => loadLogs(page + 1);
        pageDiv.appendChild(next);
      }
    }
  } catch (_) {}
};

// ── Log detail modal ──────────────────────────────────────────
window.openLogDetailModal = function(log) {
  const meta = document.getElementById('log-detail-meta');
  const payloadDiv = document.getElementById('log-detail-payload');
  const tbody = document.getElementById('log-detail-deliveries');

  meta.textContent = `device: ${fmtDatetime(log.received_at)}  ·  server: ${fmtDatetime(log.forwarded_at)}  ·  source: ${log.source}  ·  token: ${log.token_name || '—'}`;

  const fields = [
    ['Scope',   log.payload.scope],
    ['Title',   log.payload.title],
    ['Body',    log.payload.body],
    ['Package', log.payload.package],
  ].filter(([, v]) => v);
  payloadDiv.innerHTML = fields.map(([k, v]) =>
    `<div style="display:flex;gap:8px;margin-bottom:4px">
      <span style="min-width:60px;color:var(--muted);font-size:12px">${k}</span>
      <span style="font-size:13px">${esc(String(v))}</span>
    </div>`
  ).join('');

  if (log.deliveries && log.deliveries.length > 0) {
    tbody.innerHTML = log.deliveries.map(d => `
      <tr>
        <td>${esc(d.token_name)}</td>
        <td style="white-space:nowrap">${fmtDatetime(d.sent_at)}</td>
        <td style="white-space:nowrap">${d.acked_at
          ? `<span class="badge delivery-acked">✓ ${fmtDatetime(d.acked_at)}</span>`
          : '<span style="color:var(--muted)">—</span>'}</td>
      </tr>`
    ).join('');
  } else {
    tbody.innerHTML = '<tr><td colspan="3" class="empty">No deliveries recorded</td></tr>';
  }

  document.getElementById('log-detail-modal').style.display = 'flex';
};

window.closeLogDetailModal = function() {
  document.getElementById('log-detail-modal').style.display = 'none';
};

function startLogsPolling() {
  if (logTimer) clearInterval(logTimer);
  logTimer = setInterval(() => {
    if (document.getElementById('tab-logs').classList.contains('active')) {
      loadLogs(currentLogPage);
    }
  }, 10000);
}

// ── Server log ────────────────────────────────────────────────
let serverLogTimer = null;
let activeServerLogTab = 'server';

window.switchServerLogTab = function(tab) {
  activeServerLogTab = tab;
  document.getElementById('server-log-content').style.display = tab === 'server' ? '' : 'none';
  document.getElementById('heartbeat-log-content').style.display = tab === 'heartbeat' ? '' : 'none';
  document.getElementById('server-log-tab-server').className = 'small' + (tab === 'server' ? ' active' : ' secondary');
  document.getElementById('server-log-tab-heartbeat').className = 'small' + (tab === 'heartbeat' ? ' active' : ' secondary');
  if (tab === 'server') refreshServerLog(); else refreshHeartbeatLog();
};

async function refreshServerLog() {
  try {
    const r = await fetch('/api/server-log');
    if (!r.ok) return;
    const text = await r.text();
    const pre = document.getElementById('server-log-content');
    if (!pre) return;
    pre.textContent = text;
    pre.scrollTop = pre.scrollHeight;
  } catch (_) {}
}

async function refreshHeartbeatLog() {
  try {
    const r = await fetch('/api/heartbeat-log');
    if (!r.ok) return;
    const text = await r.text();
    const pre = document.getElementById('heartbeat-log-content');
    if (!pre) return;
    pre.textContent = text;
    pre.scrollTop = pre.scrollHeight;
  } catch (_) {}
}

function startServerLogPolling() {
  if (serverLogTimer) clearInterval(serverLogTimer);
  if (activeServerLogTab === 'server') refreshServerLog(); else refreshHeartbeatLog();
  serverLogTimer = setInterval(() => {
    if (document.getElementById('tab-server-log').classList.contains('active')) {
      if (activeServerLogTab === 'server') refreshServerLog(); else refreshHeartbeatLog();
    }
  }, 5000);
}

// ── Regenerate token ──────────────────────────────────────────
window.regenerateToken = async function(id) {
  const ok = await showConfirm('Regenerate this token? The current value will be invalidated immediately and any live connection will be disconnected.');
  if (!ok) return;
  try {
    const r = await fetch('/api/tokens/' + id + '/regenerate', { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    document.getElementById('regen-token-value').textContent = data.token;
    document.getElementById('regen-modal').style.display = 'flex';
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};
window.closeRegenModal = function() {
  document.getElementById('regen-modal').style.display = 'none';
  location.reload();
};
window.copyRegenToken = function(btn) {
  copyToClipboard(document.getElementById('regen-token-value').textContent, btn);
};

// ── Token events modal ────────────────────────────────────────
// ── Token deliveries modal ────────────────────────────────────
let _deliveriesTokenId = null;

window.openDeliveriesModal = function(id, name) {
  _deliveriesTokenId = id;
  document.getElementById('deliveries-modal-title').textContent = 'Messages — ' + name;
  document.getElementById('deliveries-modal').style.display = 'flex';
  loadDeliveries(id, 1);
};

window.closeDeliveriesModal = function() {
  document.getElementById('deliveries-modal').style.display = 'none';
  _deliveriesTokenId = null;
};

async function loadDeliveries(id, page) {
  const tbody = document.getElementById('deliveries-tbody');
  const pageDiv = document.getElementById('deliveries-pagination');
  const infoDiv = document.getElementById('deliveries-info');
  try {
    const r = await fetch(`/api/tokens/${id}/deliveries?page=${page}&per_page=10`);
    if (!r.ok) return;
    const data = await r.json();

    infoDiv.textContent = data.total + ' total messages';

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No messages delivered yet</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(d => `
        <tr>
          <td style="white-space:nowrap">${fmtDatetime(d.received_at)}</td>
          <td><span class="badge ${d.source === 'admin' ? 'source-admin' : 'source-device'}">${esc(d.source)}</span></td>
          <td>${esc(d.payload.scope || '')}</td>
          <td>${esc(trunc(d.payload.title || '', 50))}</td>
          <td style="white-space:nowrap">${fmtDatetime(d.sent_at)}</td>
          <td style="white-space:nowrap">${d.acked_at
            ? `<span class="badge delivery-acked">✓ ${fmtDatetime(d.acked_at)}</span>`
            : '<span style="color:var(--muted)">—</span>'}</td>
        </tr>`
      ).join('');
    }

    pageDiv.innerHTML = '';
    if (data.pages > 1) {
      if (page > 1) {
        const prev = document.createElement('button');
        prev.textContent = '← Prev';
        prev.className = 'secondary small';
        prev.onclick = () => loadDeliveries(id, page - 1);
        pageDiv.appendChild(prev);
      }
      const info = document.createElement('span');
      info.className = 'page-info';
      info.textContent = 'Page ' + page + ' of ' + data.pages;
      pageDiv.appendChild(info);
      if (page < data.pages) {
        const next = document.createElement('button');
        next.textContent = 'Next →';
        next.className = 'secondary small';
        next.onclick = () => loadDeliveries(id, page + 1);
        pageDiv.appendChild(next);
      }
    }
  } catch (_) {}
}

// ── Token events modal ────────────────────────────────────────
let _eventsTokenId = null;

window.openEventsModal = function(id, name) {
  _eventsTokenId = id;
  document.getElementById('events-modal-title').textContent = 'History — ' + name;
  document.getElementById('events-modal').style.display = 'flex';
  document.getElementById('events-tbody').innerHTML = '<tr><td colspan="3" class="empty">Loading…</td></tr>';
  loadEvents(id, 1);
};
window.closeEventsModal = function() {
  document.getElementById('events-modal').style.display = 'none';
  _eventsTokenId = null;
};

function fmtEventDetail(event, detail) {
  if (!detail) return '';
  if (event === 'renamed') return esc(detail.from) + ' → ' + esc(detail.to);
  if (event === 'permissions_changed') return 'Send: ' + (detail.can_send ? 'on' : 'off') + ', Receive: ' + (detail.can_receive ? 'on' : 'off') + ', Talk: ' + (detail.can_talk ? 'on' : 'off') + ', Hear: ' + (detail.can_hear ? 'on' : 'off');
  return '';
}

async function loadEvents(id, page) {
  const params = new URLSearchParams({ page, per_page: 10 });
  try {
    const r = await fetch('/api/tokens/' + id + '/events?' + params);
    if (!r.ok) return;
    const data = await r.json();
    const tbody = document.getElementById('events-tbody');
    const pageDiv = document.getElementById('events-pagination');
    const infoDiv = document.getElementById('events-info');
    if (!tbody) return;

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty">No events yet</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(e => `
        <tr>
          <td><span class="badge event-${esc(e.event)}">${esc(e.event)}</span></td>
          <td style="white-space:nowrap;color:var(--muted)">${fmtDatetime(e.occurred_at)}</td>
          <td style="color:var(--muted)">${fmtEventDetail(e.event, e.detail)}</td>
        </tr>
      `).join('');
    }

    infoDiv.textContent = data.total + ' total event' + (data.total !== 1 ? 's' : '');
    pageDiv.innerHTML = '';
    if (data.pages > 1) {
      if (page > 1) {
        const prev = document.createElement('button');
        prev.textContent = '← Prev';
        prev.className = 'secondary small';
        prev.onclick = () => loadEvents(id, page - 1);
        pageDiv.appendChild(prev);
      }
      const info = document.createElement('span');
      info.className = 'page-info';
      info.textContent = 'Page ' + page + ' of ' + data.pages;
      pageDiv.appendChild(info);
      if (page < data.pages) {
        const next = document.createElement('button');
        next.textContent = 'Next →';
        next.className = 'secondary small';
        next.onclick = () => loadEvents(id, page + 1);
        pageDiv.appendChild(next);
      }
    }
  } catch (_) {}
}

// ── Connection log modal ──────────────────────────────────────
let _connectionLogOpen = false;
let _connectionLogPage = 1;

window.openConnectionLogModal = function() {
  _connectionLogOpen = true;
  _connectionLogPage = 1;
  document.getElementById('connection-log-modal').style.display = 'flex';
  document.getElementById('connection-log-tbody').innerHTML = '<tr><td colspan="4" class="empty">Loading…</td></tr>';
  loadConnectionLog(1);
};

window.closeConnectionLogModal = function() {
  _connectionLogOpen = false;
  document.getElementById('connection-log-modal').style.display = 'none';
};

async function loadConnectionLog(page) {
  _connectionLogPage = page;
  const params = new URLSearchParams({ page, per_page: 10 });
  try {
    const r = await fetch('/api/connection-log?' + params);
    if (!r.ok) return;
    const data = await r.json();
    const tbody = document.getElementById('connection-log-tbody');
    const pageDiv = document.getElementById('connection-log-pagination');
    const infoDiv = document.getElementById('connection-log-info');
    if (!tbody) return;

    infoDiv.textContent = data.total + ' total event' + (data.total !== 1 ? 's' : '');

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">No connection events yet</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(e => `
        <tr>
          <td>${esc(e.token_name)}</td>
          <td><span class="badge event-${esc(e.event)}">${esc(e.event)}</span></td>
          <td style="white-space:nowrap;color:var(--muted)">${fmtDatetime(e.occurred_at)}</td>
          <td style="color:var(--muted)">${esc(e.detail?.ip || '—')}</td>
        </tr>
      `).join('');
    }

    pageDiv.innerHTML = '';
    if (data.pages > 1) {
      if (page > 1) {
        const prev = document.createElement('button');
        prev.textContent = '← Prev';
        prev.className = 'secondary small';
        prev.onclick = () => loadConnectionLog(page - 1);
        pageDiv.appendChild(prev);
      }
      const info = document.createElement('span');
      info.className = 'page-info';
      info.textContent = 'Page ' + page + ' of ' + data.pages;
      pageDiv.appendChild(info);
      if (page < data.pages) {
        const next = document.createElement('button');
        next.textContent = 'Next →';
        next.className = 'secondary small';
        next.onclick = () => loadConnectionLog(page + 1);
        pageDiv.appendChild(next);
      }
    }
  } catch (_) {}
}

// ── Voice channels ────────────────────────────────────────────
let channelsTimer = null;

function startChannelsPolling() {
  if (channelsTimer) clearInterval(channelsTimer);
  channelsTimer = setInterval(() => {
    if (document.getElementById('tab-channels').classList.contains('active')) {
      refreshChannels();
    }
  }, 5000);
}

async function refreshChannels() {
  const tbody = document.getElementById('channels-tbody');
  if (!tbody) return;
  try {
    const r = await fetch('/api/channels');
    if (!r.ok) throw new Error(await r.text());
    const channels = await r.json();
    if (!channels.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No channels yet — create one to get started.</td></tr>';
      return;
    }
    tbody.innerHTML = channels.map(ch => {
      const clients = ch.clients.map(c =>
        `<span title="${esc(c.token_name)}">${esc(c.token_name)}${c.transmitting ? ' 🎙' : ''}</span>`
      ).join(', ');
      return `<tr>
        <td>${ch.number}</td>
        <td>${esc(ch.name)}</td>
        <td>
          <button class="small perm-btn ${ch.is_enabled ? 'perm-on' : 'perm-off'}"
                  onclick="toggleChannelEnabled(${ch.id}, ${!ch.is_enabled}, this)">
            ${ch.is_enabled ? 'Enabled' : 'Disabled'}
          </button>
        </td>
        <td>${ch.client_count > 0 ? ch.client_count + ' — ' + clients : '<span class="muted">none</span>'}</td>
        <td class="td-flex" style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="small secondary" onclick="openRenameChannelModal(${ch.id}, '${esc(ch.name)}')">Rename</button>
          <button class="small danger" onclick="deleteChannel(${ch.id}, ${ch.client_count})">Delete</button>
        </td>
      </tr>`;
    }).join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">Failed to load channels.</td></tr>';
  }
}

window.toggleChannelEnabled = async function(id, newValue, btn) {
  try {
    const r = await fetch('/api/channels/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_enabled: newValue }),
    });
    if (!r.ok) throw new Error(await r.text());
    btn.classList.toggle('perm-on', newValue);
    btn.classList.toggle('perm-off', !newValue);
    btn.textContent = newValue ? 'Enabled' : 'Disabled';
    btn.setAttribute('onclick', `toggleChannelEnabled(${id}, ${!newValue}, this)`);
    if (!newValue) refreshChannels();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

window.deleteChannel = async function(id, clientCount) {
  if (clientCount > 0) {
    toast('Disable the channel first to eject connected clients, then delete.', 'error');
    return;
  }
  const ok = await showConfirm('Delete this channel?');
  if (!ok) return;
  try {
    const r = await fetch('/api/channels/' + id, { method: 'DELETE' });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || r.statusText);
    }
    toast('Channel deleted', 'success');
    refreshChannels();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

window.openCreateChannelModal = function() {
  document.getElementById('new-channel-number').value = '';
  document.getElementById('new-channel-name').value = '';
  document.getElementById('create-channel-modal').style.display = 'flex';
  document.getElementById('new-channel-number').focus();
};
window.closeCreateChannelModal = function() {
  document.getElementById('create-channel-modal').style.display = 'none';
};
window.submitCreateChannel = async function(e) {
  e.preventDefault();
  const number = parseInt(document.getElementById('new-channel-number').value, 10);
  const name = document.getElementById('new-channel-name').value.trim();
  const btn = document.getElementById('create-channel-btn');
  btn.disabled = true;
  try {
    const r = await fetch('/api/channels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ number, name }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || r.statusText);
    }
    closeCreateChannelModal();
    toast('Channel created', 'success');
    refreshChannels();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
  }
};

window.openRenameChannelModal = function(id, currentName) {
  document.getElementById('rename-channel-id').value = id;
  document.getElementById('rename-channel-name').value = currentName;
  document.getElementById('rename-channel-modal').style.display = 'flex';
  document.getElementById('rename-channel-name').focus();
};
window.closeRenameChannelModal = function() {
  document.getElementById('rename-channel-modal').style.display = 'none';
};
window.submitRenameChannel = async function(e) {
  e.preventDefault();
  const id = document.getElementById('rename-channel-id').value;
  const name = document.getElementById('rename-channel-name').value.trim();
  try {
    const r = await fetch('/api/channels/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(await r.text());
    closeRenameChannelModal();
    toast('Channel renamed', 'success');
    refreshChannels();
  } catch (err) {
    toast('Error: ' + err.message, 'error');
  }
};

// ── Voice activity log ────────────────────────────────────────
let currentVoiceLogPage = 1;
let voiceLogTimer = null;

function fmtBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / (1024 * 1024)).toFixed(1) + ' MB';
}

function fmtElapsed(startIso, endIso) {
  const start = new Date(startIso + (startIso.endsWith('Z') ? '' : 'Z'));
  const end = endIso ? new Date(endIso + (endIso.endsWith('Z') ? '' : 'Z')) : new Date();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return secs + 's';
  const m = Math.floor(secs / 60), s = secs % 60;
  if (m < 60) return m + 'm ' + s + 's';
  const h = Math.floor(m / 60), mm = m % 60;
  return h + 'h ' + mm + 'm';
}

window.loadVoiceLog = async function(page) {
  currentVoiceLogPage = page;
  const params = new URLSearchParams({ page, per_page: 50 });
  try {
    const r = await fetch('/api/voice-log?' + params);
    if (!r.ok) return;
    const data = await r.json();
    const tbody = document.getElementById('voice-log-tbody');
    const pageDiv = document.getElementById('voice-log-pagination');
    const infoDiv = document.getElementById('voice-log-info');
    if (!tbody) return;

    if (data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">No voice activity yet</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(l => `
        <tr>
          <td>${esc(l.token_name)}</td>
          <td>${l.channel_id != null ? '#' + esc(String(l.channel_id)) : '<span class="muted">—</span>'}</td>
          <td style="white-space:nowrap">${fmtDatetime(l.started_at)}</td>
          <td style="white-space:nowrap">${l.ended_at ? fmtDatetime(l.ended_at) : '<span class="badge perm-on">live</span>'}</td>
          <td>${fmtElapsed(l.started_at, l.ended_at)}</td>
          <td>${fmtBytes(l.bytes_relayed)}</td>
          <td>${l.listeners}</td>
        </tr>`
      ).join('');
    }

    infoDiv.textContent = data.total + ' total entries';
    pageDiv.innerHTML = '';
    if (data.pages > 1) {
      if (page > 1) {
        const prev = document.createElement('button');
        prev.textContent = '← Prev';
        prev.className = 'secondary small';
        prev.onclick = () => loadVoiceLog(page - 1);
        pageDiv.appendChild(prev);
      }
      const info = document.createElement('span');
      info.className = 'page-info';
      info.textContent = 'Page ' + page + ' of ' + data.pages;
      pageDiv.appendChild(info);
      if (page < data.pages) {
        const next = document.createElement('button');
        next.textContent = 'Next →';
        next.className = 'secondary small';
        next.onclick = () => loadVoiceLog(page + 1);
        pageDiv.appendChild(next);
      }
    }
  } catch (_) {}
};

function startVoiceLogPolling() {
  if (voiceLogTimer) clearInterval(voiceLogTimer);
  voiceLogTimer = setInterval(() => {
    if (document.getElementById('tab-voice-log').classList.contains('active')) {
      loadVoiceLog(currentVoiceLogPage);
    }
  }, 5000);
}

// ── Esc closes any open modal ─────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (document.getElementById('create-modal').style.display === 'flex') closeCreateModal();
  if (document.getElementById('rename-modal').style.display === 'flex') closeRenameModal();
  if (document.getElementById('send-modal').style.display === 'flex') closeSendModal();
  if (document.getElementById('events-modal').style.display === 'flex') closeEventsModal();
  if (document.getElementById('deliveries-modal').style.display === 'flex') closeDeliveriesModal();
  if (document.getElementById('regen-modal').style.display === 'flex') closeRegenModal();
  if (document.getElementById('log-detail-modal').style.display === 'flex') closeLogDetailModal();
  if (document.getElementById('connection-log-modal').style.display === 'flex') closeConnectionLogModal();
  if (document.getElementById('create-channel-modal').style.display === 'flex') closeCreateChannelModal();
  if (document.getElementById('rename-channel-modal').style.display === 'flex') closeRenameChannelModal();
});

// ── Init ──────────────────────────────────────────────────────
updateTzBtn();
refreshTokenTimestamps();
startClientsPolling();
startChannelsPolling();
startLogsPolling();
startVoiceLogPolling();
startServerLogPolling();
