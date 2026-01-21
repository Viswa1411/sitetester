// H1 Audit JavaScript
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const form = document.getElementById('upload-form');
const stopButton = document.getElementById('stop-button');
let sessionId = null;
let pollInterval = null;

// Initialize drop zone
dropZone.onclick = () => fileInput.click();

fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (file) {
        dropZone.innerHTML = `
            <div class="w-24 h-24 mx-auto mb-4 bg-green-500/10 rounded-full flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-400"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
            </div>
            <p class="text-2xl text-green-400">${file.name}<br>Ready for H1 audit!</p>
        `;
    }
};

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
    document.getElementById('status-text').textContent = "Uploading file and preparing...";
    stopButton.classList.remove('hidden');

    const formData = new FormData();
    if (fileInput.files[0]) {
        formData.append("file", fileInput.files[0]);
    }
    if (manualUrls.trim()) {
        formData.append("manual_urls", manualUrls.trim());
    }
    formData.append("session_name", sessionName);

    try {
        const res = await fetch("/upload/h1", {
            method: "POST",
            body: formData
        });

        if (!res.ok) {
            if (res.status === 401) {
                Swal.fire({
                    icon: 'warning',
                    title: 'Session Expired',
                    text: 'Your session has expired. Please log in again.',
                    background: '#0f172a',
                    color: '#f8fafc',
                    confirmButtonColor: '#3b82f6',
                    confirmButtonText: 'Go to Login'
                }).then(() => {
                    window.location.href = "/login";
                });
                return;
            }
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || errData.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        sessionId = data.session;

        document.getElementById('status-text').textContent = "Auditing H1 tags...";

        // Start polling for progress
        pollInterval = setInterval(async () => {
            try {
                const progRes = await fetch(`/progress/h1/${sessionId}`);
                const prog = await progRes.json();
                const completed = prog.completed || 0;
                const total = prog.total || 1;
                const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
                const status = prog.status || "running";

                document.getElementById('progress-bar').style.width = `${percent}%`;
                document.getElementById('progress-text').textContent = `${percent}%`;
                document.getElementById('status-text').textContent = `Audited ${completed} of ${total} pages...`;

                // Handle different statuses
                if (status === "stopped") {
                    clearInterval(pollInterval);
                    document.getElementById('status-text').textContent = "Session stopped by user.";
                    document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
                    stopButton.classList.add('hidden');

                    setTimeout(() => {
                        window.location.href = "/profile";
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
            title: 'Upload Failed',
            text: err.message || 'An error occurred during upload. Please try again.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6',
            footer: '<a href="/support" class="text-blue-400">Need help? Contact support</a>'
        });
        document.getElementById('upload-section').classList.remove('hidden');
        document.getElementById('progress-section').classList.add('hidden');
        if (pollInterval) clearInterval(pollInterval);
    }
};

// Load results
async function loadResults() {
    try {
        const res = await fetch(`/api/results/h1/${sessionId}`);

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

// ... displayResults ... (omitted for brevity, not changing)

// Check if we should auto-load results from URL parameters
window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const status = urlParams.get('status');
    const sessionIdParam = urlParams.get('session_id') || urlParams.get('session'); // Support both
    const restartParam = urlParams.get('restart');

    // Handle restart - pre-fill form from sessionStorage
    if (restartParam) {
        const restartConfig = sessionStorage.getItem('restartConfig');
        if (restartConfig) {
            try {
                const config = JSON.parse(restartConfig);

                // Pre-fill manual URLs textarea
                if (config.urls && config.urls.length > 0) {
                    const urlsTextarea = document.getElementById('manual-urls');
                    if (urlsTextarea) {
                        urlsTextarea.value = config.urls.join('\n');
                    }
                }

                // Pre-fill session name
                if (config.name) {
                    const sessionNameInput = document.querySelector('input[name="session_name"]');
                    if (sessionNameInput) {
                        sessionNameInput.value = config.name + ' (Restarted)';
                    }
                }

                // Clear sessionStorage after using
                sessionStorage.removeItem('restartConfig');

                // Show success message and auto-submit
                Swal.fire({
                    icon: 'success',
                    title: 'Session Restarted',
                    text: 'Starting H1 audit with previous configuration...',
                    background: '#0f172a',
                    color: '#f8fafc',
                    confirmButtonColor: '#3b82f6',
                    timer: 2000,
                    showConfirmButton: false
                });

                // Auto-submit the form after a short delay
                setTimeout(() => {
                    form.dispatchEvent(new Event('submit'));
                }, 2000);
            } catch (e) {
                console.error('Error loading restart config:', e);
            }
        }
    }

    // Handle completed status - show results
    if (status === 'completed' && sessionIdParam) {
        document.getElementById('upload-section').classList.add('hidden');
        document.getElementById('results-section').classList.remove('hidden');
        sessionId = sessionIdParam;
        loadResults();
    }
});

// Display results
function displayResults(results) {
    const contentArea = document.getElementById('content-area');

    if (!results || results.length === 0) {
        contentArea.innerHTML = `
            <div class="text-center py-12">
                <p class="text-2xl text-gray-400">No results found for this session.</p>
            </div>
        `;
        return;
    }

    // Calculate summary statistics
    const totalPages = results.length;
    const pagesWithH1 = results.filter(r => r.h1_count > 0).length;
    const pagesWithoutH1 = results.filter(r => r.h1_count === 0).length;
    const pagesWithMultipleH1 = results.filter(r => r.h1_count > 1).length;
    const averageH1Count = (results.reduce((sum, r) => sum + r.h1_count, 0) / totalPages).toFixed(1);

    contentArea.innerHTML = `
        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-purple-500/30">
                <p class="text-gray-400 text-sm">Total Pages</p>
                <p class="text-3xl font-bold text-purple-400">${totalPages}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-green-500/30">
                <p class="text-gray-400 text-sm">Pages with H1</p>
                <p class="text-3xl font-bold text-green-400">${pagesWithH1}</p>
                <p class="text-sm text-gray-400 mt-1">${Math.round((pagesWithH1 / totalPages) * 100)}%</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-red-500/30">
                <p class="text-gray-400 text-sm">Pages without H1</p>
                <p class="text-3xl font-bold text-red-400">${pagesWithoutH1}</p>
                <p class="text-sm text-gray-400 mt-1">${Math.round((pagesWithoutH1 / totalPages) * 100)}%</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-yellow-500/30">
                <p class="text-gray-400 text-sm">Multiple H1 Pages</p>
                <p class="text-3xl font-bold text-yellow-400">${pagesWithMultipleH1}</p>
                <p class="text-sm text-gray-400 mt-1">${Math.round((pagesWithMultipleH1 / totalPages) * 100)}%</p>
            </div>
        </div>
        
        <!-- Detailed Results -->
        <div class="bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-gray-700/50">
            <h3 class="text-2xl font-bold text-purple-300 mb-6">Detailed Results</h3>
            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="text-left border-b border-gray-700">
                            <th class="pb-3 px-4">URL</th>
                            <th class="pb-3 px-4">H1 Count</th>
                            <th class="pb-3 px-4">Status</th>
                            <th class="pb-3 px-4">H1 Texts</th>
                            <th class="pb-3 px-4">Issues</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${results.map(result => {
        const statusClass = result.h1_count === 0 ? 'bg-red-900/50 text-red-300' :
            result.h1_count === 1 ? 'bg-green-900/50 text-green-300' :
                'bg-yellow-900/50 text-yellow-300';

        const statusText = result.h1_count === 0 ? 'No H1' :
            result.h1_count === 1 ? 'Good' :
                'Multiple H1';

        // Safely parse h1_texts and issues - they might already be arrays or need parsing
        let h1Texts = [];
        let issues = [];

        try {
            h1Texts = typeof result.h1_texts === 'string' ? JSON.parse(result.h1_texts) : (result.h1_texts || []);
        } catch (e) {
            h1Texts = result.h1_texts ? [result.h1_texts] : [];
        }

        try {
            issues = typeof result.issues === 'string' ? JSON.parse(result.issues) : (result.issues || []);
        } catch (e) {
            issues = result.issues ? [result.issues] : [];
        }

        return `
                                <tr class="border-b border-gray-800/50 hover:bg-gray-800/30">
                                    <td class="py-4 px-4">
                                        <div class="font-medium truncate max-w-xs">${result.url}</div>
                                    </td>
                                    <td class="py-4 px-4">
                                        <span class="px-3 py-1 rounded-full text-lg font-bold">${result.h1_count}</span>
                                    </td>
                                    <td class="py-4 px-4">
                                        <span class="px-3 py-1 rounded-full text-sm ${statusClass}">
                                            ${statusText}
                                        </span>
                                    </td>
                                    <td class="py-4 px-4">
                                        ${h1Texts.length > 0 ?
                `<div class="space-y-1">
                                                ${h1Texts.map(text => `<div class="text-sm text-gray-300">"${text.substring(0, 50)}${text.length > 50 ? '...' : ''}"</div>`).join('')}
                                            </div>` :
                '<p class="text-gray-400 text-sm">No H1 tags found</p>'
            }
                                    </td>
                                    <td class="py-4 px-4 align-top">
                                        ${issues.length > 0 ?
                `<div class="space-y-2">
                                                <div class="text-sm text-yellow-300 font-semibold">${issues.join(', ')}</div>
                                                ${h1Texts.length > 1 ?
                    `<div class="ml-3 space-y-1 mt-2 border-l-2 border-yellow-500/30 pl-3">
                                                        ${h1Texts.map(text => `<div class="text-xs text-gray-400">• ${text}</div>`).join('')}
                                                    </div>` : ''
                }
                                            </div>` :
                '<p class="text-gray-400 text-sm">No issues</p>'
            }
                                    </td>
                                </tr>
                            `;
    }).join('')}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Export Button -->
        <div class="mt-8 text-center">
            <button onclick="exportResults()" class="px-6 py-3 bg-gradient-to-r from-purple-500 to-pink-600 hover:from-purple-400 hover:to-pink-500 rounded-xl font-bold text-lg">
                Export Results as CSV
            </button>
        </div>
    `;
}

// Export results as CSV
function exportResults() {
    Swal.fire({
        icon: 'info',
        title: 'Feature Coming Soon',
        html: 'CSV export is currently in development.<br><br>In the meantime, you can:<ul class="text-left mt-2 ml-4"><li>• Copy results from the table</li><li>• Take screenshots for reports</li><li>• Contact <a href="/support" class="text-blue-400">support</a> for bulk export assistance</li></ul>',
        background: '#0f172a',
        color: '#f8fafc',
        confirmButtonColor: '#3b82f6'
    });
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
            Swal.fire({
                icon: 'error',
                title: 'Unable to Stop Session',
                text: 'The session could not be stopped. It may have already completed.',
                background: '#0f172a',
                color: '#f8fafc',
                confirmButtonColor: '#3b82f6'
            });
            stopButton.disabled = false;
            stopButton.textContent = "Stop Session";
        }
    } catch (error) {
        Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'An error occurred while stopping the session.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
        stopButton.disabled = false;
        stopButton.textContent = "Stop Session";
    }
}

