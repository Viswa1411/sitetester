// Performance Audit JavaScript
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const form = document.getElementById('upload-form');
const stopButton = document.getElementById('stop-button');
let sessionId = null;
let pollInterval = null;
let currentResults = null;

// Initialize drop zone
dropZone.onclick = () => fileInput.click();

dropZone.ondragover = (e) => {
    e.preventDefault();
    dropZone.classList.add('border-green-500', 'bg-green-500/10');
};

dropZone.ondragleave = () => {
    dropZone.classList.remove('border-green-500', 'bg-green-500/10');
};

dropZone.ondrop = (e) => {
    e.preventDefault();
    dropZone.classList.remove('border-green-500', 'bg-green-500/10');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        fileInput.files = files;
        updateDropZone(files[0]);
    }
};

fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (file) {
        updateDropZone(file);
    }
};

function updateDropZone(file) {
    dropZone.innerHTML = `
        <div class="w-16 h-16 mx-auto mb-4 bg-green-500/10 rounded-full flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-400"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
        </div>
        <p class="text-xl text-green-400 font-medium">${file.name}</p>
        <p class="text-sm text-gray-500 mt-1">Ready to analyze</p>
    `;
    dropZone.classList.add('border-green-500/50');
}

// Form submission
form.onsubmit = async (e) => {
    e.preventDefault();

    const manualUrls = document.getElementById('manual-urls').value;

    if (!fileInput.files[0] && !manualUrls.trim()) {
        Swal.fire({
            icon: 'info',
            title: 'Input Required',
            text: 'Please upload a file or enter URLs manually.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
        return;
    }

    const sessionName = document.querySelector('input[name="session_name"]').value;
    const strategyElement = document.querySelector('input[name="strategy"]:checked');
    const strategy = strategyElement ? strategyElement.value : 'desktop';

    if (!sessionName.trim()) {
        Swal.fire({
            icon: 'info',
            title: 'Session Name Required',
            text: 'Please enter a name for this audit session.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
        return;
    }

    // Show progress section
    document.getElementById('upload-section').classList.add('hidden');
    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('status-text').textContent = "Initializing performance analysis...";
    stopButton.classList.remove('hidden');

    const formData = new FormData();
    if (fileInput.files[0]) {
        formData.append("file", fileInput.files[0]);
    }
    if (manualUrls.trim()) {
        formData.append("manual_urls", manualUrls.trim());
    }
    formData.append("session_name", sessionName);
    formData.append("strategy", strategy);

    try {
        const res = await fetch("/upload/performance", {
            method: "POST",
            body: formData
        });

        if (!res.ok) {
            if (res.status === 401) {
                window.location.href = "/login";
                return;
            }
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || errData.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        sessionId = data.session;

        document.getElementById('status-text').textContent = `Analyzing performance (${strategy})...`;

        // Start polling for progress
        pollInterval = setInterval(async () => {
            try {
                const progRes = await fetch(`/progress/performance/${sessionId}`);
                const prog = await progRes.json();
                const completed = prog.completed || 0;
                const total = prog.total || 1;
                const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
                const status = prog.status || "running";

                document.getElementById('progress-bar').style.width = `${percent}%`;
                document.getElementById('progress-bar').textContent = `${percent}%`;
                document.getElementById('status-text').textContent = `Analyzed ${completed} of ${total} pages...`;

                // Handle different statuses
                if (status === "stopped") {
                    clearInterval(pollInterval);
                    document.getElementById('status-text').textContent = "Session stopped by user.";
                    document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
                    stopButton.classList.add('hidden');

                    setTimeout(() => {
                        window.location.href = "/platform/history?type=performance";
                    }, 2000);
                    return;
                }

                if (status === "error") {
                    clearInterval(pollInterval);
                    document.getElementById('status-text').textContent = "Session encountered an error.";
                    document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
                    stopButton.classList.add('hidden');
                    return;
                }

                if (completed >= total && total > 0 && status === "completed") {
                    clearInterval(pollInterval);
                    setTimeout(() => {
                        document.getElementById('progress-section').classList.add('hidden');
                        document.getElementById('results-section').classList.remove('hidden');
                        loadResults();
                    }, 1000);
                }
            } catch (err) {
                console.error("Progress polling error:", err);
            }
        }, 2000);

    } catch (err) {
        Swal.fire({
            icon: 'error',
            title: 'Audit Failed',
            text: err.message || 'An error occurred during upload.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
        document.getElementById('upload-section').classList.remove('hidden');
        document.getElementById('progress-section').classList.add('hidden');
        if (pollInterval) clearInterval(pollInterval);
    }
};

// Load results
async function loadResults() {
    try {
        const res = await fetch(`/api/results/${sessionId}`);

        if (!res.ok) {
            throw new Error("Failed to load results");
        }

        const results = await res.json();
        // The API returns an array directly for performance type
        displayResults(results);
    } catch (err) {
        console.error("Error loading results:", err);
        document.getElementById('content-area').innerHTML = `
            <div class="text-center py-12">
                <p class="text-2xl text-red-400">Error loading results: ${err.message}</p>
            </div>
        `;
    }
}

// Display results
function displayResults(results) {
    currentResults = results; // Store for export
    const contentArea = document.getElementById('content-area');

    if (!Array.isArray(results) || results.length === 0) {
        contentArea.innerHTML = `
            <div class="text-center py-12">
                <p class="text-2xl text-gray-400">No results found for this session.</p>
            </div>
        `;
        return;
    }

    // Calculate Summary Stats
    const totalPages = results.length;
    const avgScore = Math.round(results.reduce((sum, r) => sum + (r.score || 0), 0) / totalPages) || 0;
    const avgLoadTime = (results.reduce((sum, r) => sum + (r.page_load || 0), 0) / totalPages / 1000).toFixed(2);

    // Count Good/Fair/Poor
    const good = results.filter(r => r.score >= 90).length;
    const needsImprovement = results.filter(r => r.score >= 50 && r.score < 90).length;
    const poor = results.filter(r => r.score < 50).length;

    contentArea.innerHTML = `
        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Total Pages</p>
                <p class="text-3xl font-bold text-white">${totalPages}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Average Score</p>
                <p class="text-3xl font-bold ${getScoreColor(avgScore)}">${avgScore}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Avg Load Time</p>
                <p class="text-3xl font-bold text-blue-400">${avgLoadTime}s</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Health</p>
                <div class="flex gap-2 mt-2">
                    <span class="text-green-400 text-sm font-bold">${good} Good</span>
                    <span class="text-yellow-400 text-sm font-bold">${needsImprovement} Fair</span>
                    <span class="text-red-400 text-sm font-bold">${poor} Poor</span>
                </div>
            </div>
        </div>
        
        <!-- Detailed Results -->
        <div class="bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-gray-700/50">
            <h3 class="text-2xl font-bold text-white mb-6">Detailed Performance Metrics</h3>
            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="text-left border-b border-gray-700">
                            <th class="pb-3 px-4">URL</th>
                            <th class="pb-3 px-4">Score</th>
                            <th class="pb-3 px-4">TTFB</th>
                            <th class="pb-3 px-4">FCP</th>
                            <th class="pb-3 px-4">Load Time</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${results.map(result => {
        const score = result.score || 0;
        const ttfb = result.ttfb || 0;
        const fcp = result.fcp || 0;
        const loadTime = (result.page_load / 1000).toFixed(2);

        return `
                                <tr class="border-b border-gray-800/50 hover:bg-gray-800/30">
                                    <td class="py-4 px-4">
                                        <div class="font-medium truncate max-w-xs text-indigo-300">${result.url}</div>
                                        <div class="text-xs text-gray-500">${result.device_preset || 'Desktop'}</div>
                                    </td>
                                    <td class="py-4 px-4">
                                        <div class="flex items-center gap-2">
                                            <div class="w-16 bg-gray-700 rounded-full h-2 overflow-hidden">
                                                <div class="h-full ${getScoreBgColor(score)}" style="width: ${score}%"></div>
                                            </div>
                                            <span class="font-bold ${getScoreColor(score)}">${score}</span>
                                        </div>
                                    </td>
                                    <td class="py-4 px-4 text-gray-300">${ttfb}ms</td>
                                    <td class="py-4 px-4 text-gray-300">${fcp}ms</td>
                                    <td class="py-4 px-4 font-mono text-blue-300 font-bold">${loadTime}s</td>
                                </tr>
                            `;
    }).join('')}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Export Button -->
        <div class="mt-8 text-center">
            <button onclick="exportResults()" class="px-6 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded-xl font-bold text-lg shadow-lg shadow-blue-500/20">
                Export Results as CSV
            </button>
        </div>
    `;
}

function getScoreColor(score) {
    if (score >= 90) return 'text-green-400';
    if (score >= 50) return 'text-yellow-400';
    return 'text-red-400';
}

function getScoreBgColor(score) {
    if (score >= 90) return 'bg-green-500';
    if (score >= 50) return 'bg-yellow-500';
    return 'bg-red-500';
}


// Stop session
async function stopSession() {
    if (!sessionId || !confirm("Are you sure you want to stop this session?")) {
        return;
    }

    try {
        stopButton.disabled = true;
        stopButton.textContent = "Stopping...";

        const response = await fetch(`/api/sessions/${sessionId}/stop`, {
            method: 'POST'
        });

        if (response.ok) {
            document.getElementById('status-text').textContent = "Stopping session...";
            if (pollInterval) clearInterval(pollInterval);
        } else {
            stopButton.disabled = false;
            stopButton.textContent = "Stop Session";
        }
    } catch (error) {
        stopButton.disabled = false;
        stopButton.textContent = "Stop Session";
    }
}

// Export results as CSV
function exportResults() {
    if (!currentResults || currentResults.length === 0) {
        Swal.fire({
            icon: 'warning',
            title: 'No Data',
            text: 'There are no results to export.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
        return;
    }

    try {
        // Define headers
        const headers = ['URL', 'Score', 'TTFB (ms)', 'FCP (ms)', 'Load Time (s)', 'Device Preset'];

        // Convert results to CSV rows
        const csvRows = currentResults.map(result => {
            const loadTime = (result.page_load / 1000).toFixed(2);
            // Return CSV formatted row
            return [
                `"${result.url.replace(/"/g, '""')}"`,
                result.score || 0,
                result.ttfb || 0,
                result.fcp || 0,
                loadTime,
                `"${(result.device_preset || 'Desktop').replace(/"/g, '""')}"`
            ].join(',');
        });

        // Combine headers and rows
        const csvContent = [headers.join(',')].concat(csvRows).join('\n');

        // Create blob and download link
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', `performance_audit_results_${sessionId || 'export'}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        Swal.fire({
            icon: 'success',
            title: 'Export Successful',
            text: 'Your CSV file has been downloaded.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6',
            timer: 2000,
            showConfirmButton: false
        });

    } catch (error) {
        console.error('Export error:', error);
        Swal.fire({
            icon: 'error',
            title: 'Export Failed',
            text: 'An error occurred while generating the CSV file.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
    }
}

// Check for results or restart on page load
window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const sessionIdParam = urlParams.get('session_id') || urlParams.get('session');
    const statusParam = urlParams.get('status');
    const restartParam = urlParams.get('restart');

    if (statusParam === 'completed' && sessionIdParam) {
        sessionId = sessionIdParam;
        // Hide upload, show results
        document.getElementById('upload-section').classList.add('hidden');
        document.getElementById('results-section').classList.remove('hidden');
        loadResults();
    } else if (restartParam) {
        // Handle restart - load config from session storage
        const configStr = sessionStorage.getItem('restartConfig');
        if (configStr) {
            try {
                const config = JSON.parse(configStr);

                // Only use config if it matches the requested restart session
                if (config.session_id === restartParam) {

                    // 1. Pre-fill URLs
                    if (config.urls && Array.isArray(config.urls) && config.urls.length > 0) {
                        const urlsText = config.urls.join('\n');
                        document.getElementById('manual-urls').value = urlsText;
                    }

                    // 2. Pre-fill Project Name
                    if (config.name) {
                        const nameInput = document.querySelector('input[name="session_name"]');
                        if (nameInput) nameInput.value = config.name;
                    }

                    // 3. Auto-start the audit
                    // check if we have enough data to start
                    if (document.getElementById('manual-urls').value && document.querySelector('input[name="session_name"]').value) {
                        // Use a short timeout to ensure UI is ready
                        setTimeout(() => {
                            const submitBtn = document.querySelector('button[type="submit"]');
                            if (submitBtn) submitBtn.click();
                        }, 500);
                    }

                    // Clear storage to prevent re-triggering on reload
                    sessionStorage.removeItem('restartConfig');
                }
            } catch (e) {
                console.error("Error parsing restart config:", e);
            }
        }
    }
});
