
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-upload');
const form = document.querySelector('form');
const resultsArea = document.getElementById('resultsArea');
const submitBtn = form.querySelector('button[type="submit"]');

// File Upload Logic
if (dropZone && fileInput) {
    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            dropZone.innerHTML = `
                <div class="flex flex-col items-center justify-center pt-5 pb-6">
                    <div class="w-12 h-12 mb-4 rounded-full bg-green-500/20 flex items-center justify-center">
                        <i data-lucide="check" class="w-6 h-6 text-green-500"></i>
                    </div>
                    <p class="mb-2 text-sm text-green-400 font-semibold">${file.name}</p>
                    <p class="text-xs text-gray-400">Ready to upload</p>
                </div>
            `;
            dropZone.classList.add('border-green-500/50', 'bg-green-500/5');
            dropZone.classList.remove('border-white/10');
            lucide.createIcons();
        }
    });

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        dropZone.classList.add('border-amber-500', 'bg-slate-800');
    }

    function unhighlight(e) {
        dropZone.classList.remove('border-amber-500', 'bg-slate-800');
    }

    dropZone.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            fileInput.files = files;
            fileInput.dispatchEvent(new Event('change'));
        }
    }
}

// AJAX Submission & Polling
form.addEventListener('submit', async (e) => {
    e.preventDefault();

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin mr-2"></i> Starting Audit...';
    lucide.createIcons();

    resultsArea.innerHTML = `
        <div class="glass-panel p-12 text-center rounded-2xl mb-8 border border-white/5 bg-slate-900/50">
            <div class="w-16 h-16 rounded-full bg-amber-500/10 text-amber-400 flex items-center justify-center mx-auto mb-4 animate-pulse">
                 <i data-lucide="loader-2" class="w-8 h-8 animate-spin"></i>
            </div>
            <h3 class="text-xl font-bold text-white">Running Accessibility Audit</h3>
            <p class="text-slate-400 mt-2">Checking for WCAG 2.1 violations...</p>
        </div>
    `;
    lucide.createIcons();

    try {
        const formData = new FormData(form);
        const res = await fetch('/api/accessibility-test', {
            method: 'POST',
            body: formData,
            headers: {
                'Accept': 'application/json'
            }
        });

        if (res.ok) {
            const data = await res.json();
            if (data.status === 'started') {
                pollResults(data.session_id);
            }
        } else {
            throw new Error('Failed to start audit');
        }
    } catch (e) {
        console.error(e);
        resultsArea.innerHTML = `<div class="p-4 bg-red-500/10 text-red-400 rounded-xl">Error: ${e.message}</div>`;
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Start Accessibility Audit';
    }
});

async function pollResults(sessionId) {
    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/api/results/${sessionId}`);
            if (res.ok) {
                const results = await res.json();
                if (results && results.length > 0) {
                    clearInterval(interval);
                    renderResults(results);
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Start Accessibility Audit';
                }
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 2000);
}

function renderResults(results) {
    const auditFormContainer = document.getElementById('auditFormContainer');
    if (auditFormContainer) {
        auditFormContainer.style.display = 'none';
    }

    let html = `
        <div class="glass-panel p-6 rounded-2xl border border-white/5 animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div class="flex justify-between items-center mb-6">
                <h3 class="text-xl font-bold text-white">Audit Results</h3>
                <button onclick="window.location.reload()" class="px-4 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition text-sm">
                    New Audit
                </button>
            </div>
            <div class="space-y-4">
    `;

    results.forEach(r => {
        html += `
            <div class="p-4 bg-slate-900/50 rounded-xl border border-white/10">
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-4">
                    <div class="font-medium text-white break-all">${r.url}</div>
                    <div class="flex items-center gap-4">
                         <!-- Removed Score/Issues Stats -->
                    </div>
                </div>
                
                <!-- Removed Stats Grid -->
                
                ${r.violations && r.violations.length > 0 ? `
                <div class="mt-6 border-t border-white/5 pt-4">
                    <h4 class="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">Detected Violations</h4>
                    <div class="space-y-3">
                        ${r.violations.map(v => `
                            <div class="p-3 bg-black/20 rounded-lg border border-white/5 hover:bg-black/40 transition">
                                <div class="flex items-start gap-3">
                                    <div class="mt-1">
                                        ${v.impact === 'critical' ? '<i data-lucide="alert-circle" class="w-4 h-4 text-red-500"></i>' :
                v.impact === 'serious' ? '<i data-lucide="alert-triangle" class="w-4 h-4 text-amber-500"></i>' :
                    v.impact === 'moderate' ? '<i data-lucide="info" class="w-4 h-4 text-blue-500"></i>' :
                        '<i data-lucide="check-circle" class="w-4 h-4 text-slate-500"></i>'}
                                    </div>
                                    <div class="flex-1">
                                        <div class="flex justify-between items-start">
                                            <span class="font-medium text-slate-200 text-sm">${v.help}</span>
                                            <span class="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-white/10">${v.id}</span>
                                        </div>
                                        <p class="text-xs text-slate-500 mt-1">${v.description}</p>
                                        <div class="mt-2 text-xs font-mono bg-black/30 p-2 rounded text-slate-400 overflow-x-auto">
                                            ${v.nodes && v.nodes.length > 0 ? `Target: ${v.nodes[0].target[0]}` : 'Global Issue'}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
            </div>
        `;
    });

    html += `
            </div>
        </div>
    `;

    resultsArea.innerHTML = html;
    lucide.createIcons();
}

// Auto-load results from URL
document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const status = urlParams.get('status');
    const sessionId = urlParams.get('session');

    if (status === 'completed' && sessionId) {
        pollResults(sessionId);
    }
});
