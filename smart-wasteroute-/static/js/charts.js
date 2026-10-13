/* ==========================================================
   static/js/charts.js
   Tiny dependency-free SVG charts for the compact History cards:
   bar chart, line chart (with markers) and a timeline. Each function returns
   an SVG/HTML string sized by a viewBox, so the same chart can be rendered
   in a small card and again, larger, in the expand modal.
   ========================================================== */

const Charts = (() => {
    const W = 420, H = 260, PAD = { l: 44, r: 12, t: 14, b: 44 };

    function niceMax(v) {
        if (v <= 0) return 1;
        const p = Math.pow(10, Math.floor(Math.log10(v)));
        const n = v / p;
        return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
    }

    function axes(max, unit) {
        const ticks = 4;
        let out = "";
        for (let i = 0; i <= ticks; i++) {
            const y = PAD.t + (H - PAD.t - PAD.b) * (1 - i / ticks);
            const val = (max * i / ticks);
            out += `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y}" y2="${y}" stroke="#263248" stroke-width="1"/>
                    <text x="${PAD.l - 6}" y="${y + 3}" text-anchor="end">${+val.toFixed(1)}</text>`;
        }
        return `<g class="chart-axis">${out}<text x="4" y="10">${escapeHtml(unit || "")}</text></g>`;
    }

    function xLabel(x, text, anchorEvery) {
        const t = String(text);
        const short = t.length > 9 ? t.slice(0, 8) + "…" : t;
        return `<text class="chart-axis" x="${x}" y="${H - PAD.b + 14}" text-anchor="middle" style="fill:#94a3b8;font-size:10px">${escapeHtml(short)}<title>${escapeHtml(t)}</title></text>`;
    }

    function empty(msg) { return `<div class="chart-empty">${escapeHtml(msg || "No data yet")}</div>`; }

    function bar({ labels, values, color = "#3b82f6", unit = "" }) {
        if (!values.length) return empty();
        const max = niceMax(Math.max(...values));
        const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;
        const slot = plotW / values.length, bw = Math.min(40, slot * 0.6);
        let bars = "";
        values.forEach((v, i) => {
            const h = plotH * v / max, x = PAD.l + slot * i + (slot - bw) / 2, y = PAD.t + plotH - h;
            bars += `<rect x="${x}" y="${y}" width="${bw}" height="${h}" rx="3" fill="${color}"><title>${escapeHtml(labels[i])}: ${+v.toFixed(2)} ${escapeHtml(unit)}</title></rect>
                     <text x="${x + bw / 2}" y="${y - 3}" text-anchor="middle" style="fill:#e5e9f0;font-size:10px">${+v.toFixed(1)}</text>
                     ${xLabel(x + bw / 2, labels[i])}`;
        });
        return `<svg viewBox="0 0 ${W} ${H}">${axes(max, unit)}${bars}</svg>`;
    }

    function line({ labels, values, color = "#22d3ee", unit = "", step = false }) {
        if (!values.length) return empty();
        const max = niceMax(Math.max(...values));
        const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;
        const n = values.length, slot = n > 1 ? plotW / (n - 1) : 0;
        const pts = values.map((v, i) => [PAD.l + (n > 1 ? slot * i : plotW / 2), PAD.t + plotH * (1 - v / max)]);
        let d = "";
        pts.forEach((p, i) => { d += i === 0 ? `M${p[0]},${p[1]}` : (step ? `L${p[0]},${pts[i - 1][1]} L${p[0]},${p[1]}` : ` L${p[0]},${p[1]}`); });
        const dots = pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${color}"><title>${escapeHtml(labels[i])}: ${+values[i].toFixed(2)} ${escapeHtml(unit)}</title></circle>${xLabel(p[0], labels[i])}`).join("");
        return `<svg viewBox="0 0 ${W} ${H}">${axes(max, unit)}<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5"/>${dots}</svg>`;
    }

    /* items: [{label, time(ISO or null), sub}] in collection order */
    function timeline(items) {
        if (!items.length) return empty("No bins collected yet");
        return `<div style="height:100%;overflow-y:auto;padding:.3rem .2rem">${items.map((it, i) => `
            <div style="display:flex;gap:.6rem;align-items:flex-start;margin-bottom:.45rem">
                <div style="display:flex;flex-direction:column;align-items:center">
                    <div style="width:22px;height:22px;border-radius:50%;background:${it.color || "#3b82f6"};color:#0b1120;font-weight:700;font-size:.72rem;display:flex;align-items:center;justify-content:center">${i + 1}</div>
                    ${i < items.length - 1 ? '<div style="width:2px;height:16px;background:#263248"></div>' : ""}
                </div>
                <div style="font-size:.82rem"><strong>${escapeHtml(it.label)}</strong> <span style="color:#94a3b8">${escapeHtml(it.time || "")}</span><br>
                <span style="color:#94a3b8">${escapeHtml(it.sub || "")}</span></div>
            </div>`).join("")}</div>`;
    }

    return { bar, line, timeline };
})();
