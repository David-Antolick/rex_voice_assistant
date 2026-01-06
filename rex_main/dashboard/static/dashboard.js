// REX Dashboard JavaScript

// Global state
let ws = null;
let latencyChart = null;
let commandChart = null;
let reconnectAttempts = 0;
let hasReceivedData = false;
const maxReconnectAttempts = 3; // Fall back to polling after 3 failed attempts

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('Dashboard initializing...');

    // Try to init charts, but don't let it block the rest
    try {
        if (typeof Chart !== 'undefined') {
            initCharts();
            console.log('Charts initialized');
        } else {
            console.warn('Chart.js not loaded (may be blocked by browser)');
        }
    } catch (e) {
        console.error('Failed to initialize charts:', e);
    }

    // Always try WebSocket
    try {
        connectWebSocket();
    } catch (e) {
        console.error('Failed to start WebSocket:', e);
        // Fall back to polling immediately
        startPolling();
    }
});

// Initialize Chart.js charts
function initCharts() {
    // Latency history chart
    const latencyCtx = document.getElementById('latency-chart').getContext('2d');
    latencyChart = new Chart(latencyCtx, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'End-to-End',
                    borderColor: '#e94560',
                    backgroundColor: 'rgba(233, 69, 96, 0.1)',
                    data: [],
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Whisper',
                    borderColor: '#f5576c',
                    backgroundColor: 'rgba(245, 87, 108, 0.1)',
                    data: [],
                    tension: 0.3,
                    fill: false
                },
                {
                    label: 'VAD',
                    borderColor: '#764ba2',
                    backgroundColor: 'rgba(118, 75, 162, 0.1)',
                    data: [],
                    tension: 0.3,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'minute',
                        displayFormats: {
                            minute: 'HH:mm'
                        }
                    },
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#a0a0a0'
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#a0a0a0',
                        callback: (value) => value + 'ms'
                    }
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: '#a0a0a0'
                    }
                }
            }
        }
    });

    // Command frequency chart
    const commandCtx = document.getElementById('command-chart').getContext('2d');
    commandChart = new Chart(commandCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Commands',
                backgroundColor: 'rgba(0, 217, 255, 0.6)',
                borderColor: '#00d9ff',
                borderWidth: 1,
                data: []
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            scales: {
                x: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#a0a0a0',
                        stepSize: 1
                    }
                },
                y: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#a0a0a0'
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

// WebSocket connection
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    console.log('Attempting to connect to WebSocket:', wsUrl);
    updateConnectionStatus(false, 'Connecting...');

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected successfully');
        reconnectAttempts = 0;
        stopPolling(); // Stop polling if we were in fallback mode
        updateConnectionStatus(true, 'Connected');
    };

    ws.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        updateConnectionStatus(false, 'Disconnected');
        scheduleReconnect();
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        updateConnectionStatus(false, 'Error');
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateDashboard(data);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };
}

function scheduleReconnect() {
    if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
        console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
        setTimeout(connectWebSocket, delay);
    } else {
        // Fall back to polling if WebSocket keeps failing
        console.log('WebSocket failed after max attempts, falling back to polling');
        updateConnectionStatus(false, 'Polling mode');
        startPolling();
    }
}

// Polling fallback for browsers that block WebSockets
let pollingInterval = null;

function startPolling() {
    if (pollingInterval) return; // Already polling

    console.log('Starting polling fallback (every 3 seconds)');
    pollingInterval = setInterval(async () => {
        try {
            // Single combined request for all data
            const [statsRes, recentRes, commandsRes, benchmarkRes] = await Promise.all([
                fetch('/api/stats'),
                fetch('/api/recent'),
                fetch('/api/commands'),
                fetch('/api/benchmark')
            ]);

            const data = {
                stats: await statsRes.json(),
                recent: await recentRes.json(),
                commands: await commandsRes.json()
            };

            const benchmarkData = await benchmarkRes.json();

            updateDashboard(data);
            updateResources(benchmarkData);
            updateConnectionStatus(false, 'Polling');
        } catch (e) {
            console.error('Polling error:', e);
            updateConnectionStatus(false, 'Error');
        }
    }, 3000);  // Poll every 3 seconds instead of 2
}

// Benchmark polling is now integrated into startPolling()

function updateResources(data) {
    if (!data || data.error) return;

    // CPU
    const cpuPercent = data.cpu_percent || 0;
    document.getElementById('cpu-bar').style.width = `${cpuPercent}%`;
    document.getElementById('cpu-value').textContent = `${Math.round(cpuPercent)}%`;

    // Memory
    const memPercent = data.memory_percent || 0;
    document.getElementById('memory-bar').style.width = `${memPercent}%`;
    document.getElementById('memory-value').textContent = `${Math.round(memPercent)}%`;

    // GPU
    if (data.gpu_available) {
        const gpuPercent = data.gpu_percent || 0;
        document.getElementById('gpu-bar').style.width = `${gpuPercent}%`;
        document.getElementById('gpu-value').textContent = `${Math.round(gpuPercent)}%`;

        // VRAM
        const vramUsed = data.gpu_memory_used_mb || 0;
        const vramTotal = data.gpu_memory_total_mb || 1;
        const vramPercent = (vramUsed / vramTotal) * 100;
        document.getElementById('vram-bar').style.width = `${vramPercent}%`;
        document.getElementById('vram-value').textContent = `${Math.round(vramUsed)} MB`;

        // GPU info
        const gpuInfo = document.getElementById('gpu-info');
        if (data.gpu_name) {
            let info = data.gpu_name;
            if (data.gpu_temperature) {
                info += ` | ${Math.round(data.gpu_temperature)}°C`;
            }
            gpuInfo.textContent = info;
        }
    } else {
        document.getElementById('gpu-value').textContent = 'N/A';
        document.getElementById('vram-value').textContent = 'N/A';
        document.getElementById('gpu-info').textContent = 'No GPU detected';
    }
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function updateConnectionStatus(connected, message) {
    const indicator = document.getElementById('connection-status');
    const text = document.getElementById('connection-text');

    if (connected) {
        indicator.classList.remove('disconnected');
        indicator.classList.add('connected');
        text.textContent = message || 'Connected';
    } else {
        indicator.classList.remove('connected');
        indicator.classList.add('disconnected');
        text.textContent = message || 'Disconnected';
    }
}

// Update dashboard with new data
function updateDashboard(data) {
    hasReceivedData = true;
    updateStats(data.stats);
    updateRecentTable(data.recent);
    updateCommandChart(data.commands);
    updateLatencyBars(data.stats);

    // Update resources if included (WebSocket path)
    if (data.resources) {
        updateResources(data.resources);
    }
}

function updateStats(stats) {
    // Total commands
    const totalCommands = stats.total_matched + stats.total_unmatched;
    document.getElementById('total-commands').textContent = totalCommands;

    // Match rate
    document.getElementById('match-rate').textContent =
        stats.match_rate_percent ? `${stats.match_rate_percent}%` : '0%';

    // Average E2E latency
    const avgE2E = stats.avg_e2e_ms;
    document.getElementById('avg-latency').textContent =
        avgE2E ? `${Math.round(avgE2E)}ms` : '--';

    // Session time
    const sessionSeconds = Math.floor(stats.session_duration_s);
    const minutes = Math.floor(sessionSeconds / 60);
    const seconds = sessionSeconds % 60;
    document.getElementById('session-time').textContent =
        `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function updateLatencyBars(stats) {
    const maxLatency = 2000; // Max bar width represents 2000ms

    // VAD
    const vadMs = stats.avg_vad_ms || 0;
    const vadPercent = Math.min((vadMs / maxLatency) * 100, 100);
    document.getElementById('vad-bar').style.width = `${vadPercent}%`;
    document.getElementById('vad-value').textContent = vadMs ? `${Math.round(vadMs)}ms` : '--';

    // Whisper
    const whisperMs = stats.avg_whisper_ms || 0;
    const whisperPercent = Math.min((whisperMs / maxLatency) * 100, 100);
    document.getElementById('whisper-bar').style.width = `${whisperPercent}%`;
    document.getElementById('whisper-value').textContent = whisperMs ? `${Math.round(whisperMs)}ms` : '--';

    // Execute
    const executeMs = stats.avg_execute_ms || 0;
    const executePercent = Math.min((executeMs / maxLatency) * 100, 100);
    document.getElementById('execute-bar').style.width = `${executePercent}%`;
    document.getElementById('execute-value').textContent = executeMs ? `${Math.round(executeMs)}ms` : '--';
}

function updateRecentTable(recent) {
    const tbody = document.getElementById('recent-tbody');

    if (!recent || recent.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-message">Waiting for transcriptions...</td></tr>';
        return;
    }

    tbody.innerHTML = recent.map(item => {
        const matchClass = item.matched ? 'matched' : 'unmatched';
        const commandText = item.command || (item.matched === false ? 'No match' : '--');

        return `
            <tr>
                <td>${item.time}</td>
                <td class="${matchClass}">${escapeHtml(item.text)}</td>
                <td class="command-cell">${escapeHtml(commandText)}</td>
                <td class="latency-cell">${item.whisper_ms ? Math.round(item.whisper_ms) + 'ms' : '--'}</td>
                <td class="latency-cell">${item.execute_ms ? Math.round(item.execute_ms) + 'ms' : '--'}</td>
                <td class="latency-cell">${item.e2e_ms ? Math.round(item.e2e_ms) + 'ms' : '--'}</td>
            </tr>
        `;
    }).join('');
}

function updateCommandChart(commands) {
    if (!commandChart) return; // Chart not initialized

    if (!commands || commands.length === 0) {
        commandChart.data.labels = ['No commands yet'];
        commandChart.data.datasets[0].data = [0];
    } else {
        // Take top 8 commands
        const topCommands = commands.slice(0, 8);
        commandChart.data.labels = topCommands.map(c => formatCommandName(c.command));
        commandChart.data.datasets[0].data = topCommands.map(c => c.count);
    }
    commandChart.update('none');
}

// Utility functions
function formatCommandName(name) {
    if (!name) return 'Unknown';
    // Convert snake_case to Title Case
    return name.split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Fetch historical data for chart on page load
async function fetchHistoricalData() {
    if (!latencyChart) return; // Chart not initialized

    try {
        const response = await fetch('/api/history?minutes=60');
        const data = await response.json();

        if (data.e2e && data.e2e.length > 0) {
            latencyChart.data.datasets[0].data = data.e2e;
        }
        if (data.whisper && data.whisper.length > 0) {
            latencyChart.data.datasets[1].data = data.whisper;
        }
        if (data.vad && data.vad.length > 0) {
            latencyChart.data.datasets[2].data = data.vad;
        }
        latencyChart.update();
    } catch (e) {
        console.error('Failed to fetch historical data:', e);
    }
}

// Load historical data after charts are initialized
setTimeout(fetchHistoricalData, 1000);

// Failsafe: If we haven't received any data after 5 seconds, start polling
setTimeout(() => {
    if (!hasReceivedData && !pollingInterval) {
        console.log('Failsafe: No data received after 5s, starting polling');
        startPolling();
    }
}, 5000);
