(function () {
    const btnRun = document.getElementById('btnRun');
    const planList = document.getElementById('planList');
    const chainContainer = document.getElementById('chainContainer');
    const emptyChain = document.getElementById('emptyChain');
    const detailContent = document.getElementById('detailContent');

    let API_BASE = location.origin.replace(/\/static.*$/, '');
    let selectedPlan = null;
    let currentPlanData = null;

    if (btnRun) btnRun.disabled = true;
    let currentRequests = [];
    let selectedStepIndex = null;

    function updateRunButtonState() {
        btnRun.disabled = !selectedPlan;
    }

    function api(path, options = {}) {
        const url = (API_BASE.replace(/\/$/, '') + path).replace(/([^:]\/)\/+/g, '$1');
        return fetch(url, options).then(r => {
            if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
            return r.json();
        });
    }

    function getMethodClass(m) {
        const u = (m || '').toUpperCase();
        if (u === 'GET') return 'GET';
        if (u === 'POST') return 'POST';
        if (u === 'PUT') return 'PUT';
        if (u === 'DELETE') return 'DELETE';
        return '';
    }

    async function loadPlans() {
        try {
            const data = await api('/testplans');
            const plans = data.testPlans || {};
            planList.innerHTML = '';
            for (const [file, desc] of Object.entries(plans)) {
                const li = document.createElement('li');
                li.className = 'plan-item' + (selectedPlan === file ? ' active' : '');
                li.dataset.file = file;
                const name = typeof desc === 'string' ? desc : file;
                const maxLen = 35;
                const displayName = name.length > maxLen ? name.slice(0, maxLen) + '…' : name;
                li.innerHTML = `<div class="plan-item-head"><span class="name" title="${escapeHtml(name)}">${escapeHtml(displayName)}</span><span class="badge pending">…</span></div><span class="file">${escapeHtml(file)}</span>`;
                li.querySelector('.badge').textContent = '…';
                li.addEventListener('click', () => selectPlan(file));
                planList.appendChild(li);
                (async function () {
                    try {
                        const result = await api('/testplans/' + encodeURIComponent(file) + '/validate');
                        const isValid = result && result.valid === true;
                        li.querySelector('.badge').className = 'badge ' + (isValid ? 'valid' : 'invalid');
                        li.querySelector('.badge').textContent = isValid ? 'Valid' : 'Invalid';
                    } catch {
                        li.querySelector('.badge').className = 'badge invalid';
                        li.querySelector('.badge').textContent = 'Invalid';
                    }
                })();
            }
        } catch (e) {
        }
        updateRunButtonState();
    }

    function escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    async function selectPlan(name) {
        selectedPlan = name;
        selectedStepIndex = null;
        planList.querySelectorAll('.plan-item').forEach(el => {
            el.classList.toggle('active', el.dataset.file === name);
        });
        try {
            currentPlanData = await api('/testplans/' + encodeURIComponent(name));
            currentRequests = currentPlanData.requests || [];
            renderChain();
            showDetailIntro();
        } catch (e) {
        }
        updateRunButtonState();
    }

    function renderChain() {
        emptyChain.style.display = currentRequests.length ? 'none' : 'block';
        chainContainer.querySelectorAll('.chain-step').forEach(el => el.remove());
        if (!currentRequests.length) return;
        currentRequests.forEach((req, i) => {
            const method = (req.method || 'GET').toUpperCase();
            const methodClass = getMethodClass(req.method);
            const name = req.description || req.name || req.id || 'Step ' + (i + 1);
            const url = req.url || '';
            const saves = req.save ? Object.entries(req.save).map(([k, v]) => `${k} ← ${v}`).join(', ') : '';
            const uses = (url.match(/\{\{(.*?)\}\}/g) || []).join(' ');
            const stepEl = document.createElement('div');
            stepEl.className = 'chain-step';
            stepEl.innerHTML = `
                <div class="chain-step-connector">
                    <div class="line line-top"></div>
                    <div class="dot"></div>
                    <div class="line line-bottom"></div>
                </div>
                <div class="chain-step-card ${selectedStepIndex === i ? 'selected' : ''}" data-index="${i}">
                    <div class="step-header">
                        <span class="method ${methodClass}">${escapeHtml(method)}</span>
                        <span class="step-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                        <button type="button" class="step-run-btn" data-step-index="${i}" title="Run this step (runs from start through this step)">Run</button>
                    </div>
                    <div class="step-url">${escapeHtml(url)}</div>
                    ${saves || uses ? `<div class="step-vars">${saves ? `<span class="saves">Saves: ${escapeHtml(saves)}</span>` : ''} ${uses ? `<span class="uses">Uses: ${escapeHtml(uses)}</span>` : ''}</div>` : ''}
                    <div class="step-status"></div>
                </div>
            `;
            const card = stepEl.querySelector('.chain-step-card');
            card.addEventListener('click', (e) => { if (!e.target.closest('.step-run-btn')) selectStep(i); });
            const runBtn = stepEl.querySelector('.step-run-btn');
            runBtn.addEventListener('click', (e) => { e.stopPropagation(); runStep(i); });
            chainContainer.appendChild(stepEl);
        });
    }

    async function runStep(stepIndex) {
        if (!selectedPlan) return;
        const card = getStepCard(stepIndex);
        if (!card) return;
        const runBtn = card.querySelector('.step-run-btn');
        if (runBtn) runBtn.disabled = true;
        
        // Clear previous results for all steps
        chainContainer.querySelectorAll('.chain-step-card').forEach(c => {
            c.classList.remove('step-running', 'step-pass', 'step-fail');
            c.querySelector('.step-status').textContent = '';
        });
        
        setStepRunning(stepIndex);
        detailContent.innerHTML = '<p class="meta">Running step ' + (stepIndex + 1) + '…</p>';
        try {
            const url = (API_BASE.replace(/\/$/, '') + '/testplans/' + encodeURIComponent(selectedPlan) + '/run/step/' + stepIndex).replace(/([^:]\/)\/+/g, '$1');
            const res = await fetch(url, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || res.statusText);
            }
            const data = await res.json();
            const result = data.result || data;
            const resultsSoFar = data.results_so_far || [result];
            const executedIndices = data.executed_step_indices || [stepIndex];
            
            // Highlight all steps that were actually executed using their step_index
            resultsSoFar.forEach((stepResult) => {
                const actualStepIndex = stepResult.step_index !== undefined ? stepResult.step_index : stepIndex;
                setStepResult(actualStepIndex, stepResult);
            });
            
            const name = result.name || currentRequests[stepIndex]?.description || currentRequests[stepIndex]?.name || currentRequests[stepIndex]?.id || 'Step ' + (stepIndex + 1);
            const fmt = (v) => v == null ? '' : (typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v));
            let html = '<h3>' + escapeHtml(name) + '</h3><p class="meta">Step ' + (stepIndex + 1) + ' result</p>';
            if (executedIndices.length > 1) {
                html += '<p class="meta" style="color: var(--accent); margin-top: 8px;">✓ Executed ' + executedIndices.length + ' step(s) including dependencies (steps: ' + executedIndices.map(i => i + 1).join(', ') + ')</p>';
            }
            html += '<div class="req-res-section"><h4 class="req-res-head">Request</h4>';
            html += '<p><strong>Method</strong> ' + escapeHtml(String(result.method || '').toUpperCase()) + '</p>';
            html += '<p><strong>URL</strong></p><pre>' + escapeHtml(result.url || '') + '</pre>';
            if (result.request_headers && Object.keys(result.request_headers).length) html += '<p><strong>Headers</strong></p><pre>' + escapeHtml(fmt(result.request_headers)) + '</pre>';
            if (result.request_body != null) html += '<p><strong>Body</strong></p><pre>' + escapeHtml(fmt(result.request_body)) + '</pre>';
            html += '</div>';
            html += '<div class="req-res-section"><h4 class="req-res-head">Response</h4>';
            html += '<p><strong>Status</strong> ' + escapeHtml(String(result.status || '')) + ' &nbsp; <strong>Code</strong> ' + escapeHtml(String(result.response_code ?? '')) + '</p>';
            if (result.error) html += '<p class="error"><strong>Error</strong> ' + escapeHtml(result.error) + '</p>';
            if (result.response_headers && Object.keys(result.response_headers).length) html += '<p><strong>Headers</strong></p><pre>' + escapeHtml(fmt(result.response_headers)) + '</pre>';
            if (result.response_sample != null) html += '<p><strong>Body</strong></p><pre>' + escapeHtml(fmt(result.response_sample)) + '</pre>';
            html += '</div>';
            detailContent.innerHTML = html;
        } catch (e) {
            setStepResult(stepIndex, { status: 'FAIL', error: e.message });
            detailContent.innerHTML = '<p class="meta">Step failed.</p><p class="error">' + escapeHtml(e.message) + '</p>';
        }
        if (runBtn) runBtn.disabled = false;
    }

    function selectStep(i) {
        selectedStepIndex = i;
        renderChain();
        const req = currentRequests[i];
        if (!req) return;
        const name = req.description || req.name || req.id || 'Step ' + (i + 1);
        detailContent.innerHTML = `
            <h3>${escapeHtml(name)}</h3>
            <div class="meta">${escapeHtml((req.method || 'GET').toUpperCase())} — Step ${i + 1} of ${currentRequests.length}</div>
            <p><strong>URL</strong></p>
            <pre>${escapeHtml(req.url || '')}</pre>
            <p><strong>Headers</strong></p>
            <pre>${escapeHtml(JSON.stringify(req.headers || {}, null, 2))}</pre>
            <p><strong>Body</strong></p>
            <pre>${escapeHtml(typeof req.body === 'object' ? JSON.stringify(req.body, null, 2) : (req.body || '(none)'))}</pre>
            ${req.save ? `<p><strong>Saves (chaining)</strong></p><pre>${escapeHtml(JSON.stringify(req.save, null, 2))}</pre>` : ''}
            ${req.validate ? `<p><strong>Validate</strong></p><pre>${escapeHtml(JSON.stringify(req.validate, null, 2))}</pre>` : ''}
        `;
    }

    function showDetailIntro() {
        detailContent.innerHTML = '<p class="meta">Select a request in the chain to preview, or click <strong>Run chain</strong> to execute all requests in order.</p>';
    }

    function getStepCard(i) {
        return chainContainer.querySelector('.chain-step-card[data-index="' + i + '"]');
    }

    function setStepRunning(i) {
        const card = getStepCard(i);
        if (!card) return;
        card.classList.remove('step-pass', 'step-fail');
        card.classList.add('step-running');
        card.querySelector('.step-status').textContent = 'Running…';
    }

    function setStepResult(i, result) {
        const card = getStepCard(i);
        if (!card) return;
        card.classList.remove('step-running');
        const status = (result.status || '').toUpperCase();
        const isPass = status === 'PASS';
        card.classList.add(isPass ? 'step-pass' : 'step-fail');
        const code = result.response_code != null ? result.response_code : '';
        const msg = result.error ? result.error : (code ? code + ' OK' : (isPass ? 'OK' : 'FAIL'));
        card.querySelector('.step-status').textContent = msg;
    }

    async function runChain() {
        if (!selectedPlan) return;
        detailContent.innerHTML = '<p class="meta">Executing request chain…</p>';
        chainContainer.querySelectorAll('.chain-step-card').forEach(c => {
            c.classList.remove('step-running', 'step-pass', 'step-fail');
            c.querySelector('.step-status').textContent = '';
        });
        const streamUrl = (API_BASE.replace(/\/$/, '') + '/testplans/' + encodeURIComponent(selectedPlan) + '/run/stream').replace(/([^:]\/)\/+/g, '$1');
        try {
            const res = await fetch(streamUrl, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || res.statusText);
            }
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let lastReport = null;
            let htmlReportPath = null;
            let csvReportPath = null;
            if (currentRequests.length > 0) setStepRunning(0);
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop() || '';
                for (const part of parts) {
                    const line = part.split('\n').find(l => l.startsWith('data: '));
                    if (!line) continue;
                    let event;
                    try {
                        event = JSON.parse(line.slice(6));
                    } catch (_) { continue; }
                    if (event.type === 'step') {
                        const idx = event.index;
                        setStepResult(idx, event.result);
                        if (getStepCard(idx + 1)) setStepRunning(idx + 1);
                    } else if (event.type === 'done') {
                        lastReport = event.report;
                        htmlReportPath = event.html_report || null;
                        csvReportPath = event.csv_report || null;
                        if (lastReport) renderReport(lastReport, htmlReportPath, csvReportPath);
                        chainContainer.querySelectorAll('.chain-step-card.step-running').forEach(c => {
                            c.classList.remove('step-running');
                            c.querySelector('.step-status').textContent = '';
                        });
                    } else if (event.type === 'error') {
                        detailContent.innerHTML = '<p class="meta">Run failed.</p><p class="error">' + escapeHtml(event.detail || 'Unknown error') + '</p>';
                    }
                }
            }
            if (!lastReport) {
                detailContent.innerHTML = '<p class="meta">Run finished. No report received.</p>';
            }
        } catch (e) {
            detailContent.innerHTML = '<p class="meta">Run failed.</p><p class="error">' + escapeHtml(e.message) + '</p>';
            chainContainer.querySelectorAll('.chain-step-card').forEach(c => {
                c.classList.remove('step-running');
                c.querySelector('.step-status').textContent = '';
            });
        }
    }

    function renderReport(report, htmlReportPath, csvReportPath) {
        const r = report.results || [];
        const passed = report.passed ?? r.filter(x => x.status === 'PASS').length;
        const failed = report.failed ?? r.filter(x => x.status === 'FAIL').length;
        const time = report.execution_time_sec;
        let html = `
            <h3>Run report</h3>
            <div class="report-summary">
                <div class="report-stat"><span class="value">${r.length}</span><span class="label">Total</span></div>
                <div class="report-stat passed"><span class="value">${passed}</span><span class="label">Passed</span></div>
                <div class="report-stat failed"><span class="value">${failed}</span><span class="label">Failed</span></div>
                <div class="report-stat"><span class="value">${time != null ? time + 's' : '—'}</span><span class="label">Time</span></div>
            </div>
        `;
        r.forEach((row, i) => {
            const status = (row.status || '').toUpperCase();
            const isPass = status === 'PASS';
            html += `
                <div class="result-row ${isPass ? 'pass' : 'fail'}">
                    <span class="name">${escapeHtml(row.name || 'Step ' + (i + 1))}</span>
                    <span class="code">${escapeHtml((row.method || '') + ' ' + (row.url || ''))} → ${row.response_code ?? ''}</span>
                    ${row.error ? `<div class="error">${escapeHtml(row.error)}</div>` : ''}
                </div>
            `;
        });
        if (htmlReportPath || csvReportPath) {
            html += `<div class="report-actions">`;
            if (htmlReportPath) {
                const reportUrl = (API_BASE.replace(/\/$/, '') + htmlReportPath).replace(/([^:]\/)\/+/g, '$1');
                html += `<a href="${reportUrl}" target="_blank" class="report-btn report-btn-html"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> HTML Report</a>`;
            }
            if (csvReportPath) {
                const csvUrl = (API_BASE.replace(/\/$/, '') + csvReportPath).replace(/([^:]\/)\/+/g, '$1');
                html += `<a href="${csvUrl}" target="_blank" class="report-btn report-btn-csv"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> CSV Report</a>`;
            }
            html += `</div>`;
        }
        detailContent.innerHTML = html;
    }

    document.getElementById('btnRun').addEventListener('click', runChain);

    updateRunButtonState();
    loadPlans();
})();
