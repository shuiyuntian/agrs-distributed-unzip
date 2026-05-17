/* Task Management Frontend - Batch + Subtask Architecture */

const API_BASE = '';
let expandedBatchIds = new Set();

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function apiPost(url, data) {
    const resp = await fetch(API_BASE + url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

async function apiGet(url) {
    const resp = await fetch(API_BASE + url);
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

async function apiDelete(url) {
    const resp = await fetch(API_BASE + url, { method: 'DELETE' });
    if (!resp.ok) throw new Error(await resp.text());
    return resp.json();
}

async function submitTasks() {
    const textarea = document.getElementById('input-paths');
    const outputRoot = document.getElementById('output-root').value.trim();
    const lines = textarea.value.split('\n').map(l => l.trim()).filter(l => l);

    if (lines.length === 0) {
        showToast('Please enter at least one folder path', 'error');
        return;
    }

    try {
        const result = await apiPost('/api/tasks/submit', {
            input_paths: lines,
            output_root: outputRoot || null
        });
        showToast(`Submitted ${result.length} batch(es)`, 'success');
        textarea.value = '';
        loadBatches();
    } catch (e) {
        showToast('Submit failed: ' + e.message, 'error');
    }
}

function formatTime(dt) {
    if (!dt) return '-';
    const d = new Date(dt);
    return d.toLocaleString();
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function getStatusBadge(status) {
    const map = {
        'pending': ['Pending', 'status-pending'],
        'running': ['Running', 'status-running'],
        'success': ['Success', 'status-success'],
        'failed': ['Failed', 'status-failed'],
        'partial': ['Partial', 'status-retrying'],
        'retrying': ['Retrying', 'status-retrying']
    };
    const [label, cls] = map[status] || [status, ''];
    return `<span class="status-badge ${cls}">${label}</span>`;
}

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '-';
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i];
}

function formatSpeed(mbps) {
    if (!mbps || mbps === 0) return '-';
    return mbps.toFixed(1) + ' MB/s';
}

function renderBatchProgress(batch) {
    const total = batch.total_subtasks || 0;
    const completed = batch.completed_subtasks || 0;
    const failed = batch.failed_subtasks || 0;
    if (total === 0) return '<div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>';

    const pct = Math.min(100, ((completed + failed) / total * 100)).toFixed(1);
    let color = 'var(--primary)';
    if (batch.status === 'success') color = 'var(--success)';
    else if (batch.status === 'failed' || batch.status === 'partial') color = 'var(--danger)';

    return `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${color}"></div></div>
            <div style="font-size:0.75rem;color:var(--gray);margin-top:2px">${completed} done / ${failed} fail / ${total} total (${pct}%)</div>`;
}

function renderTaskProgress(task) {
    if (task.status === 'success') {
        return '<div class="progress-bar"><div class="progress-fill" style="width:100%;background:var(--success)"></div></div>';
    }
    if (task.status === 'failed') {
        return '<div class="progress-bar"><div class="progress-fill" style="width:100%;background:var(--danger)"></div></div>';
    }
    if (task.total_bytes > 0 && task.processed_bytes > 0) {
        const pct = Math.min(100, (task.processed_bytes / task.total_bytes * 100)).toFixed(1);
        return `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                <div style="font-size:0.75rem;color:var(--gray)">${pct}% | ${formatSpeed(task.speed_mbps)}</div>`;
    }
    return '<div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>';
}

async function loadBatches() {
    const statusFilter = document.getElementById('status-filter').value;
    const container = document.getElementById('batch-list');

    try {
        const url = `/api/tasks/batches?limit=100` + (statusFilter ? `&status=${statusFilter}` : '');
        const data = await apiGet(url);

        if (data.batches.length === 0) {
            container.innerHTML = '<div style="text-align:center;color:var(--gray);padding:2rem">No batches</div>';
        } else {
            container.innerHTML = data.batches.map(b => renderBatchCard(b)).join('');
        }

        updateKPI(data.counts);
        const now = new Date();
        document.getElementById('last-update').textContent =
            `Updated ${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
    } catch (e) {
        container.innerHTML = `<div style="text-align:center;color:var(--danger);padding:2rem">Load failed: ${e.message}</div>`;
    }
}

function renderBatchCard(batch) {
    const isExpanded = expandedBatchIds.has(batch.id);
    const folderName = batch.input_path.split(/[\\/]/).pop() || batch.input_path;
    const created = formatTime(batch.created_at);
    const completed = formatTime(batch.completed_at);
    let duration = '-';
    if (batch.started_at && batch.completed_at) {
        const start = new Date(batch.started_at).getTime();
        const end = new Date(batch.completed_at).getTime();
        duration = formatDuration((end - start) / 1000);
    }

    return `
        <div class="batch-card" style="border:1px solid var(--border);border-radius:0.5rem;margin-bottom:0.75rem;overflow:hidden">
            <div style="padding:1rem;display:flex;align-items:center;gap:1rem;cursor:pointer;background:#f9fafb"
                 onclick="toggleBatch(${batch.id})">
                <span style="font-size:1.2rem">${isExpanded ? '▼' : '▶'}</span>
                <div style="flex:1;min-width:0">
                    <div style="font-weight:600;margin-bottom:0.25rem">Batch #${batch.id} — ${folderName}</div>
                    <div style="font-size:0.8rem;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${batch.input_path}</div>
                    <div style="font-size:0.75rem;color:var(--gray);margin-top:0.25rem">
                        Submitted: ${created}${batch.completed_at ? ` | Completed: ${completed} | Duration: ${duration}` : ''}
                    </div>
                </div>
                <div style="text-align:center;min-width:80px">
                    ${getStatusBadge(batch.status)}
                </div>
                <div style="min-width:200px">${renderBatchProgress(batch)}</div>
                <div style="display:flex;gap:0.5rem">
                    ${batch.status === 'failed' || batch.status === 'partial' ? `<button class="btn btn-sm btn-warning" onclick="event.stopPropagation();retryBatch(${batch.id})">Retry</button>` : ''}
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteBatch(${batch.id})">Delete</button>
                </div>
            </div>
            ${isExpanded ? `<div id="batch-tasks-${batch.id}" style="padding:1rem;border-top:1px solid var(--border)">Loading subtasks...</div>` : ''}
        </div>
    `;
}

async function toggleBatch(batchId) {
    if (expandedBatchIds.has(batchId)) {
        expandedBatchIds.delete(batchId);
        loadBatches();
    } else {
        expandedBatchIds.add(batchId);
        loadBatches();
        // Load subtasks after render
        setTimeout(() => loadBatchTasks(batchId), 50);
    }
}

async function loadBatchTasks(batchId) {
    const container = document.getElementById(`batch-tasks-${batchId}`);
    if (!container) return;

    try {
        const data = await apiGet(`/api/tasks/batches/${batchId}/tasks`);
        if (data.tasks.length === 0) {
            container.innerHTML = '<div style="text-align:center;color:var(--gray)">No subtasks</div>';
            return;
        }

        container.innerHTML = `
            <table style="font-size:0.8rem">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Archive</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Progress</th>
                        <th>Submitted</th>
                        <th>Started</th>
                        <th>Completed</th>
                        <th>Duration</th>
                        <th>Worker</th>
                        <th>Retry</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.tasks.map(t => {
                        let duration = '-';
                        if (t.started_at && t.completed_at) {
                            const start = new Date(t.started_at).getTime();
                            const end = new Date(t.completed_at).getTime();
                            duration = formatDuration((end - start) / 1000);
                        }
                        return `
                        <tr>
                            <td>${t.id}</td>
                            <td title="${t.input_path}">${t.input_path.split(/[\\/]/).pop()}</td>
                            <td>${t.archive_type || '-'}</td>
                            <td>${getStatusBadge(t.status)}</td>
                            <td style="min-width:120px">${renderTaskProgress(t)}</td>
                            <td>${formatTime(t.created_at)}</td>
                            <td>${formatTime(t.started_at)}</td>
                            <td>${formatTime(t.completed_at)}</td>
                            <td>${duration}</td>
                            <td title="${t.worker_id || ''}">${t.worker_id ? t.worker_id.substring(0, 8) + '...' : '-'}</td>
                            <td>${t.retry_count}</td>
                            <td>
                                ${t.status === 'running' ? `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation();cancelTask(${t.id})">Cancel</button>` : ''}
                            </td>
                        </tr>
                    `;}).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        container.innerHTML = `<div style="color:var(--danger)">Load failed: ${e.message}</div>`;
    }
}

function updateKPI(counts) {
    document.getElementById('kpi-total').textContent = counts.total || 0;
    document.getElementById('kpi-pending').textContent = counts.pending || 0;
    document.getElementById('kpi-running').textContent = counts.running || 0;
    document.getElementById('kpi-success').textContent = counts.success || 0;
    document.getElementById('kpi-failed').textContent = (counts.failed || 0) + (counts.partial || 0);
}

async function retryBatch(batchId) {
    try {
        await apiPost(`/api/tasks/batches/${batchId}/retry`, {});
        showToast('Batch retry triggered', 'success');
        loadBatches();
    } catch (e) {
        showToast('Retry failed: ' + e.message, 'error');
    }
}

async function deleteBatch(batchId) {
    if (!confirm(`Delete batch #${batchId} and all its subtasks?`)) return;
    try {
        await apiDelete(`/api/tasks/batches/${batchId}`);
        showToast('Batch deleted', 'success');
        expandedBatchIds.delete(batchId);
        loadBatches();
    } catch (e) {
        showToast('Delete failed: ' + e.message, 'error');
    }
}

async function retryFailedBatches() {
    if (!confirm('Retry all failed subtasks across all batches?')) return;
    try {
        await apiPost('/api/tasks/retry-failed', {});
        showToast('All failed tasks queued for retry', 'success');
        loadBatches();
    } catch (e) {
        showToast('Retry failed: ' + e.message, 'error');
    }
}

async function clearCompleted() {
    if (!confirm('Clear all completed (success/failed) batches and subtasks?')) return;
    try {
        await apiPost('/api/tasks/clear-completed', {});
        showToast('Completed records cleared', 'success');
        loadBatches();
    } catch (e) {
        showToast('Clear failed: ' + e.message, 'error');
    }
}

async function cancelTask(taskId) {
    if (!confirm(`Cancel subtask #${taskId}?`)) return;
    try {
        await apiPost(`/api/tasks/${taskId}/cancel`, {});
        showToast('Task cancelled', 'success');
        loadBatches();
    } catch (e) {
        showToast('Cancel failed: ' + e.message, 'error');
    }
}

async function loadWorkers() {
    const container = document.getElementById('worker-list');
    try {
        const data = await apiGet('/api/workers/list');
        if (data.workers.length === 0) {
            container.innerHTML = '<div style="text-align:center;color:var(--gray);padding:1rem">No workers</div>';
            return;
        }
        container.innerHTML = `
            <table style="font-size:0.85rem">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Hostname</th>
                        <th>IP</th>
                        <th>Status</th>
                        <th>Active Task</th>
                        <th>Completed</th>
                        <th>Last Heartbeat</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.workers.map(w => renderWorkerRow(w)).join('')}
                </tbody>
            </table>
        `;
    } catch (e) {
        container.innerHTML = `<div style="text-align:center;color:var(--danger);padding:1rem">Load failed: ${e.message}</div>`;
    }
}

function renderWorkerRow(w) {
    const statusClass = w.status === 'active' ? 'status-success'
                      : w.status === 'paused' ? 'status-warning'
                      : w.status === 'restarting' ? 'status-running'
                      : 'status-failed';
    const statusLabel = w.status === 'active' ? 'Active'
                      : w.status === 'paused' ? 'Paused'
                      : w.status === 'restarting' ? 'Restarting'
                      : 'Offline';
    const hb = w.last_heartbeat ? new Date(w.last_heartbeat).toLocaleString() : '-';

    let actions = '';
    if (w.status === 'active' || w.status === 'offline') {
        actions += `<button class="btn btn-sm btn-warning" onclick="pauseWorker('${w.id}')">Pause</button>`;
    }
    if (w.status === 'paused') {
        actions += `<button class="btn btn-sm btn-success" onclick="resumeWorker('${w.id}')">Resume</button>`;
    }
    if (w.status !== 'restarting') {
        actions += `<button class="btn btn-sm btn-danger" onclick="restartWorker('${w.id}')">Restart</button>`;
    }

    return `
        <tr>
            <td title="${w.id}">${w.id.substring(0, 8)}...</td>
            <td>${w.hostname}</td>
            <td>${w.ip_address}</td>
            <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
            <td>${w.active_task_id || '-'}</td>
            <td>${w.total_tasks}</td>
            <td>${hb}</td>
            <td style="white-space:nowrap">${actions}</td>
        </tr>
    `;
}

async function pauseWorker(workerId) {
    try {
        await apiPost(`/api/workers/${workerId}/pause`, {});
        showToast('Worker paused', 'success');
        loadWorkers();
    } catch (e) {
        showToast('Pause failed: ' + e.message, 'error');
    }
}

async function resumeWorker(workerId) {
    try {
        await apiPost(`/api/workers/${workerId}/resume`, {});
        showToast('Worker resumed', 'success');
        loadWorkers();
    } catch (e) {
        showToast('Resume failed: ' + e.message, 'error');
    }
}

async function restartWorker(workerId) {
    if (!confirm(`Restart worker ${workerId.substring(0, 8)}...?`)) return;
    try {
        await apiPost(`/api/workers/${workerId}/restart`, {});
        showToast('Worker restart command sent', 'success');
        loadWorkers();
    } catch (e) {
        showToast('Restart failed: ' + e.message, 'error');
    }
}

// Auto refresh
setInterval(() => {
    loadBatches();
    loadWorkers();
    expandedBatchIds.forEach(id => loadBatchTasks(id));
}, 2000);

// Init
loadBatches();
loadWorkers();
