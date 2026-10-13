/* ==========================================================
   static/js/data_structures.js
   Populates every "Live Data" panel on the Data Structures
   page from /api/data-structures/live, plus a Dijkstra demo
   tool wired to the existing /api/routes/shortest-path endpoint.
   ========================================================== */

document.addEventListener("DOMContentLoaded", () => {
    loadLiveSnapshot();
    document.getElementById("btn-refresh-ds").addEventListener("click", loadLiveSnapshot);
    document.getElementById("btn-run-dijkstra").addEventListener("click", runDijkstra);
});

async function loadLiveSnapshot() {
    try {
        const res = await fetch("/api/data-structures/live");
        const body = await res.json();
        if (!body.success) throw new Error(body.error);

        renderGraph(body.data.graph);
        renderQueueAndPriorityQueue(body.data.queue_and_priority_queue);
        renderStack(body.data.stack);
        renderHashTable(body.data.hash_table);
        renderListArray(body.data.list_array);

        populateDijkstraDropdowns(body.data.graph);
    } catch (err) {
        console.error("Failed to load live data structures snapshot:", err);
    }
}

function priorityBadgeClass(priority) {
    return {
        LOW: "badge-low", MEDIUM: "badge-medium", HIGH: "badge-high", CRITICAL: "badge-critical",
    }[priority] || "badge-low";
}

function renderGraph(graph) {
    const el = document.getElementById("graph-live");
    if (!graph.available) {
        el.innerHTML = `<p class="empty-row">${escapeHtml(graph.reason)}</p>`;
        return;
    }

    const vertices = Object.keys(graph.adjacency_list);
    if (vertices.length === 0) {
        el.innerHTML = `<p class="empty-row">No locations yet.</p>`;
        return;
    }

    el.innerHTML = `
        <p class="ds-meta">
            ${graph.vertex_count} vertices &middot; ${graph.edge_count} edges &middot;
            ${graph.is_connected ? "connected" : "NOT connected"}
        </p>
        <ul class="adjacency-list">
            ${vertices.map(v => `
                <li>
                    <strong>${escapeHtml(v)}</strong>
                    <ul>
                        ${graph.adjacency_list[v].map(edge =>
                            `<li>&rarr; ${escapeHtml(edge.neighbor)} : ${edge.distance_km} km</li>`
                        ).join("")}
                    </ul>
                </li>
            `).join("")}
        </ul>
    `;
}

function renderQueueAndPriorityQueue(data) {
    const queueEl = document.getElementById("queue-live");
    const pqEl = document.getElementById("priority-queue-live");

    if (data.queue_arrival_order.length === 0) {
        queueEl.innerHTML = `<p class="empty-row">No pending requests.</p>`;
        pqEl.innerHTML = `<p class="empty-row">No pending requests.</p>`;
        return;
    }

    queueEl.innerHTML = `
        <ol class="ds-ordered-list">
            ${data.queue_arrival_order.map(item => `<li>${escapeHtml(item.bin_id)}</li>`).join("")}
        </ol>
    `;

    pqEl.innerHTML = `
        <ol class="ds-ordered-list">
            ${data.priority_queue_urgency_order.map(item =>
                `<li>${escapeHtml(item.bin_id)} <span class="ds-meta">(weight ${item.priority_weight})</span></li>`
            ).join("")}
        </ol>
        ${data.skipped_stale_requests.length > 0
            ? `<p class="stale-note">Skipped stale requests: ${data.skipped_stale_requests.map(escapeHtml).join(", ")}</p>`
            : ""}
    `;
}

function renderStack(stack) {
    const el = document.getElementById("stack-live");
    if (!stack.available) {
        el.innerHTML = `<p class="empty-row">${escapeHtml(stack.reason)}</p>`;
        return;
    }

    el.innerHTML = `
        <p class="ds-meta">From vehicle ${escapeHtml(stack.vehicle_id)}'s most recent route</p>
        <p><strong>Push order (bottom &rarr; top):</strong> ${stack.push_order.map(escapeHtml).join(" &rarr; ")}</p>
        <p><strong>peek() right now:</strong> ${escapeHtml(stack.peek_top)}</p>
        <p><strong>Most-recent-first view:</strong> ${stack.most_recent_first.map(escapeHtml).join(" &rarr; ")}</p>
    `;
}

function renderHashTable(ht) {
    const el = document.getElementById("hash-table-live");
    if (ht.rows.length === 0) {
        el.innerHTML = `<p class="empty-row">No active bins yet.</p>`;
        return;
    }

    el.innerHTML = `
        <p class="ds-meta">${ht.bucket_count} buckets &middot; ${ht.item_count} items stored</p>
        <table class="data-table">
            <thead><tr><th>Key</th><th>Hash</th><th>Stored Value</th></tr></thead>
            <tbody>
                ${ht.rows.map(row => `
                    <tr>
                        <td><code>${escapeHtml(row.key)}</code></td>
                        <td>${row.hash}${row.collision ? ' <span class="badge badge-medium">collision bucket</span>' : ""}</td>
                        <td>${escapeHtml(row.value)}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;
}

function renderListArray(la) {
    const el = document.getElementById("list-array-live");
    el.innerHTML = `
        <p><strong>Bins list</strong> (${la.bins_count} items): ${la.bin_ids.map(escapeHtml).join(", ") || "<em>empty</em>"}</p>
        <p><strong>Vehicles list</strong> (${la.vehicles_count} items): ${la.vehicle_ids.map(escapeHtml).join(", ") || "<em>empty</em>"}</p>
    `;
}

function populateDijkstraDropdowns(graph) {
    const startSelect = document.getElementById("dijkstra-start");
    const destSelect = document.getElementById("dijkstra-destination");

    if (!graph.available) {
        startSelect.innerHTML = `<option value="">No graph available</option>`;
        destSelect.innerHTML = `<option value="">No graph available</option>`;
        return;
    }

    const vertices = Object.keys(graph.adjacency_list);
    const options = vertices.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("");
    startSelect.innerHTML = options;
    destSelect.innerHTML = options;
    if (vertices.length > 1) {
        destSelect.selectedIndex = 1; // default to a different vertex than start, for a more interesting first demo
    }
}

async function runDijkstra() {
    const start = document.getElementById("dijkstra-start").value;
    const destination = document.getElementById("dijkstra-destination").value;
    const resultEl = document.getElementById("dijkstra-result");

    if (!start || !destination) {
        alert("Choose both a start and a destination.");
        return;
    }

    resultEl.classList.remove("hidden");
    resultEl.textContent = "Running Dijkstra...";

    try {
        const res = await fetch("/api/routes/shortest-path", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start, destination }),
        });
        const body = await res.json();
        if (!body.success) throw new Error(body.error);

        const data = body.data;
        if (!data.reachable) {
            resultEl.innerHTML = `<strong>${escapeHtml(start)} &rarr; ${escapeHtml(destination)}</strong>: not reachable.`;
            return;
        }

        resultEl.innerHTML = `
            <strong>Shortest Distance:</strong> ${data.distance} km<br>
            <strong>Path:</strong> ${data.path.map(escapeHtml).join(" &rarr; ")}<br>
            <strong>Visited Nodes (in order):</strong> ${data.visited_nodes.map(escapeHtml).join(", ")}
        `;
    } catch (err) {
        resultEl.textContent = "Error: " + err.message;
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
