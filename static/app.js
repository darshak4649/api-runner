const API_BASE = "http://127.0.0.1:8000";

/* ===========================
   LOAD TESTPLANS
=========================== */

async function loadTestplans() {
  try {
    const res = await fetch(API_BASE + "/testplans");
    const data = await res.json();

    const select = document.getElementById("testplanSelect");
    select.innerHTML = '<option value="">-- Select Testplan --</option>';

    data.available_testplans.forEach(tp => {
      const opt = document.createElement("option");
      opt.value = tp;
      opt.innerText = tp;
      select.appendChild(opt);
    });

  } catch (err) {
    document.getElementById("previewArea").innerHTML =
      `<pre>Error loading testplans: ${err.message}</pre>`;
  }
}

/* ===========================
   UTILITIES
=========================== */

function extractVars(obj) {
  const text = JSON.stringify(obj);
  const matches = text.match(/\{\{(.*?)\}\}/g) || [];
  return matches.map(v => v.replace(/[{}]/g, ""));
}

function methodBadge(method) {
  if (method?.toUpperCase() === "GET") {
    return `<span class="badge get-badge">GET</span>`;
  }
  if (method?.toUpperCase() === "POST") {
    return `<span class="badge post-badge">POST</span>`;
  }
  return `<span class="badge">${method}</span>`;
}

/* ===========================
   STATUS HANDLING
=========================== */

function markCardStatus(index, status) {
  const badge = document.getElementById(`status-${index}`);
  if (!badge) return;

  badge.className = "status-badge";

  if (status === "RUNNING") {
    badge.innerText = "⏳ RUNNING";
    badge.classList.add("status-running");
  } else if (status === "PASS") {
    badge.innerText = "🟢 PASS";
    badge.classList.add("status-pass");
  } else if (status === "FAIL") {
    badge.innerText = "🔴 FAIL";
    badge.classList.add("status-fail");
  } else {
    badge.innerText = "⏸ PENDING";
    badge.classList.add("status-pending");
  }
}

/* ===========================
   RENDER CARD WITH STATUS
=========================== */

function renderCardWithStatus(req, idx) {
  const used = extractVars(req);
  const produced = req.save ? Object.keys(req.save) : [];

  let html = `
    <div class="req-card" id="card-${idx}">
      <div class="req-header">
        ${methodBadge(req.method)}
        ${req.name || "Unnamed Request"}
        <span class="status-badge status-pending" id="status-${idx}">
          ⏸ PENDING
        </span>
      </div>

      <div style="font-size:12px; color:#424242; margin-bottom:4px;">
        ${req.url}
      </div>
  `;

  if (used.length > 0) {
    html += `
      <div class="var-line uses">
        🔹 Uses: ${used.join(", ")}
      </div>
    `;
  }

  if (produced.length > 0) {
    html += `
      <div class="var-line produces">
        ✅ Produces: ${produced.join(", ")}
      </div>
    `;
  }

  html += `</div>`;
  return html;
}

/* ===========================
   VALIDATE + PREVIEW (SEQUENTIAL)
=========================== */

async function validateTestplan() {
  const tp = document.getElementById("testplanSelect").value;
  if (!tp) {
    alert("Select a testplan first");
    return;
  }

  try {
    const planRes = await fetch(API_BASE + "/testplans/" + tp);
    const plan = await planRes.json();

    const valRes = await fetch(`${API_BASE}/testplans/${tp}/validate`);
    const valData = await valRes.json();

    let chainHtml = `
      <b>Validation Result:</b>
      <pre>${JSON.stringify(valData, null, 2)}</pre>

      <div class="title" style="margin-top:16px;">
        Execution Chain Preview (Sequential)
      </div>

      <div class="chain-wrapper">
        <div class="chain-row">
    `;

    plan.requests.forEach((req, idx) => {
      chainHtml += renderCardWithStatus(req, idx);

      if (idx < plan.requests.length - 1) {
        chainHtml += `<div class="chain-arrow">→</div>`;
      }
    });

    chainHtml += `
        </div>
      </div>
    `;

    document.getElementById("previewArea").innerHTML = chainHtml;

  } catch (err) {
    document.getElementById("previewArea").innerHTML =
      `<pre>Validation error: ${err.message}</pre>`;
  }
}

/* ===========================
   RUN TESTPLAN (WITH STATUS UPDATES)
=========================== */

async function runTestplan() {
  const tp = document.getElementById("testplanSelect").value;
  if (!tp) {
    alert("Select a testplan first");
    return;
  }

  try {
    // 1) Fetch plan to render cards first
    const planRes = await fetch(API_BASE + "/testplans/" + tp);
    const plan = await planRes.json();

    // 2) Render chain with PENDING statuses
    let chainHtml = `
      <div class="title" style="margin-top:16px;">
        Executing Testplan...
      </div>

      <div class="chain-wrapper">
        <div class="chain-row">
    `;

    plan.requests.forEach((req, idx) => {
      chainHtml += renderCardWithStatus(req, idx);
      if (idx < plan.requests.length - 1) {
        chainHtml += `<div class="chain-arrow">→</div>`;
      }
    });

    chainHtml += `
        </div>
      </div>
    `;

    document.getElementById("previewArea").innerHTML = chainHtml;

    // 3) Actually call backend to run testplan
    const res = await fetch(`${API_BASE}/testplans/${tp}/run`, {
      method: "POST"
    });

    const data = await res.json();

    // 4) Update card statuses based on report
    data.results.forEach((r, idx) => {
      markCardStatus(idx, r.status);
    });

    // 5) Show report links
    const reportCard = document.getElementById("reportCard");
    const links = document.getElementById("reportLinks");

    links.innerHTML = `
      <a href="${data.json_report}" target="_blank">
        📥 Download JSON Report
      </a>
      |
      <a href="${data.html_report}" target="_blank">
        🌐 Open HTML Report
      </a>
    `;

    reportCard.style.display = "block";

  } catch (err) {
    document.getElementById("previewArea").innerHTML =
      `<pre>Error: ${err.message}</pre>`;
  }
}

/* Auto-load on page open */
loadTestplans();
