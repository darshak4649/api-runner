let currentTable = null;
let currentOffset = 0;
let limit = 100;

async function testConnection() {
    try {
        const response = await fetch('/api/db/test');
        const data = await response.json();
        
        const indicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        const schemaInfo = document.getElementById('schemaInfo');
        
        if (data.status === 'success') {
            indicator.classList.add('connected');
            statusText.textContent = 'Connected';
            if (data.schema) {
                schemaInfo.textContent = `Schema: ${data.schema}`;
            }
        } else {
            statusText.textContent = 'Connection failed';
            showError(data.message);
        }
    } catch (error) {
        document.getElementById('statusText').textContent = 'Connection error';
        showError(error.message);
    }
}

async function loadTables() {
    try {
        const response = await fetch('/api/db/tables');
        const data = await response.json();
        
        const tableList = document.getElementById('tableList');
        tableList.innerHTML = '';
        
        if (data.tables.length === 0) {
            tableList.innerHTML = '<li class="loading">No tables found</li>';
            return;
        }
        
        data.tables.forEach(table => {
            const li = document.createElement('li');
            li.className = 'table-item';
            li.textContent = table;
            li.onclick = () => loadTableData(table);
            tableList.appendChild(li);
        });
    } catch (error) {
        showError('Failed to load tables: ' + error.message);
    }
}

async function loadTableData(tableName, offset = 0) {
    currentTable = tableName;
    currentOffset = offset;
    
    // Update active state
    document.querySelectorAll('.table-item').forEach(item => {
        item.classList.remove('active');
        if (item.textContent === tableName) {
            item.classList.add('active');
        }
    });
    
    const content = document.getElementById('tableContent');
    content.innerHTML = '<div class="loading">Loading data...</div>';
    
    try {
        const response = await fetch(`/api/db/tables/${tableName}/data?limit=${limit}&offset=${offset}`);
        const data = await response.json();
        
        renderTableData(data);
    } catch (error) {
        showError('Failed to load table data: ' + error.message);
    }
}

function renderTableData(data) {
    const content = document.getElementById('tableContent');
    
    if (data.rows.length === 0) {
        content.innerHTML = `
            <div class="table-header">
                <h2>${data.schema}.${data.table_name}</h2>
                <div class="table-info">No data found</div>
            </div>
        `;
        return;
    }
    
    const columns = Object.keys(data.rows[0]);
    
    let html = `
        <div class="table-header">
            <h2>${data.schema}.${data.table_name}</h2>
            <div class="table-info">Total rows: ${data.total_count}</div>
        </div>
        <div class="table-wrapper">
            <table class="data-table">
                <thead>
                    <tr>
                        ${columns.map(col => `<th>${col}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${data.rows.map(row => `
                        <tr>
                            ${columns.map(col => `<td title="${escapeHtml(formatValue(row[col]))}">${formatValue(row[col])}</td>`).join('')}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        <div class="pagination">
            <button onclick="loadTableData('${data.table_name}', ${Math.max(0, currentOffset - limit)})" 
                    ${currentOffset === 0 ? 'disabled' : ''}>
                Previous
            </button>
            <span>Showing ${currentOffset + 1} - ${Math.min(currentOffset + limit, data.total_count)} of ${data.total_count}</span>
            <div class="page-size-selector">
                <label>Rows per page:</label>
                <select onchange="changePageSize(this.value)">
                    <option value="50" ${limit === 50 ? 'selected' : ''}>50</option>
                    <option value="100" ${limit === 100 ? 'selected' : ''}>100</option>
                    <option value="200" ${limit === 200 ? 'selected' : ''}>200</option>
                    <option value="500" ${limit === 500 ? 'selected' : ''}>500</option>
                    <option value="1000" ${limit === 1000 ? 'selected' : ''}>1000</option>
                </select>
            </div>
            <button onclick="loadTableData('${data.table_name}', ${currentOffset + limit})" 
                    ${currentOffset + limit >= data.total_count ? 'disabled' : ''}>
                Next
            </button>
        </div>
        <div class="query-section">
            <h3>Custom Query</h3>
            <textarea class="query-input" id="customQuery" placeholder="SELECT * FROM vehicle_management.${data.table_name} WHERE ..."></textarea>
            <button class="query-button" onclick="executeCustomQuery()">Execute Query</button>
        </div>
    `;
    
    content.innerHTML = html;
}

function formatValue(value) {
    if (value === null) return '<em>NULL</em>';
    if (typeof value === 'object') return JSON.stringify(value);
    return value;
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

function changePageSize(newLimit) {
    limit = parseInt(newLimit);
    currentOffset = 0;
    if (currentTable) {
        loadTableData(currentTable, 0);
    }
}

async function executeCustomQuery() {
    const query = document.getElementById('customQuery').value;
    if (!query.trim()) {
        alert('Please enter a query');
        return;
    }
    
    try {
        const response = await fetch('/api/db/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql: query })
        });
        
        const data = await response.json();
        
        if (data.status === 'error') {
            showError(data.message);
            return;
        }
        
        renderQueryResults(data);
    } catch (error) {
        showError('Query execution failed: ' + error.message);
    }
}

function renderQueryResults(data) {
    if (data.rows.length === 0) {
        showError('Query returned no results');
        return;
    }
    
    const columns = Object.keys(data.rows[0]);
    const content = document.getElementById('tableContent');
    
    let html = `
        <div class="table-header">
            <h2>Query Results</h2>
            <div class="table-info">${data.count} rows</div>
        </div>
        <div class="table-wrapper">
            <table class="data-table">
                <thead>
                    <tr>
                        ${columns.map(col => `<th>${col}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${data.rows.map(row => `
                        <tr>
                            ${columns.map(col => `<td title="${escapeHtml(formatValue(row[col]))}">${formatValue(row[col])}</td>`).join('')}
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
    
    content.innerHTML = html;
}

function showError(message) {
    const errorDiv = document.getElementById('errorMessage');
    errorDiv.innerHTML = `<div class="error">${message}</div>`;
    setTimeout(() => {
        errorDiv.innerHTML = '';
    }, 5000);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    testConnection();
    loadTables();
});
