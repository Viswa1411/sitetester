// url-compare.js - Handle URL comparison form submission

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('compareForm');
    const compareBtn = document.getElementById('compareBtn');
    const loadingState = document.getElementById('loadingState');
    const errorDisplay = document.getElementById('errorDisplay');
    const errorMessage = document.getElementById('errorMessage');
    const loadingText = document.getElementById('loadingText');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Get form data
        const urlA = document.getElementById('urlA').value.trim();
        const urlB = document.getElementById('urlB').value.trim();
        const ignoreCase = document.getElementById('ignoreCase').checked;
        const ignoreWhitespace = document.getElementById('ignoreWhitespace').checked;
        const ignoreLinebreaks = document.getElementById('ignoreLinebreaks').checked;
        const sortLines = document.getElementById('sortLines').checked;

        // Validate URLs
        if (!urlA || !urlB) {
            showError('Please enter both URLs');
            return;
        }

        // Basic URL validation
        try {
            new URL(urlA);
            new URL(urlB);
        } catch (err) {
            showError('Please enter valid URLs (including http:// or https://)');
            return;
        }

        // Show loading state
        hideError();
        showLoading();
        disableForm();

        try {
            // Update loading text
            loadingText.textContent = 'Fetching URL A...';

            // Make API request
            const response = await fetch('/api/compare-urls', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url_a: urlA,
                    url_b: urlB,
                    ignore_case: ignoreCase,
                    ignore_whitespace: ignoreWhitespace,
                    ignore_linebreaks: ignoreLinebreaks,
                    sort_lines: sortLines
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Comparison failed');
            }

            // Success! Redirect to results page
            window.location.href = `/compare-results/${data.session_id}`;

        } catch (error) {
            console.error('Comparison error:', error);
            showError(error.message || 'An error occurred during comparison. Please try again.');
            hideLoading();
            enableForm();
        }
    });

    function showLoading() {
        loadingState.classList.remove('hidden');
    }

    function hideLoading() {
        loadingState.classList.add('hidden');
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorDisplay.classList.remove('hidden');
    }

    function hideError() {
        errorDisplay.classList.add('hidden');
    }

    function disableForm() {
        compareBtn.disabled = true;
        compareBtn.classList.add('opacity-50', 'cursor-not-allowed');
        const inputs = form.querySelectorAll('input');
        inputs.forEach(input => input.disabled = true);
    }

    function enableForm() {
        compareBtn.disabled = false;
        compareBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        const inputs = form.querySelectorAll('input');
        inputs.forEach(input => input.disabled = false);
    }

    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});
