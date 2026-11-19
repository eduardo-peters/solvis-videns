// Desenho dos gráficos do agente local (SVG puro, sem bibliotecas).
// Recebe a especificação de agent/charts.py. hide=true esconde números (rótulos, eixos e dicas).
(function () {
  const F = 'font:11px ui-monospace,SFMono-Regular,Menlo,monospace';
  const C = { text: '#e6edf3', muted: '#8b97a6', grid: '#21262d', axis: '#30363d', blue: '#58a6ff',
              green: '#3fb950', red: '#f85149', yellow: '#d29922', purple: '#bc8cff', orange: '#ff7b2e' };
  const PALETTE = ['#58a6ff', '#3fb950', '#d29922', '#bc8cff', '#f85149', '#39c5cf', '#ff7b2e', '#8b949e',
                   '#db61a2', '#a5d6ff', '#7ee787', '#e3b341'];
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = (v, u) => v == null ? '—' : (Number.isInteger(v) ? v.toLocaleString('pt-BR') : v.toLocaleString('pt-BR', { maximumFractionDigits: 2 })) + (u || '');
  const svg = (w, h, body) => `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="${F};display:block;margin:8px 0 2px">${body}</svg>`;
  const T = (x, y, s, o = {}) => `<text x="${x}" y="${y}" fill="${o.fill || C.muted}" ${o.anchor ? `text-anchor="${o.anchor}"` : ''} ${o.size ? `font-size="${o.size}"` : ''} ${o.weight ? `font-weight="${o.weight}"` : ''}>${esc(s)}</text>`;
  const tip = (label, v, u, hide, n) => `<title>${esc(label)}${hide ? '' : ' · ' + fmt(v, u)}${!hide && n != null ? ' · n ' + fmt(n) : ''}</title>`;
  const title = c => T(4, 15, c.title, { fill: C.text, size: 13, weight: 600 });
  const footer = (c, y) => (c.notes || []).map((n, i) => T(4, y + i * 14, '• ' + n)).join('');
  const nice = (lo, hi) => { if (lo === hi) { hi = lo + 1; } const span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / 4)));
    const s = [1, 2, 2.5, 5, 10].map(k => k * step).find(k => span / k <= 5) || step * 10;
    return { lo: Math.floor(lo / s) * s, hi: Math.ceil(hi / s) * s, step: s }; };
  const legend = (items, x, y) => { let off = 0; return items.map(([name, color]) => { const s = `<rect x="${x + off}" y="${y - 9}" width="10" height="10" rx="2" fill="${color}"/>` + T(x + off + 14, y, name); off += 14 + String(name).length * 6.8 + 18; return s; }).join(''); };

  function yAxis(x0, x1, y0, y1, sc, hide, unit) {
    let s = '';
    for (let v = sc.lo; v <= sc.hi + 1e-9; v += sc.step) {
      const y = y1 - (v - sc.lo) / (sc.hi - sc.lo) * (y1 - y0);
      s += `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="${v === 0 ? C.axis : C.grid}"/>`;
      if (!hide) s += T(x0 - 6, y + 4, fmt(+v.toFixed(2), unit), { anchor: 'end' });
    }
    return s;
  }

  function columns(c, hide, opt = {}) {
    const vals = c.series[0].values, n = vals.length, W = Math.max(520, 70 + n * 42), H = 300, L = 54, R = 16, top = 34, B = 64;
    const lo = Math.min(0, ...vals.filter(v => v != null)), hi = Math.max(...vals.filter(v => v != null), 0);
    const sc = c.domain ? { lo: c.domain[0], hi: c.domain[1], step: (c.domain[1] - c.domain[0]) / 4 } : nice(lo, hi);
    const Y = v => H - B - (v - sc.lo) / (sc.hi - sc.lo) * (H - B - top), bw = (W - L - R) / n;
    let s = title(c) + yAxis(L, W - R, top, H - B, sc, hide, c.unit);
    vals.forEach((v, i) => {
      if (v == null) return;
      const x = L + i * bw + bw * 0.15, y = Math.min(Y(v), Y(0)), h = Math.abs(Y(v) - Y(0));
      const color = (c.colors && c.colors[i]) || (v < 0 ? C.red : (opt.color || C.blue));
      const small = c.n && c.n[i] < 30;
      s += `<rect x="${x}" y="${y}" width="${bw * 0.7}" height="${Math.max(h, 1)}" rx="3" fill="${color}" opacity="${small ? 0.45 : 1}">${tip(c.labels[i], v, c.unit, hide, c.n && c.n[i])}</rect>`;
      if (!hide && n <= 24) s += T(x + bw * 0.35, (v < 0 ? y + h + 12 : y - 4), fmt(v, c.unit), { anchor: 'middle', fill: C.text });
      const lab = String(c.labels[i]);
      s += `<text x="${x + bw * 0.35}" y="${H - B + 14}" fill="${C.muted}" text-anchor="end" transform="rotate(-35 ${x + bw * 0.35} ${H - B + 14})">${esc(lab.length > 18 ? lab.slice(0, 17) + '…' : lab)}</text>`;
    });
    if (c.legend) s += legend(Object.entries(c.legend), L, H - 4);
    const notes = footer(c, H + 14);
    return svg(W, H + (c.notes || []).length * 14 + 8, s + notes);
  }

  function hbars(c, hide) {
    const vals = c.series[0].values, n = vals.length, rowH = 24, L = 250, W = 760, top = 34, H = top + n * rowH + 10;
    const lo = c.domain ? c.domain[0] : Math.min(0, ...vals), hi = c.domain ? c.domain[1] : Math.max(...vals, 0);
    const X = v => L + (v - lo) / ((hi - lo) || 1) * (W - L - 70);
    let s = title(c);
    vals.forEach((v, i) => {
      const y = top + i * rowH, small = c.n && c.n[i] < 30, x0 = X(Math.max(lo, Math.min(0, hi)));
      s += T(L - 8, y + 15, String(c.labels[i]).slice(0, 38), { anchor: 'end', fill: '#c9d3dd' });
      s += `<rect x="${L}" y="${y + 4}" width="${W - L - 70}" height="${rowH - 8}" rx="3" fill="${C.grid}"/>`;
      s += `<rect x="${Math.min(X(v), x0)}" y="${y + 4}" width="${Math.max(Math.abs(X(v) - x0), 2)}" height="${rowH - 8}" rx="3" fill="${v < 0 ? C.red : C.green}" opacity="${small ? 0.45 : 1}">${tip(c.labels[i], v, c.unit, hide, c.n && c.n[i])}</rect>`;
      if (!hide) s += T(W - 62, y + 15, fmt(v, c.unit) + (c.n ? '  n ' + fmt(c.n[i]) : ''), { fill: C.text });
    });
    return svg(W, H + (c.notes || []).length * 14 + 8, s + footer(c, H + 6));
  }

  function lines(c, hide, area) {
    const vals = c.series[0].values, n = vals.length, W = 720, H = 280, L = 54, R = 20, top = 34, B = 40;
    const real = vals.filter(v => v != null), sc = nice(Math.min(...real, area ? 0 : Infinity), Math.max(...real));
    const X = i => L + i * (W - L - R) / Math.max(n - 1, 1), Y = v => H - B - (v - sc.lo) / (sc.hi - sc.lo) * (H - B - top);
    let s = title(c) + yAxis(L, W - R, top, H - B, sc, hide, c.unit);
    const pts = vals.map((v, i) => v == null ? null : [X(i), Y(v)]).filter(Boolean);
    if (area && pts.length) s += `<path d="M${pts[0][0]},${Y(sc.lo)} ${pts.map(p => 'L' + p.join(',')).join(' ')} L${pts[pts.length - 1][0]},${Y(sc.lo)} Z" fill="${C.blue}" opacity="0.22"/>`;
    s += `<polyline fill="none" stroke="${C.blue}" stroke-width="2.2" stroke-linejoin="round" points="${pts.map(p => p.join(',')).join(' ')}"/>`;
    vals.forEach((v, i) => {
      if (v == null) return;
      const small = c.n && c.n[i] < 30;
      s += `<circle cx="${X(i)}" cy="${Y(v)}" r="${small ? 3 : 4}" fill="${small ? C.bg || '#0b0f14' : C.blue}" stroke="${C.blue}" stroke-width="1.5">${tip(c.labels[i], v, c.unit, hide, c.n && c.n[i])}</circle>`;
      if (n <= 24 || i % 2 === 0) s += T(X(i), H - B + 16, c.labels[i], { anchor: 'middle' });
    });
    s += T(L, H - 4, c.x_label || '');
    return svg(W, H + (c.notes || []).length * 14 + 8, s + footer(c, H + 12));
  }

  function combo(c, hide) {
    const bars = c.series[0].values, nps = c.series[1].values, n = bars.length, W = 760, H = 300, L = 58, R = 58, top = 40, B = 40;
    const sb = nice(0, Math.max(...bars)), real = nps.filter(v => v != null), sl = nice(Math.min(0, ...real), Math.max(100, ...real));
    const bw = (W - L - R) / n, Yb = v => H - B - v / sb.hi * (H - B - top), Yl = v => H - B - (v - sl.lo) / (sl.hi - sl.lo) * (H - B - top);
    let s = title(c) + yAxis(L, W - R, top, H - B, sb, hide, '');
    if (!hide) for (let v = sl.lo; v <= sl.hi; v += sl.step) s += T(W - R + 6, Yl(v) + 4, fmt(v), { fill: C.purple });
    bars.forEach((v, i) => { s += `<rect x="${L + i * bw + bw * 0.15}" y="${Yb(v)}" width="${bw * 0.7}" height="${H - B - Yb(v)}" rx="3" fill="${C.blue}" opacity="0.75">${tip(c.labels[i] + ' · avaliações', v, '', hide)}</rect>`;
      s += T(L + i * bw + bw / 2, H - B + 16, c.labels[i], { anchor: 'middle' }); });
    const pts = nps.map((v, i) => v == null ? null : [L + i * bw + bw / 2, Yl(v)]).filter(Boolean);
    s += `<polyline fill="none" stroke="${C.purple}" stroke-width="2.4" points="${pts.map(p => p.join(',')).join(' ')}"/>`;
    nps.forEach((v, i) => { if (v != null) s += `<circle cx="${L + i * bw + bw / 2}" cy="${Yl(v)}" r="4" fill="${C.purple}">${tip(c.labels[i] + ' · NPS', v, '', hide)}</circle>`; });
    s += legend([['avaliações (eixo esq.)', C.blue], ['NPS (eixo dir.)', C.purple]], L, 30);
    return svg(W, H + (c.notes || []).length * 14 + 8, s + footer(c, H + 12));
  }

  function stacked(c, hide) {
    const n = c.labels.length, rowH = 26, L = 230, W = 760, top = 46, H = top + n * rowH + 10, w = W - L - 20;
    let s = title(c) + legend(c.series.map(x => [x.name, x.color]), L, 32);
    c.labels.forEach((lab, i) => {
      const y = top + i * rowH; let x = L;
      s += T(L - 8, y + 16, String(lab).slice(0, 34) + (c.n && !hide ? '  n ' + fmt(c.n[i]) : ''), { anchor: 'end', fill: '#c9d3dd' });
      c.series.forEach(sr => { const v = sr.values[i], bw = v / 100 * w;
        s += `<rect x="${x}" y="${y + 4}" width="${Math.max(bw, 0)}" height="${rowH - 8}" fill="${sr.color}">${tip(lab + ' · ' + sr.name, v, '%', hide)}</rect>`;
        if (!hide && bw > 34) s += T(x + bw / 2, y + 17, fmt(v, '%'), { anchor: 'middle', fill: '#0b0f14', weight: 600 });
        x += bw; });
    });
    return svg(W, H + (c.notes || []).length * 14 + 8, s + footer(c, H + 6));
  }

  function donut(c, hide) {
    const W = 560, H = 260, cx = 130, cy = 140, r = 96, ri = 58, tot = c.values.reduce((a, b) => a + b, 0) || 1;
    let s = title(c), a0 = -Math.PI / 2;
    c.values.forEach((v, i) => {
      const a1 = a0 + v / tot * 2 * Math.PI, large = a1 - a0 > Math.PI ? 1 : 0, col = PALETTE[i % PALETTE.length];
      const p = (a, rr) => [cx + rr * Math.cos(a), cy + rr * Math.sin(a)];
      const [x0, y0] = p(a0, r), [x1, y1] = p(a1, r), [x2, y2] = p(a1, ri), [x3, y3] = p(a0, ri);
      if (v / tot > 0.9999) {  // fatia única: arco de 360° não desenha; usa um anel
        s += `<circle cx="${cx}" cy="${cy}" r="${(r + ri) / 2}" fill="none" stroke="${col}" stroke-width="${r - ri}">${tip(c.labels[i], v, c.unit, hide)}</circle>`;
      } else {
        s += `<path d="M${x0},${y0} A${r},${r} 0 ${large} 1 ${x1},${y1} L${x2},${y2} A${ri},${ri} 0 ${large} 0 ${x3},${y3} Z" fill="${col}" stroke="#0b0f14" stroke-width="2">${tip(c.labels[i], v, c.unit, hide)}</path>`;
      }
      s += `<rect x="270" y="${48 + i * 22}" width="12" height="12" rx="2" fill="${col}"/>` + T(288, 58 + i * 22, String(c.labels[i]).slice(0, 30) + (hide ? '' : '  ' + fmt(v, c.unit)), { fill: '#c9d3dd' });
      a0 = a1;
    });
    if (c.center && !hide) s += T(cx, cy + 4, c.center, { anchor: 'middle', fill: C.text, size: 12 });
    return svg(W, Math.max(H, 60 + c.values.length * 22), s);
  }

  function scatter(c, hide) {
    const W = 720, H = 380, L = 60, R = 20, top = 34, B = 46, xs = c.points.map(p => p.x), ys = c.points.map(p => p.y);
    const sx = nice(0, Math.max(...xs)), sy = nice(Math.min(...ys, 0), Math.max(...ys, 100));
    const X = v => L + (v - sx.lo) / (sx.hi - sx.lo) * (W - L - R), Y = v => H - B - (v - sy.lo) / (sy.hi - sy.lo) * (H - B - top);
    let s = title(c) + yAxis(L, W - R, top, H - B, sy, hide, '');
    if (!hide) for (let v = sx.lo; v <= sx.hi; v += sx.step) s += T(X(v), H - B + 16, fmt(v), { anchor: 'middle' });
    const med = ys.slice().sort((a, b) => a - b)[Math.floor(ys.length / 2)];
    s += `<line x1="${L}" x2="${W - R}" y1="${Y(med)}" y2="${Y(med)}" stroke="${C.yellow}" stroke-dasharray="4 4" opacity="0.7"/>` + T(W - R, Y(med) - 4, 'mediana', { anchor: 'end', fill: C.yellow });
    c.points.forEach(p => { s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="5" fill="${p.y < med ? C.red : C.green}" opacity="0.75"><title>${esc(p.label)}${hide ? '' : ' · NPS ' + fmt(p.y) + ' · n ' + fmt(p.x)}</title></circle>`; });
    s += T(L, H - 6, c.x_label) + T(W - R, H - 6, 'eixo vertical: ' + c.y_label, { anchor: 'end' });
    return svg(W, H + (c.notes || []).length * 14 + 8, s + footer(c, H + 12));
  }

  function heatmap(c, hide) {
    const cw = 30, ch = 22, L = 240, top = 40, W = L + c.x.length * cw + 20, H = top + c.y.length * ch + 50;
    const div = c.scale === 'diverging';
    const lerp = (a, b, t) => 'rgb(' + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',') + ')';
    const col = v => { if (v == null) return '#11161d'; if (!div) { if (!v) return '#161b22'; return lerp([22, 27, 34], [255, 123, 46], Math.sqrt(v / c.max)); }
      const mid = 50, t = Math.max(-1, Math.min(1, (v - mid) / 50)); return t < 0 ? lerp([60, 60, 70], [248, 81, 73], -t) : lerp([60, 60, 70], [63, 185, 80], t); };
    let s = title(c);
    c.x.forEach((x, j) => s += T(L + j * cw + cw / 2, 32, x, { anchor: 'middle' }));
    c.y.forEach((u, i) => { s += T(L - 8, top + i * ch + 15, String(u).slice(0, 32), { anchor: 'end', fill: '#c9d3dd' });
      c.matrix[i].forEach((v, j) => s += `<rect x="${L + j * cw}" y="${top + i * ch}" width="${cw - 2}" height="${ch - 2}" rx="3" fill="${col(v)}"><title>${esc(u)} · ${esc(c.x[j])}${hide || v == null ? '' : ' · ' + fmt(v)}</title></rect>`); });
    const ly = top + c.y.length * ch + 16;
    s += T(L, ly + 10, div ? 'NPS baixo' : 'menos');
    for (let k = 0; k < 10; k++) { const v = div ? k * 11 : c.max * (k + 1) / 10; s += `<rect x="${L + 62 + k * 16}" y="${ly}" width="14" height="12" rx="2" fill="${col(v)}"/>`; }
    s += T(L + 62 + 10 * 16 + 6, ly + 10, (div ? 'NPS alto' : 'mais') + ' · ' + c.x_label);
    return svg(W, H + (c.notes || []).length * 14 + 8, s + footer(c, H + 4));
  }

  window.drawChart = function (c, hide) {
    switch (c.type) {
      case 'heatmap': return heatmap(c, hide);
      case 'hbar': return hbars(c, hide);
      case 'line': return lines(c, hide, false);
      case 'area': return lines(c, hide, true);
      case 'combo': return combo(c, hide);
      case 'stacked': return stacked(c, hide);
      case 'donut': return donut(c, hide);
      case 'scatter': return scatter(c, hide);
      case 'histogram': return columns(c, hide);
      default: return columns(c, hide);
    }
  };
})();
