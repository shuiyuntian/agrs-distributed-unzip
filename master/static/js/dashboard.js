/* Dashboard Frontend - Batch Architecture */

let throughputChart = null;
let statusChart = null;
let workersChart = null;
let queueChart = null;

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}小时 ${m}分`;
    return `${m}分`;
}

function initCharts() {
    const ctx1 = document.getElementById('chart-throughput').getContext('2d');
    throughputChart = new Chart(ctx1, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '吞吐量 (MB/s)',
                data: [],
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: { beginAtZero: true }
            }
        }
    });

    const ctx2 = document.getElementById('chart-status').getContext('2d');
    statusChart = new Chart(ctx2, {
        type: 'doughnut',
        data: {
            labels: ['等待中', '运行中', '成功', '失败', '部分成功'],
            datasets: [{
                data: [0, 0, 0, 0, 0],
                backgroundColor: ['#f59e0b', '#2563eb', '#10b981', '#ef4444', '#f97316']
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } }
            }
        }
    });

    const ctx3 = document.getElementById('chart-workers').getContext('2d');
    workersChart = new Chart(ctx3, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: '已完成任务',
                data: [],
                backgroundColor: '#3b82f6',
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { font: { size: 10 } } },
                y: { beginAtZero: true }
            }
        }
    });

    const ctx4 = document.getElementById('chart-queue').getContext('2d');
    queueChart = new Chart(ctx4, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: '等待中',
                    data: [],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 2
                },
                {
                    label: '运行中',
                    data: [],
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } },
            scales: {
                x: { display: false },
                y: { beginAtZero: true }
            }
        }
    });
}

async function updateDashboard() {
    try {
        const dash = await apiGet('/api/stats/dashboard');

        document.getElementById('dash-total').textContent = dash.batches.total;
        document.getElementById('dash-running').textContent = dash.batches.running;
        document.getElementById('dash-success').textContent = dash.batches.success;
        document.getElementById('dash-failed').textContent = (dash.batches.failed || 0) + (dash.batches.partial || 0);
        document.getElementById('dash-pending').textContent = dash.batches.pending + dash.batches.partial;

        document.getElementById('dash-active-workers').textContent = dash.workers.active;
        document.getElementById('dash-total-workers').textContent = dash.workers.total;
        document.getElementById('dash-busy-workers').textContent = dash.workers.busy;
        document.getElementById('dash-throughput').textContent = dash.performance.throughput_mbps.toFixed(1);
        document.getElementById('dash-avg-speed').textContent = dash.performance.avg_speed_mbps.toFixed(1);
        document.getElementById('dash-eta').textContent = formatDuration(dash.performance.estimated_seconds_remaining);
        document.getElementById('dash-remaining').textContent = dash.batches.pending + dash.batches.partial;

        statusChart.data.datasets[0].data = [
            dash.batches.pending,
            dash.batches.running,
            dash.batches.success,
            dash.batches.failed,
            dash.batches.partial
        ];
        statusChart.update('none');

        const workers = await apiGet('/api/workers/list');
        const tbody = document.getElementById('worker-table-body');
        if (workers.workers.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--gray)">暂无工作节点</td></tr>';
        } else {
            tbody.innerHTML = workers.workers.map(w => {
                const statusClass = w.status === 'active' ? 'status-success' : 'status-failed';
                const statusLabel = w.status === 'active' ? '在线' : '离线';
                return `
                    <tr>
                        <td title="${w.id}">${w.id.substring(0, 8)}...</td>
                        <td>${w.hostname}</td>
                        <td>${w.ip_address}</td>
                        <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
                        <td>${w.active_task_id || '-'}</td>
                        <td>${w.total_tasks}</td>
                        <td>${new Date(w.last_heartbeat.replace(' ', 'T') + 'Z').toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai'})}</td>
                    </tr>
                `;
            }).join('');
        }

        workersChart.data.labels = workers.workers.map(w => w.hostname.substring(0, 12));
        workersChart.data.datasets[0].data = workers.workers.map(w => w.total_tasks);
        workersChart.update('none');

    } catch (e) {
        console.error('Dashboard update failed:', e);
    }
}

async function updateHistoryCharts() {
    try {
        const history = await apiGet('/api/stats/history?minutes=30');
        if (!history.history || history.history.length === 0) return;

        const labels = history.history.map(h => {
            const d = new Date(h.timestamp.replace(' ', 'T') + 'Z');
            return d.toLocaleTimeString('zh-CN', {timeZone: 'Asia/Shanghai', hour: '2-digit', minute:'2-digit', hour12: false});
        });

        throughputChart.data.labels = labels;
        throughputChart.data.datasets[0].data = history.history.map(h => h.throughput_mbps || 0);
        throughputChart.update('none');

        queueChart.data.labels = labels;
        queueChart.data.datasets[0].data = history.history.map(h => h.pending_tasks || 0);
        queueChart.data.datasets[1].data = history.history.map(h => h.running_tasks || 0);
        queueChart.update('none');

    } catch (e) {
        console.error('History charts update failed:', e);
    }
}

initCharts();
updateDashboard();
updateHistoryCharts();

setInterval(updateDashboard, 2000);
setInterval(updateHistoryCharts, 10000);
