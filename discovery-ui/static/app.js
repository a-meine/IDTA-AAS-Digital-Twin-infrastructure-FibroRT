const API_SHELLS = "/api/shells";
const API_SERVERS = "/api/servers";

let allShells = [];
let allServers = [];

async function loadData() {
    try {
        const [shellsRes, serversRes] = await Promise.all([
            fetch(API_SHELLS),
            fetch(API_SERVERS),
        ]);
        allShells = await shellsRes.json();
        allServers = await serversRes.json();

        if (allShells.error) {
            document.getElementById("product-list").innerHTML =
                `<p class="empty-state">Error loading data: ${allShells.error}</p>`;
            return;
        }

        document.getElementById("shell-count").textContent = `${allShells.length} Products`;
        document.getElementById("server-count").textContent = `${allServers.length} Servers`;
        renderShells(allShells);
        renderServers(allServers);
    } catch (err) {
        document.getElementById("product-list").innerHTML =
            `<p class="empty-state">Failed to connect to discovery API.</p>`;
    }
}

function parseEp(ep) {
    const proto_info = ep.protocolInformation || {};
    const href = proto_info.href || "";
    if (href) {
        try {
            const url = new URL(href);
            return { host: url.hostname, port: parseInt(url.port) || 8081, protocol: proto_info.endpointProtocol || "https" };
        } catch {}
    }
    return { host: ep.host || "unknown", port: ep.port || 8081, protocol: ep.protocol || "https" };
}

function renderShells(shells) {
    const container = document.getElementById("product-list");
    const noResults = document.getElementById("no-results");

    if (!shells || shells.length === 0) {
        container.innerHTML = "";
        noResults.style.display = "block";
        return;
    }

    noResults.style.display = "none";
    container.innerHTML = shells.map(shell => {
        const ep = (shell.endpoints || [])[0] || {};
        const { host, port, protocol } = parseEp(ep);
        const webUiUrl = `${protocol}://${host}:8443`;
        const rawApiUrl = `${protocol}://${host}:${port}/shells/${encodeURIComponent(shell.id || "")}`;

        return `
            <div class="card">
                <h3>${escapeHtml(shell.idShort || shell.id || "Unnamed")}</h3>
                <p class="meta"><strong>ID:</strong> ${escapeHtml(shell.id || "N/A")}</p>
                <p class="meta"><strong>Server:</strong> ${escapeHtml(host)}:${port}</p>
                <div class="card-actions">
                    <a href="${webUiUrl}" target="_blank" rel="noopener" class="btn">View on Server</a>
                    <a href="${rawApiUrl}" target="_blank" rel="noopener" class="btn btn-secondary">Raw API</a>
                </div>
            </div>
        `;
    }).join("");
}

function renderServers(servers) {
    const container = document.getElementById("server-list");
    if (!servers || servers.length === 0) {
        container.innerHTML = `<p class="empty-state">No servers registered yet.</p>`;
        return;
    }

    container.innerHTML = servers.map(s => `
        <div class="card">
            <h3>${escapeHtml(s.ip)}</h3>
            <p class="meta">${s.shell_count} AAS registered</p>
            <p class="meta">${escapeHtml(s.protocol)}://${escapeHtml(s.ip)}:${s.port}</p>
            <div class="card-actions">
                <a href="https://${escapeHtml(s.ip)}:8443" target="_blank" rel="noopener" class="btn">Open Server UI</a>
            </div>
        </div>
    `).join("");
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// Search / filter
document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    if (!q) {
        renderShells(allShells);
        return;
    }
    const filtered = allShells.filter(s => {
        const idShort = (s.idShort || "").toLowerCase();
        const id = (s.id || "").toLowerCase();
        const endpoints = JSON.stringify(s.endpoints || []).toLowerCase();
        return idShort.includes(q) || id.includes(q) || endpoints.includes(q);
    });
    renderShells(filtered);
});

// Initial load + auto-refresh every 30s
loadData();
setInterval(loadData, 30000);
