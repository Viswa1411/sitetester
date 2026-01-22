// Accessibility Audit JavaScript
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
    dropZone.classList.add('border-amber-500', 'bg-amber-500/10');
};

dropZone.ondragleave = () => {
    dropZone.classList.remove('border-amber-500', 'bg-amber-500/10');
};

dropZone.ondrop = (e) => {
    e.preventDefault();
    dropZone.classList.remove('border-amber-500', 'bg-amber-500/10');
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
        <div class="w-16 h-16 mx-auto mb-4 bg-amber-500/10 rounded-full flex items-center justify-center">
             <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-amber-400"><polyline points="20 6 9 17 4 12"></polyline></svg>
        </div>
        <p class="text-xl text-amber-400 font-medium">${file.name}</p>
        <p class="text-sm text-gray-500 mt-1">Ready to scan</p>
    `;
    dropZone.classList.add('border-amber-500/50');
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
    document.getElementById('status-text').textContent = "Initializing accessibility audit...";
    stopButton.classList.remove('hidden');

    const formData = new FormData();
    if (fileInput.files[0]) {
        formData.append("file", fileInput.files[0]);
    }
    if (manualUrls.trim()) {
        formData.append("urls", manualUrls.trim());
    }
    formData.append("session_name", sessionName);

    try {
        // The endpoint is /api/accessibility-test logic. 
        // Need to update backend logic?
        // Let's implement /upload/accessibility route first, similar to others.
        const res = await fetch("/upload/accessibility", {
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

        document.getElementById('status-text').textContent = "Analyzing accessibility...";

        // Start polling for progress
        pollInterval = setInterval(async () => {
            try {
                // We need a progress endpoint for accessibility too.
                const progRes = await fetch(`/progress/accessibility/${sessionId}`);
                const prog = await progRes.json();
                const completed = prog.completed || 0;
                const total = prog.total || 1;
                const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
                const status = prog.status || "running";

                document.getElementById('progress-bar').style.width = `${percent}%`;
                document.getElementById('progress-bar').textContent = `${percent}%`;
                document.getElementById('status-text').textContent = `Audited ${completed} of ${total} pages...`;

                if (status === "stopped") {
                    clearInterval(pollInterval);
                    document.getElementById('status-text').textContent = "Session stopped by user.";
                    document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
                    stopButton.classList.add('hidden');
                    setTimeout(() => {
                        window.location.href = "/platform/history?type=accessibility";
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

    // Calculate Stats
    const totalPages = results.length;
    let totalCritical = 0;
    let totalSerious = 0;
    let totalModerate = 0;

    results.forEach(r => {
        if (r.violations) {
            r.violations.forEach(v => {
                if (v.impact === 'critical') totalCritical++;
                else if (v.impact === 'serious') totalSerious++;
                else if (v.impact === 'moderate') totalModerate++;
            });
        }
    });

    contentArea.innerHTML = `
        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Total Pages</p>
                <p class="text-3xl font-bold text-white">${totalPages}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Critical Issues</p>
                <p class="text-3xl font-bold text-red-400">${totalCritical}</p>
            </div>
             <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Serious Issues</p>
                <p class="text-3xl font-bold text-amber-400">${totalSerious}</p>
            </div>
             <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Moderate Issues</p>
                <p class="text-3xl font-bold text-blue-400">${totalModerate}</p>
            </div>
        </div>
        
        <!-- Detailed Results -->
        <div class="space-y-6">
            ${results.map(r => `
                <div class="bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-gray-700/50">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6">
                         <div class="font-medium truncate max-w-lg text-amber-300 text-lg">${r.url}</div>
                         <div class="flex gap-2 mt-2 md:mt-0">
                            <span class="px-2 py-1 bg-red-500/10 text-red-400 text-xs rounded border border-red-500/20">${r.violations ? r.violations.filter(v => v.impact === 'critical').length : 0} Critical</span>
                            <span class="px-2 py-1 bg-amber-500/10 text-amber-400 text-xs rounded border border-amber-500/20">${r.violations ? r.violations.filter(v => v.impact === 'serious').length : 0} Serious</span>
                         </div>
                    </div>
                    
                    ${r.violations && r.violations.length > 0 ? `
                        <div class="bg-gray-900/50 rounded-xl border border-white/5 overflow-hidden">
                             ${r.violations.map(v => `
                                <div class="p-4 border-b border-white/5 last:border-0 hover:bg-white/5 transition">
                                    <div class="flex items-start gap-4">
                                        <div class="mt-1">
                                            ${v.impact === 'critical' ? '<span class="text-red-500"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></span>' :
            v.impact === 'serious' ? '<span class="text-amber-500"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>' :
                '<span class="text-blue-500"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></span>'}
                                        </div>
                                        <div class="flex-1">
                                            <div class="flex justify-between">
                                                <h4 class="text-white font-medium text-sm">${v.help}</h4>
                                                <span class="text-xs font-mono text-gray-500">${v.id}</span>
                                            </div>
                                            <p class="text-gray-400 text-sm mt-1 mb-2">${v.description}</p>
                                            
                                            <div class="bg-black/30 p-2 rounded text-xs font-mono text-gray-300 border border-white/5 break-all">
                                                ${v.nodes && v.nodes.length > 0 ? v.nodes[0].target[0] : 'Global Issue'}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                             `).join('')}
                        </div>
                    ` : '<p class="text-green-400 text-sm">No violations found!</p>'}
                </div>
            `).join('')}
        </div>
        
        <!-- Export Button -->
        <div class="mt-8 text-center">
            <button onclick="exportResults()" class="px-6 py-3 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 rounded-xl font-bold text-lg shadow-lg shadow-amber-500/20">
                Export Results as CSV
            </button>
        </div>
    `;
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
        const headers = ['URL', 'Critical Issues', 'Serious Issues', 'Moderate Issues', 'Minor Issues', 'Violations Summary'];

        // Convert results to CSV rows
        const csvRows = currentResults.map(result => {
            const violations = result.violations || [];
            const critical = violations.filter(v => v.impact === 'critical').length;
            const serious = violations.filter(v => v.impact === 'serious').length;
            const moderate = violations.filter(v => v.impact === 'moderate').length;
            const minor = violations.filter(v => v.impact === 'minor').length;

            // Summary string
            const summary = violations.map(v => {
                return `${v.impact.toUpperCase()}: ${v.help} (${v.id})`;
            }).join('; ');

            // Return CSV formatted row
            return [
                `"${result.url.replace(/"/g, '""')}"`,
                critical,
                serious,
                moderate,
                minor,
                `"${summary.replace(/"/g, '""')}"`
            ].join(',');
        });

        // Combine headers and rows
        const csvContent = [headers.join(',')].concat(csvRows).join('\n');

        // Create blob and download link
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', `accessibility_audit_results_${sessionId || 'export'}.csv`);
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
