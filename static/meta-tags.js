// Meta Tags Scanner JavaScript (Elite UI)

const scanForm = document.getElementById('scan-form');
const inputSection = document.getElementById('input-section');
const progressSection = document.getElementById('progress-section');
const resultsContainer = document.getElementById('results-container');
const progressBar = document.getElementById('progress-bar');
const progressStatus = document.getElementById('progress-status');
const stopButton = document.getElementById('stop-button'); // If hidden but exists in DOM

let sessionId = null;
let pollInterval = null;
let currentResults = null;

// Handle Form Submission
if (scanForm) {
    scanForm.onsubmit = async (e) => {
        e.preventDefault();

        const urlInput = document.getElementById('target-url');
        const url = urlInput.value.trim();

        if (!url) {
            Swal.fire({
                icon: 'warning',
                title: 'URL Required',
                text: 'Please enter a valid URL to scan.',
                background: '#0f172a',
                color: '#f8fafc',
                confirmButtonColor: '#3b82f6'
            });
            return;
        }

        // Show Progress
        // Instead of hiding input entirely, maybe just show progress below or modal?
        // The screenshot implies a full page state. Let's toggle sections.
        inputSection.classList.add('hidden');
        progressSection.classList.remove('hidden');
        resultsContainer.classList.add('hidden');

        // Prepare Data
        const formData = new FormData();
        formData.append("manual_urls", url);

        const sessionNameInput = document.getElementById('session-name');
        const sessionName = sessionNameInput && sessionNameInput.value.trim() ? sessionNameInput.value.trim() : `Meta Scan: ${new URL(url).hostname}`;
        formData.append("session_name", sessionName);

        try {
            const res = await fetch("/upload/meta-tags", {
                method: "POST",
                body: formData
            });

            if (!res.ok) {
                if (res.status === 401) {
                    window.location.href = "/login";
                    return;
                }
                const err = await res.json();
                throw new Error(err.error || err.detail || "Upload failed");
            }

            const data = await res.json();
            sessionId = data.session;

            startPolling(sessionId);

        } catch (err) {
            console.error(err);
            Swal.fire({
                icon: 'error',
                title: 'Scan Failed',
                text: err.message,
                background: '#0f172a',
                color: '#f8fafc'
            });
            inputSection.classList.remove('hidden');
            progressSection.classList.add('hidden');
        }
    };
}

function startPolling(sid) {
    progressStatus.textContent = "Initializing scanner...";

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/progress/meta-tags/${sid}`);
            const data = await res.json();

            const completed = data.completed || 0;
            const total = data.total || 1;
            const percent = Math.round((completed / total) * 100);
            const status = data.status || "running";

            // Update UI
            if (progressBar) progressBar.style.width = `${percent}%`;
            progressStatus.textContent = `Analyzing page structure and tags (${percent}%)...`;

            if (status === "completed") {
                clearInterval(pollInterval);
                progressStatus.textContent = "Finalizing report...";
                setTimeout(loadResults, 800);
            } else if (status === "error" || status === "stopped") {
                clearInterval(pollInterval);
                Swal.fire({
                    icon: 'error',
                    title: 'Scan Error',
                    text: 'The audit encountered an error or was stopped.',
                    background: '#0f172a',
                    color: '#f8fafc'
                });
                inputSection.classList.remove('hidden');
                progressSection.classList.add('hidden');
            }

        } catch (e) {
            console.error("Polling error", e);
        }
    }, 1500);
}

async function loadResults() {
    try {
        const res = await fetch(`/api/results/meta-tags/${sessionId}`);
        if (!res.ok) throw new Error("Failed to fetch results");

        const data = await res.json();
        renderResults(data.results || []);

    } catch (e) {
        console.error(e);
        Swal.fire('Error', 'Could not load results', 'error');
    }
}

function renderResults(results) {
    currentResults = results; // Store for export
    progressSection.classList.add('hidden');
    resultsContainer.classList.remove('hidden');
    resultsContainer.innerHTML = '';

    if (results.length === 0) {
        resultsContainer.innerHTML = '<p class="text-center text-gray-400">No results found.</p>';
        return;
    }

    // We render each result as a massive card stack (matching screenshot)
    results.forEach(result => {
        const html = generateResultCard(result);
        resultsContainer.insertAdjacentHTML('beforeend', html);
    });

    // Inject Export Button at the bottom
    const exportBtnHtml = `
    <div class="mt-8 text-center pb-12">
        <button onclick="exportResults()" class="px-6 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded-xl font-bold text-lg shadow-lg shadow-blue-500/20 text-white">
            Export Results as CSV
        </button>
    </div>
    `;
    resultsContainer.insertAdjacentHTML('beforeend', exportBtnHtml);
}

function generateResultCard(r) {
    // Helper colors
    const getScoreColor = (s) => s >= 90 ? 'text-green-400' : (s >= 50 ? 'text-yellow-400' : 'text-red-400');
    const getScoreBar = (s) => s >= 90 ? 'bg-green-500' : (s >= 50 ? 'bg-yellow-500' : 'bg-red-500');

    // Stats
    const titleLen = r.title ? r.title.length : 0;
    const descLen = r.description ? r.description.length : 0;

    // Status Logic
    const titleStatus = !r.title ? 'Missing' : (titleLen < 30 ? 'Too Short' : (titleLen > 60 ? 'Too Long' : 'Good'));
    const titleClass = titleStatus === 'Good' ? 'text-green-400' : 'text-red-400';

    const descStatus = !r.description ? 'Missing' : (descLen < 70 ? 'Too Short' : (descLen > 155 ? 'Too Long' : 'Good'));
    const descClass = descStatus === 'Good' ? 'text-green-400' : 'text-red-400';

    const canonStatus = r.canonical ? 'Valid' : 'Missing';
    const canonClass = r.canonical ? 'text-green-400' : 'text-red-400';

    // OG Image
    const ogImage = r.og_tags && r.og_tags['og:image'] ? r.og_tags['og:image'] : '';

    // Keywords Consistency Table
    let keywordRows = '';
    if (r.keyword_consistency) {
        Object.entries(r.keyword_consistency).slice(0, 5).forEach(([kw, count]) => {
            keywordRows += `
            <tr class="border-b border-gray-800/50">
                <td class="py-2 text-gray-300 capitalize">${kw}</td>
                <td class="py-2 text-right text-gray-400">${count}</td>
                <td class="py-2 text-right text-green-400 text-xs">Found</td>
            </tr>`;
        });
    }

    // Schema
    const schemaList = r.schema_tags && r.schema_tags.length > 0 ?
        r.schema_tags.map(s => `<span class="bg-blue-500/20 text-blue-300 px-2 py-1 rounded text-xs border border-blue-500/30">${s['@type'] || 'Unknown'}</span>`).join('') :
        '<span class="text-gray-500 italic">No schema detected</span>';

    // Full Metadata Rows
    let metaRows = '';
    // Standard
    if (r.title) metaRows += metaRow('Meta', 'Title', r.title);
    if (r.description) metaRows += metaRow('Meta', 'Description', r.description);
    if (r.canonical) metaRows += metaRow('Link', 'Canonical', r.canonical);

    // OG
    if (r.og_tags) {
        Object.entries(r.og_tags).forEach(([k, v]) => metaRows += metaRow('OpenGraph', k, v));
    }
    // Twitter
    if (r.twitter_tags) {
        Object.entries(r.twitter_tags).forEach(([k, v]) => metaRows += metaRow('Twitter', k, v));
    }

    // Warnings
    const warningList = (r.warnings || []).map(w => `<li class="flex items-start gap-2 text-sm text-red-300"><span class="mt-1 w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0"></span>${w}</li>`).join('');


    return `
    <div class="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden mb-12">
        <!-- Result Header -->
        <div class="p-6 border-b border-gray-800 flex justify-between items-center bg-gray-950/50">
            <h2 class="text-xl font-bold text-white truncate max-w-2xl">${r.url}</h2>
            <div class="flex gap-2">
                <button onclick="window.open('${r.url}', '_blank')" class="p-2 hover:bg-gray-800 rounded-lg text-gray-400"><i data-lucide="external-link" class="w-4 h-4"></i></button>
            </div>
        </div>

        <div class="p-8 space-y-8">
            <!-- 1. Score Cards Row -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
                <!-- SEO Score -->
                <div class="glass-panel p-6 rounded-xl relative overflow-hidden group">
                    <div class="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition">
                        <i data-lucide="activity" class="w-12 h-12 text-blue-400"></i>
                    </div>
                    <p class="text-xs text-gray-500 uppercase tracking-widest font-bold mb-4">SEO Health Score</p>
                    <div class="flex items-baseline gap-1">
                        <span class="text-5xl font-bold ${getScoreColor(r.score)}">${r.score}</span>
                        <span class="text-gray-500">/100</span>
                    </div>
                    <div class="w-full bg-gray-800 h-1.5 mt-4 rounded-full overflow-hidden">
                        <div class="${getScoreBar(r.score)} h-full" style="width: ${r.score}%"></div>
                    </div>
                </div>

                <!-- Title Length -->
                <div class="glass-panel p-6 rounded-xl">
                    <div class="flex justify-between items-start mb-2">
                        <p class="text-sm text-gray-400">Title Length</p>
                        <i data-lucide="type" class="w-4 h-4 text-gray-600"></i>
                    </div>
                    <div class="mb-2">
                        <span class="text-3xl font-bold text-white">${titleLen}</span>
                        <span class="text-xs text-gray-500">chars</span>
                    </div>
                    <p class="text-xs text-gray-500 mb-2">Ideal: 30-60 chars</p>
                    <span class="px-2 py-0.5 rounded text-xs font-bold bg-gray-800 border ${titleClass === 'text-green-400' ? 'border-green-500/30 text-green-400' : 'border-red-500/30 text-red-400'}">${titleStatus}</span>
                </div>

                <!-- Desc Length -->
                <div class="glass-panel p-6 rounded-xl">
                    <div class="flex justify-between items-start mb-2">
                        <p class="text-sm text-gray-400">Description Length</p>
                        <i data-lucide="align-left" class="w-4 h-4 text-gray-600"></i>
                    </div>
                    <div class="mb-2">
                        <span class="text-3xl font-bold text-white">${descLen}</span>
                        <span class="text-xs text-gray-500">chars</span>
                    </div>
                    <p class="text-xs text-gray-500 mb-2">Ideal: 70-155 chars</p>
                    <span class="px-2 py-0.5 rounded text-xs font-bold bg-gray-800 border ${descClass === 'text-green-400' ? 'border-green-500/30 text-green-400' : 'border-red-500/30 text-red-400'}">${descStatus}</span>
                </div>

                <!-- Canonical -->
                <div class="glass-panel p-6 rounded-xl">
                    <div class="flex justify-between items-start mb-2">
                        <p class="text-sm text-gray-400">Canonical</p>
                        <i data-lucide="link-2" class="w-4 h-4 text-gray-600"></i>
                    </div>
                    <div class="mb-2">
                        <span class="text-xl font-bold ${canonClass}">${canonStatus}</span>
                    </div>
                    <p class="text-xs text-gray-500">Prevents duplicate content</p>
                </div>
            </div>

            <!-- 2. Live Previews -->
            <div>
                <h3 class="text-lg font-bold text-purple-300 border-l-4 border-purple-500 pl-3 mb-6">Live Previews</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <!-- Google Preview -->
                    <div class="bg-white rounded-xl p-6 shadow-lg">
                        <div class="flex items-center gap-2 mb-3">
                            <div class="w-6 h-6 bg-gray-100 rounded-full flex items-center justify-center text-xs">G</div>
                            <span class="text-xs text-gray-500">Google Search Result</span>
                        </div>
                        <div class="mb-1">
                            <div class="text-xs text-gray-600 truncate">${r.url}</div>
                            <h4 class="text-xl text-[#1a0dab] hover:underline cursor-pointer truncate font-medium">${r.title || 'No Title'}</h4>
                        </div>
                        <p class="text-sm text-[#4d5156] line-clamp-2 leading-relaxed">
                            ${r.description || 'No description found.'}
                        </p>
                    </div>

                    <!-- Social Preview -->
                    <div class="bg-gray-100 rounded-xl overflow-hidden shadow-lg border border-gray-200">
                        <div class="p-4 border-b border-gray-200 bg-white flex justify-between items-center">
                            <span class="text-xs text-gray-500 font-bold">Social Share (Facebook/LinkedIn)</span>
                        </div>
                        <div class="aspect-video bg-gray-300 relative overflow-hidden flex items-center justify-center">
                            ${ogImage ? `<img src="${ogImage}" class="w-full h-full object-cover" onerror="this.src='https://via.placeholder.com/600x315?text=No+Image'"/>` : '<span class="text-gray-500 font-bold">No Image Found</span>'}
                        </div>
                        <div class="p-4 bg-[#f0f2f5]">
                            <p class="text-xs text-gray-500 uppercase mb-1 truncate">${new URL(r.url).hostname}</p>
                            <h4 class="text-base font-bold text-gray-900 mb-1 truncate">${r.og_tags && r.og_tags['og:title'] ? r.og_tags['og:title'] : (r.title || 'No Title')}</h4>
                            <p class="text-sm text-gray-600 line-clamp-2">${r.og_tags && r.og_tags['og:description'] ? r.og_tags['og:description'] : (r.description || 'No description.')}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 3. Elite Analysis -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                <!-- Schema -->
                <div class="glass-panel p-6 rounded-xl border border-gray-700/50">
                    <h3 class="text-lg font-bold text-green-400 mb-4 flex items-center gap-2">
                        <i data-lucide="code" class="w-5 h-5"></i> Structured Data (Schema.org)
                    </h3>
                    <div class="bg-gray-900/50 rounded-lg p-4 min-h-[100px] flex flex-wrap gap-2 content-start">
                        ${schemaList}
                    </div>
                </div>

                <!-- Keyword Consistency -->
                <div class="glass-panel p-6 rounded-xl border border-gray-700/50">
                     <h3 class="text-lg font-bold text-yellow-400 mb-4 flex items-center gap-2">
                        <i data-lucide="bar-chart-2" class="w-5 h-5"></i> Keyword Consistency
                    </h3>
                    <div class="overflow-hidden">
                        <table class="w-full text-sm">
                            <thead>
                                <tr class="text-left text-gray-500 border-b border-gray-700">
                                    <th class="pb-2 font-normal">Keyword</th>
                                    <th class="pb-2 font-normal text-right">Frequency</th>
                                    <th class="pb-2 font-normal text-right">Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${keywordRows || '<tr><td colspan="3" class="py-4 text-center text-gray-500">No keyword data</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- 4. Full Metadata -->
            <div class="glass-panel p-6 rounded-xl border border-gray-700/50">
                <h3 class="text-lg font-bold text-blue-300 border-l-4 border-blue-500 pl-3 mb-6">Full Metadata</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm text-left">
                        <thead>
                            <tr class="bg-gray-800/50 text-gray-400 uppercase text-xs tracking-wider">
                                <th class="px-4 py-3 rounded-tl-lg">Tag Type</th>
                                <th class="px-4 py-3">Key</th>
                                <th class="px-4 py-3 rounded-tr-lg">Value</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-800">
                             ${metaRows}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- 5. Recommendations -->
            ${warningList ? `
            <div class="bg-red-900/10 border border-red-900/30 rounded-xl p-6">
                <h3 class="text-lg font-bold text-red-400 mb-4 flex items-center gap-2">
                    <i data-lucide="alert-triangle" class="w-5 h-5"></i> Recommendations
                </h3>
                <ul class="space-y-2">
                    ${warningList}
                </ul>
            </div>` : ''}

        </div>
    </div>
    `;
}
// Export Results
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
        const headers = [
            'URL', 'Score',
            'Title', 'Title Len',
            'Description', 'Desc Len',
            'Canonical',
            'OG Title', 'OG Description', 'OG Image',
            'Top Keywords', 'Warnings'
        ];

        // Convert results to CSV rows
        const csvRows = currentResults.map(result => {
            // Keywords
            let topKeywords = '';
            if (result.keyword_consistency) {
                topKeywords = Object.keys(result.keyword_consistency).slice(0, 5).join('; ');
            }

            // OG
            const ogTitle = result.og_tags && result.og_tags['og:title'] ? result.og_tags['og:title'] : '';
            const ogDesc = result.og_tags && result.og_tags['og:description'] ? result.og_tags['og:description'] : '';
            const ogImage = result.og_tags && result.og_tags['og:image'] ? result.og_tags['og:image'] : '';

            // Warnings
            const warnings = (result.warnings || []).join('; ');

            // Return CSV formatted row
            return [
                `"${(result.url || '').replace(/"/g, '""')}"`,
                result.score || 0,
                `"${(result.title || '').replace(/"/g, '""')}"`,
                (result.title || '').length,
                `"${(result.description || '').replace(/"/g, '""')}"`,
                (result.description || '').length,
                `"${(result.canonical || '').replace(/"/g, '""')}"`,
                `"${ogTitle.replace(/"/g, '""')}"`,
                `"${ogDesc.replace(/"/g, '""')}"`,
                `"${ogImage.replace(/"/g, '""')}"`,
                `"${topKeywords.replace(/"/g, '""')}"`,
                `"${warnings.replace(/"/g, '""')}"`
            ].join(',');
        });

        // Combine headers and rows
        const csvContent = [headers.join(',')].concat(csvRows).join('\n');

        // Create blob and download link
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.setAttribute('href', url);
        link.setAttribute('download', `mata_tags_audit_results_${sessionId || 'export'}.csv`);
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
function metaRow(type, key, val) {
    return `
    <tr class="hover:bg-gray-800/30 transition">
        <td class="px-4 py-3 text-gray-400">${type}</td>
        <td class="px-4 py-3 text-blue-300 font-mono text-xs">${key}</td>
        <td class="px-4 py-3 text-gray-300 break-all">${val}</td>
    </tr>`;
}

// Initial Load Check
window.addEventListener('DOMContentLoaded', () => {
    // Re-initialize Lucide icons just in case
    if (window.lucide) lucide.createIcons();

    // Check URL params for auto-load
    const urlParams = new URLSearchParams(window.location.search);
    const sid = urlParams.get('session_id') || urlParams.get('session');
    const restartParam = urlParams.get('restart');

    if (sid && urlParams.get('status') === 'completed') {
        sessionId = sid;
        inputSection.classList.add('hidden');
        loadResults();
    } else if (restartParam) {
        // Handle restart - load config from session storage
        const configStr = sessionStorage.getItem('restartConfig');
        if (configStr) {
            try {
                const config = JSON.parse(configStr);

                // Only use config if it matches the requested restart session
                if (config.session_id === restartParam) {

                    // 1. Pre-fill URL (Meta Tags scanner handles single URL usually)
                    if (config.urls && Array.isArray(config.urls) && config.urls.length > 0) {
                        const urlInput = document.getElementById('target-url');
                        if (urlInput) urlInput.value = config.urls[0];
                    }

                    // 2. Pre-fill Project Name
                    if (config.name) {
                        const sessionNameInput = document.getElementById('session-name');
                        if (sessionNameInput) sessionNameInput.value = config.name;
                    }

                    // 3. Auto-start the scan
                    if (document.getElementById('target-url').value) {
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
