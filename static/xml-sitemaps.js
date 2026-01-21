// XML Sitemaps Audit JavaScript
const form = document.getElementById('upload-form');
const stopButton = document.getElementById('stop-button');
let sessionId = null;
let pollInterval = null;

// Form submission
form.onsubmit = async (e) => {
    e.preventDefault();

    const url = document.getElementById('sitemap-url').value;

    if (!url.trim()) {
        Swal.fire({
            icon: 'info',
            title: 'Input Required',
            text: 'Please enter a valid Sitemap URL.',
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
    document.getElementById('status-text').textContent = "Initializing sitemap crawl...";
    stopButton.classList.remove('hidden');

    const formData = new FormData();
    formData.append("url", url.trim());
    formData.append("session_name", sessionName);

    try {
        const res = await fetch("/upload/sitemap", {
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

        document.getElementById('status-text').textContent = "Crawling sitemap...";

        // Start polling for progress
        pollInterval = setInterval(async () => {
            try {
                const progRes = await fetch(`/progress/sitemap/${sessionId}`);
                const prog = await progRes.json();
                const completed = prog.completed || 0;
                const total = prog.total || 1;
                const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
                const status = prog.status || "running";

                document.getElementById('progress-bar').style.width = `${percent}%`;
                document.getElementById('progress-bar').textContent = `${percent}%`;
                document.getElementById('status-text').textContent = `Processed ${completed} URLs...`;

                if (status === "stopped") {
                    clearInterval(pollInterval);
                    document.getElementById('status-text').textContent = "Session stopped by user.";
                    document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
                    stopButton.classList.add('hidden');
                    return;
                }

                if (status === "error") {
                    clearInterval(pollInterval);
                    document.getElementById('status-text').textContent = "Session encountered an error.";
                    document.getElementById('progress-bar').style.backgroundColor = "#dc2626";
                    stopButton.classList.add('hidden');
                    return;
                }

                if (status === "completed") {
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
        const res = await fetch(`/api/results/sitemap/${sessionId}`);

        if (!res.ok) {
            throw new Error("Failed to load results");
        }

        const data = await res.json();
        // data.results is object for sitemap
        displayResults(data.results || {});
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
    const contentArea = document.getElementById('content-area');

    if (!results || Object.keys(results).length === 0) {
        contentArea.innerHTML = `
            <div class="text-center py-12">
                <p class="text-2xl text-gray-400">No results found for this session.</p>
            </div>
        `;
        return;
    }

    const loadTime = results.load_time_ms || 0;
    const urlCount = results.url_count || 0;
    const isIndex = results.is_index || false;
    const score = results.score || 0;
    const robotsStatus = results.robots_status || 'unknown';

    const childSitemaps = results.child_sitemaps || [];
    const reachability = results.reachability_sample || {};
    const issues = [...(results.errors || []), ...(results.warnings || [])];

    contentArea.innerHTML = `
        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Sitemap Score</p>
                <div class="flex items-end gap-2">
                     <p class="text-3xl font-bold ${getScoreColor(score)}">${score}</p>
                </div>
                <div class="w-full bg-gray-700 h-1.5 rounded-full mt-2 overflow-hidden">
                    <div class="h-full ${getScoreBgColor(score)}" style="width: ${score}%"></div>
                </div>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Total URLs</p>
                <p class="text-3xl font-bold text-white">${urlCount.toLocaleString()}</p>
                <p class="text-xs text-gray-500 mt-1">${isIndex ? 'Sitemap Index' : 'Standard Sitemap'}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Robots.txt Declaration</p>
                <p class="text-3xl font-bold ${robotsStatus === 'found' ? 'text-emerald-400' : 'text-red-400'} capitalize">${robotsStatus}</p>
            </div>
            <div class="bg-gray-800/50 rounded-2xl p-6 border border-gray-700/50">
                <p class="text-gray-400 text-sm">Load Time</p>
                <p class="text-3xl font-bold text-blue-400">${loadTime}ms</p>
                <p class="text-xs text-gray-500 mt-1">Target: < 1000ms</p>
            </div>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <!-- Sitemap Structure -->
            <div class="bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-gray-700/50">
                <h3 class="text-xl font-bold text-emerald-300 mb-4 flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 5v4"/><path d="M12 15v4"/><path d="M5 12h4"/><path d="M15 12h4"/></svg>
                    Sitemap Structure
                </h3>
                <div class="bg-slate-900/50 rounded-xl p-4 border border-white/5 h-[300px] overflow-y-auto font-mono text-sm">
                    <div class="text-emerald-400 mb-2 font-bold flex items-center gap-2">
                        <span>root</span> <span class="text-gray-400 font-normal">${results.url}</span>
                    </div>
                    <div class="pl-6 border-l border-white/10 space-y-2">
                         ${isIndex && childSitemaps.length > 0 ?
            childSitemaps.map(child => `
                                <div class="text-slate-400 hover:text-white transition-colors truncate">
                                    ├── <span class="bg-slate-800 px-1 rounded text-xs text-blue-300">nested</span> ${child}
                                </div>
                            `).join('') :
            `<div class="text-slate-500 italic">Contains ${urlCount} URLs (Direct List)</div>`
        }
                    </div>
                </div>
            </div>

            <!-- Reachability -->
            <div class="bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-gray-700/50">
                <h3 class="text-xl font-bold text-emerald-300 mb-4 flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                    Reachability Sample
                </h3>
                <div class="overflow-hidden rounded-xl border border-white/5">
                    <table class="w-full text-left">
                        <thead class="bg-slate-800/50">
                            <tr class="text-xs text-slate-500 uppercase">
                                <th class="p-3">Sample URL</th>
                                <th class="p-3 text-right">Status</th>
                            </tr>
                        </thead>
                        <tbody class="bg-slate-900/30 text-sm divide-y divide-white/5">
                             ${Object.keys(reachability).length > 0 ?
            Object.entries(reachability).map(([url, status]) => `
                                    <tr>
                                        <td class="p-3 text-slate-400 truncate max-w-[200px]" title="${url}">${url}</td>
                                        <td class="p-3 text-right ${status === 200 ? 'text-emerald-400' : 'text-red-400'} font-mono font-bold">${status}</td>
                                    </tr>
                                `).join('') :
            '<tr><td colspan="2" class="p-4 text-center text-gray-500">No sample checked or empty.</td></tr>'
        }
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Issues -->
        <div class="mt-8 bg-gray-800/30 backdrop-blur rounded-2xl p-6 border border-yellow-500/20 bg-yellow-500/5">
            <h3 class="text-xl font-bold text-white mb-4 flex items-center gap-2">
                 <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-yellow-400"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                 Issues Found
            </h3>
            <ul class="space-y-2">
                ${issues.length > 0 ?
            issues.map(i => `<li class="text-red-300 text-sm flex items-start gap-2"><span class="mt-1">•</span> ${i}</li>`).join('') :
            '<li class="text-emerald-400 text-sm flex items-center gap-2">No critical issues found!</li>'
        }
            </ul>
        </div>
        
        <!-- Export Button -->
        <div class="mt-8 text-center">
            <button onclick="exportResults()" class="px-6 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 rounded-xl font-bold text-lg shadow-lg shadow-emerald-500/20">
                Export Results as CSV
            </button>
        </div>
    `;
}

function getScoreColor(score) {
    if (score >= 90) return 'text-emerald-400';
    if (score >= 70) return 'text-yellow-400';
    return 'text-red-400';
}

function getScoreBgColor(score) {
    if (score >= 90) return 'bg-emerald-500';
    if (score >= 70) return 'bg-yellow-500';
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

function exportResults() {
    Swal.fire({
        icon: 'info',
        title: 'Feature Coming Soon',
        text: 'Export functionality is currently being implemented.',
        background: '#0f172a',
        color: '#f8fafc',
        confirmButtonColor: '#3b82f6'
    });
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

                    // 1. Pre-fill URL (XML sitemap is usually single URL)
                    if (config.urls && Array.isArray(config.urls) && config.urls.length > 0) {
                        // config.urls might be a list of 1 sitemap URL
                        const urlInput = document.getElementById('sitemap-url');
                        if (urlInput) urlInput.value = config.urls[0];
                    }

                    // 2. Pre-fill Project Name
                    if (config.name) {
                        const nameInput = document.querySelector('input[name="session_name"]');
                        if (nameInput) nameInput.value = config.name;
                    }

                    // 3. Auto-start the scan
                    if (document.getElementById('sitemap-url').value) {
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
