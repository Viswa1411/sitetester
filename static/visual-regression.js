
const form = document.querySelector('form');
const resultsArea = document.getElementById('resultsArea');
const submitBtn = form.querySelector('button[type="submit"]');

// Check for existing session in URL
document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const status = urlParams.get('status');
    const sessionId = urlParams.get('session_id') || urlParams.get('session');

    if (status === 'completed' && sessionId) {
        // Show loading
        resultsArea.innerHTML = `
            <div class="glass-panel p-12 text-center rounded-2xl mb-8 border border-white/5 bg-slate-900/50">
                <div class="w-16 h-16 rounded-full bg-purple-500/10 text-purple-400 flex items-center justify-center mx-auto mb-4 animate-pulse">
                     <i data-lucide="loader-2" class="w-8 h-8 animate-spin"></i>
                </div>
                <h3 class="text-xl font-bold text-white">Loading Results</h3>
                <p class="text-slate-400 mt-2">Fetching comparison data...</p>
            </div>
        `;
        lucide.createIcons();

        // Fetch results immediately
        fetch(`/api/results/${sessionId}`)
            .then(res => res.json())
            .then(data => {
                if (data.results && data.results.length > 0) {
                    renderResults(data, sessionId);
                } else {
                    resultsArea.innerHTML = `<div class="p-4 bg-red-500/10 text-red-400 rounded-xl">No results found for session ${sessionId}</div>`;
                }
            })
            .catch(e => {
                console.error(e);
                resultsArea.innerHTML = `<div class="p-4 bg-red-500/10 text-red-400 rounded-xl">Error loading results: ${e.message}</div>`;
            });
    }
});

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const baseUrl = form.querySelector('input[name="base_url"]').value;
    const compareUrl = form.querySelector('input[name="compare_url"]').value;

    if (!baseUrl || !compareUrl) return;

    // UI Loading State
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin mr-2"></i> Comparing...';
    lucide.createIcons();

    resultsArea.innerHTML = `
        <div class="glass-panel p-12 text-center rounded-2xl mb-8 border border-white/5 bg-slate-900/50">
            <div class="w-16 h-16 rounded-full bg-purple-500/10 text-purple-400 flex items-center justify-center mx-auto mb-4 animate-pulse">
                <svg class="w-8 h-8 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg>
            </div>
            <h3 class="text-xl font-bold text-white">Visual Comparison Running</h3>
            <p class="text-slate-400 mt-2 max-w-md mx-auto">Capturing screenshots, analyzing DOM structure, and computing style differences...</p>
        </div>
    `;

    try {
        const formData = new FormData(form);
        // We actually need to change the backend to return JSON for this to work elegantly 
        // OR we just follow the redirect but handle it via fetch if possible. 
        // The current backend returns 303 Redirect. Fetch follows redirects.
        // We will receive the HTML of the new page. That's not what we want for SPA-like feel.
        // However, I haven't changed the TRIGGER endpoint to return JSON yet (I only changed get_results).
        // I should stick to the current "Redirect" behavior for the trigger?
        // No, the previous plan said "AJAX preferred". 
        // I will assume I'll change the trigger endpoint to JSON too, or handle the redirect.
        // For now, let's assume standard behavior (redirect) and see.
        // Wait, if I use fetch(), it follows redirect and returns the HTML of the result page.
        // If I want to implement polling, I need the `session_id`.
        // The endpoint currently returns a 303 to `/platform/visual?status=started`.
        // That doesn't give me the session ID.
        // I MUST change the trigger endpoint to return JSON with session_id to make this robust.

        // TEMPORARY: I will submit via AJAX, ignore content, and just start polling the "latest" session?
        // No, that's flaky. 
        // I'll update the trigger endpoint in Main.py first to return JSON like I did for Performance.

        // This file assumes main.py returns JSON.
        const res = await fetch('/api/visual-test', {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            const data = await res.json();
            if (data.status === 'started') {
                pollResults(data.session_id);
            }
        } else {
            throw new Error('Failed to start');
        }

    } catch (e) {
        console.error(e);
        resultsArea.innerHTML = `<div class="p-4 bg-red-500/10 text-red-400 rounded-xl">Error starting comparison: ${e.message}</div>`;
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Compare';
    }
});

async function pollResults(sessionId) {
    const interval = setInterval(async () => {
        try {
            const res = await fetch(`/api/results/${sessionId}`);
            if (res.ok) {
                const data = await res.json();
                // Check if we have results (either dom_diffs or results array)
                if (data.results && data.results.length > 0) {
                    clearInterval(interval);
                    renderResults(data, sessionId);
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = 'Compare';
                }
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 2000);
}

function renderResults(data, sessionId) {
    const diffs = data.dom_diffs || [];
    const pixelResult = data.results[0]; // Assuming single page comparison
    const diffImgUrl = pixelResult ? pixelResult.diff_img : '';

    // Construct Grid
    let html = `
        <div class="glass-panel p-6 rounded-2xl border border-white/5 animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div class="flex items-center justify-between mb-6">
                <h3 class="text-xl font-bold text-white">Comparison Results</h3>
                <div class="flex gap-2">
                     <span class="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded bg-red-500/20 text-red-400 border border-red-500/20">
                        <div class="w-2 h-2 rounded-full bg-red-500"></div> Removed
                     </span>
                     <span class="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded bg-green-500/20 text-green-400 border border-green-500/20">
                        <div class="w-2 h-2 rounded-full bg-green-500"></div> Added
                     </span>
                     <span class="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded bg-yellow-500/20 text-yellow-400 border border-yellow-500/20">
                        <div class="w-2 h-2 rounded-full bg-yellow-500"></div> Modified
                     </span>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 relative">
                <!-- Baseline -->
                <div class="relative group">
                    <div class="absolute -top-3 left-0 bg-slate-800 text-xs px-2 py-1 rounded border border-white/10 text-slate-400 z-10">Baseline (Original)</div>
                    <div class="relative overflow-hidden rounded-lg border border-white/10 bg-black">
                        <img src="/diffs/${sessionId}/base.png" class="w-full h-auto block" id="baseImg">
                        <div id="baseOverlay" class="absolute inset-0 pointer-events-none"></div>
                    </div>
                </div>

                <!-- Comparison -->
                <div class="relative group">
                    <div class="absolute -top-3 left-0 bg-slate-800 text-xs px-2 py-1 rounded border border-white/10 text-slate-400 z-10">Comparison (New)</div>
                    <div class="relative overflow-hidden rounded-lg border border-white/10 bg-black">
                        <img src="/diffs/${sessionId}/compare.png" class="w-full h-auto block" id="compImg">
                        <div id="compOverlay" class="absolute inset-0 pointer-events-none"></div>
                    </div>
                </div>
            </div>
            

        </div>
    `;

    resultsArea.innerHTML = html;

    // Draw Highlights
    drawHighlights(diffs);
}

function drawHighlights(diffs) {
    const baseOverlay = document.getElementById('baseOverlay');
    const compOverlay = document.getElementById('compOverlay');

    // Scale factor? Screenshots are 1280px wide. 
    // The displayed image width might differ. We need to calculate scale.
    const imgElement = document.getElementById('baseImg');

    // Wait for image load to get dimensions
    if (imgElement.complete) {
        process();
    } else {
        imgElement.onload = process;
    }

    function process() {
        const scale = imgElement.clientWidth / 1280; // 1280 is viewport width set in Playwright

        diffs.forEach(diff => {
            const rect = diff.rect;
            const scaledRect = {
                x: rect.x * scale,
                y: rect.y * scale,
                w: rect.width * scale,
                h: rect.height * scale
            };

            if (diff.type === 'removed') {
                createBox(baseOverlay, scaledRect, 'border-red-500 bg-red-500/10', `Removed: ${diff.tag} ${diff.text ? `"${diff.text}"` : ''}`);
            } else if (diff.type === 'added') {
                createBox(compOverlay, scaledRect, 'border-green-500 bg-green-500/10', `Added: ${diff.tag} ${diff.text ? `"${diff.text}"` : ''}`);
            } else if (diff.type === 'style_change') {
                const tooltip = Object.entries(diff.diffs).map(([k, v]) => `${k}: ${v.old} → ${v.new}`).join('\n');
                createBox(baseOverlay, scaledRect, 'border-yellow-500 bg-yellow-500/10', `Modified: ${diff.tag}\n${tooltip}`);
                createBox(compOverlay, scaledRect, 'border-yellow-500 bg-yellow-500/10', `Modified: ${diff.tag}\n${tooltip}`);
            }
        });
    }
}

function createBox(container, rect, classes, tooltipText) {
    const div = document.createElement('div');
    div.className = `absolute border-2 pointer-events-auto cursor-help transition-all hover:bg-opacity-30 z-20 ${classes}`;
    div.style.left = `${rect.x}px`;
    div.style.top = `${rect.y}px`;
    div.style.width = `${rect.w}px`;
    div.style.height = `${rect.h}px`;

    // Create Tooltip
    // We use a simple title attribute for native tooltip or custom if needed. 
    // Native is easier for now.
    div.title = tooltipText;

    container.appendChild(div);
}
