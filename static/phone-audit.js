// Phone Number Audit JavaScript
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const form = document.getElementById('upload-form');
const stopButton = document.getElementById('stop-button');
let sessionId = null;
let pollInterval = null;
let currentResults = null;

// Initialize drop zone
dropZone.onclick = () => fileInput.click();

fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (file) {
        dropZone.innerHTML = `
            <div class="w-24 h-24 mx-auto mb-4 bg-green-500/10 rounded-full flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-green-400"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
            </div>
            <p class="text-2xl text-green-400">${file.name}<br>Ready for phone audit!</p>
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
    const targetNumbers = document.querySelector('textarea[name="target_numbers"]').value;
    const selectedOptions = Array.from(document.querySelectorAll('input[name="option"]:checked'))
        .map(cb => cb.value);

    if (!targetNumbers.trim()) {
        Swal.fire({
            icon: 'info',
            title: 'Phone Numbers Required',
            text: 'Please enter at least one phone number to check for.',
            background: '#0f172a',
            color: '#f8fafc',
            confirmButtonColor: '#3b82f6'
        });
        return;
    }

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
    formData.append("target_numbers", targetNumbers.trim());
    formData.append("options", JSON.stringify(selectedOptions));

    try {
        const res = await fetch("/upload/phone", {
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

        document.getElementById('status-text').textContent = "Scanning for phone numbers...";

        // Start polling for progress
        pollInterval = setInterval(async () => {
            try {
                const progRes = await fetch(`/progress/phone/${sessionId}`);
                const prog = await progRes.json();
                const completed = prog.completed || 0;
                const total = prog.total || 1;
                const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
                const status = prog.status || "running";

                document.getElementById('progress-bar').style.width = `${percent}%`;
                document.getElementById('progress-bar').textContent = `${percent}%`;
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
        const res = await fetch(`/phone-results/${sessionId}`);

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
    const pagesWithPhones = results.filter(r => r.phone_count > 0).length;
    const pagesWithoutPhones = results.filter(r => r.phone_count === 0).length;
    const totalPhoneNumbers = results.reduce((sum, r) => sum + r.phone_count, 0);
    const averagePhonesPerPage = (totalPhoneNumbers / totalPages).toFixed(1);

    // Count issues
    let totalIssues = 0;
    results.forEach(r => {
        const issues = r.issues || [];
        totalIssues += issues.length;
    });

    contentArea.innerHTML = `
        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-green-500/30">
                <p class="text-gray-400 text-sm">Total Pages</p>
                <p class="text-3xl font-bold text-green-400">${totalPages}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-teal-500/30">
                <p class="text-gray-400 text-sm">Pages with Phones</p>
                <p class="text-3xl font-bold text-teal-400">${pagesWithPhones}</p>
                <p class="text-sm text-gray-400 mt-1">${Math.round((pagesWithPhones / totalPages) * 100)}%</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-blue-500/30">
                <p class="text-gray-400 text-sm">Total Phone Numbers</p>
                <p class="text-3xl font-bold text-blue-400">${totalPhoneNumbers}</p>
                <p class="text-sm text-gray-400 mt-1">${averagePhonesPerPage} per page</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-yellow-500/30">
                <p class="text-gray-400 text-sm">Issues Found</p>
                <p class="text-3xl font-bold text-yellow-400">${totalIssues}</p>
                <p class="text-sm text-gray-400 mt-1">${Math.round((totalIssues / totalPages) * 100)} per page</p>
            </div>
        </div>
        
        <!-- Detailed Results -->
        <div class="bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-gray-700/50">
            <h3 class="text-2xl font-bold text-green-300 mb-6">Detailed Results</h3>
            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="text-left border-b border-gray-700">
                            <th class="pb-3 px-4">URL</th>
                            <th class="pb-3 px-4">Phone Count</th>
                            <th class="pb-3 px-4">Status</th>
                            <th class="pb-3 px-4">Phone Numbers Found</th>
                            <th class="pb-3 px-4">Issues</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${results.map(result => {
        const phoneNumbers = result.phone_numbers || [];
        const issues = result.issues || [];
        const formats = result.formats_detected || [];

        const statusClass = result.phone_count === 0 ? 'bg-red-900/50 text-red-300' :
            issues.length === 0 ? 'bg-green-900/50 text-green-300' :
                'bg-yellow-900/50 text-yellow-300';

        const statusText = result.status || (result.phone_count === 0 ? 'Not Found' : 'Found');

        return `
                                <tr class="border-b border-gray-800/50 hover:bg-gray-800/30">
                                    <td class="py-4 px-4">
                                        <div class="font-medium truncate max-w-xs">${result.url}</div>
                                    </td>
                                    <td class="py-4 px-4">
                                        <span class="px-3 py-1 rounded-full text-lg font-bold ${result.phone_count > 0 ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}">
                                            ${result.phone_count}
                                        </span>
                                    </td>
                                    <td class="py-4 px-4">
                                        <span class="px-3 py-1 rounded-full text-sm ${statusClass}">
                                            ${statusText}
                                        </span>
                                        ${formats.length > 0 ? `<div class="text-xs text-gray-400 mt-1">${formats.join(', ')}</div>` : ''}
                                    </td>
                                    <td class="py-4 px-4">
                                        ${phoneNumbers.length > 0 ?
                `<div class="space-y-1">
                                                ${phoneNumbers.map(numData => {
                    const num = typeof numData === 'object' ? numData.number : numData;
                    const count = typeof numData === 'object' && numData.count ? numData.count : 1;
                    return `<div class="text-sm text-teal-300">
                                                        <span class="font-semibold">${num}</span>
                                                        ${count > 1 ? `<span class="text-xs text-gray-400 ml-2">(${count} times)</span>` : ''}
                                                    </div>`;
                }).join('')}
                                            </div>` :
                '<p class="text-gray-400 text-sm">None found</p>'
            }
                                    </td>
        <td class="py-4 px-4">
            ${issues.length > 0 ?
                `<div class="max-w-xs">
                                                ${issues.map(issue => `<p class="text-sm text-yellow-300 mb-1">${issue}</p>`).join('')}
                                            </div>` :
                '<p class="text-gray-400 text-sm">No issues</p>'
            }
        </td>
                                </tr >
        `;
    }).join('')}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Export Button -->
        <div class="mt-8 text-center">
            <button onclick="exportResults()" class="px-6 py-3 bg-gradient-to-r from-green-500 to-teal-600 hover:from-green-400 hover:to-teal-500 rounded-xl font-bold text-lg">
                Export Results as CSV
            </button>
        </div>
    `;
}

// Export results as CSV
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
        const headers = ['URL', 'Phone Count', 'Status', 'Phone Numbers', 'Issues'];

        // Convert results to CSV rows
        const csvRows = currentResults.map(result => {
            // Determine status text
            const statusText = result.status || (result.phone_count === 0 ? 'Not Found' : 'Found');

            // Format phone numbers
            let phonesStr = '';
            if (result.phone_numbers && Array.isArray(result.phone_numbers)) {
                phonesStr = result.phone_numbers.map(p => {
                    const num = typeof p === 'object' ? p.number : p;
                    const count = typeof p === 'object' && p.count ? ` (${p.count})` : '';
                    return num + count;
                }).join('; ');
            }

            // Format issues
            let issuesStr = '';
            if (result.issues && Array.isArray(result.issues)) {
                issuesStr = result.issues.join('; ');
            }

            // Return CSV formatted row
            return [
                `"${result.url.replace(/"/g, '""')}"`,
                result.phone_count,
                `"${statusText}"`,
                `"${phonesStr.replace(/"/g, '""')}"`,
                `"${issuesStr.replace(/"/g, '""')}"`
            ].join(',');
        });

        // Combine headers and rows
        const csvContent = [headers.join(',')].concat(csvRows).join('\n');

        // Create blob and download link
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', `phone_audit_results_${sessionId || 'export'}.csv`);
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

// Check for restart parameter on page load
// Check for restart parameter or session_id on page load
window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const sessionIdParam = urlParams.get('session_id') || urlParams.get('session');
    const statusParam = urlParams.get('status');
    const restartSessionId = urlParams.get('restart');

    if (statusParam === 'completed' && sessionIdParam) {
        sessionId = sessionIdParam; // Set global sessionId
        // Hide upload, show results
        document.getElementById('upload-section').classList.add('hidden');
        document.getElementById('results-section').classList.remove('hidden');
        loadResults();
    } else if (restartSessionId) {
        const restartConfig = sessionStorage.getItem('restartConfig');

        if (restartConfig) {
            try {
                const config = JSON.parse(restartConfig);

                // Pre-fill URLs
                if (config.urls && config.urls.length > 0) {
                    document.getElementById('manual-urls').value = config.urls.join('\n');
                }

                // Pre-fill session name
                if (config.name) {
                    document.querySelector('input[name="session_name"]').value = config.name + ' (Restarted)';
                }

                // Clear sessionStorage
                sessionStorage.removeItem('restartConfig');

                // Show success message and auto-submit
                Swal.fire({
                    icon: 'success',
                    title: 'Session Restarted',
                    text: 'Starting phone audit with previous configuration...',
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

            } catch (error) {
                console.error('Error parsing restart config:', error);
            }
        }
    }
});