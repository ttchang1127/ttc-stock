(() => {
  'use strict';
  const PERIODS = [['1d', '1 日'], ['1w', '1 週'], ['1m', '1 個月'], ['3m', '3 個月'], ['6m', '6 個月']];
  const SCALE = { '1d': 4, '1w': 8, '1m': 15, '3m': 30, '6m': 50 };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const pct = value => value == null ? '—' : `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
  const capText = value => value >= 1e12 ? `$${(value / 1e12).toFixed(2)} 兆` : `$${(value / 1e8).toFixed(0)} 億`;
  const $ = id => document.getElementById(id);
  let data = null;
  let period = '1m';
  let selected = null;

  function color(value) {
    if (value == null) return '#343d50';
    const level = Math.max(-1, Math.min(1, value / SCALE[period]));
    if (Math.abs(level) < .055) return '#475569';
    if (level > 0) return level > .58 ? '#198873' : level > .25 ? '#287a74' : '#396e72';
    return level < -.58 ? '#ad5f70' : level < -.25 ? '#936171' : '#78616c';
  }

  function worst(row, side) {
    const area = row.reduce((total, item) => total + item.area, 0);
    const max = Math.max(...row.map(item => item.area));
    const min = Math.min(...row.map(item => item.area));
    return Math.max(side * side * max / area ** 2, area ** 2 / (side * side * min));
  }
  function squarify(items, x, y, w, h) {
    if (!items.length || w <= 0 || h <= 0) return [];
    const total = items.reduce((sum, item) => sum + item.value, 0);
    if (!total) return [];
    const queue = items.map(item => ({...item, area: item.value * w * h / total}));
    const rects = [];
    while (queue.length) {
      const side = Math.min(w, h);
      if (side < .001) break;
      const row = [queue.shift()];
      while (queue.length && worst([...row, queue[0]], side) <= worst(row, side)) row.push(queue.shift());
      const rowArea = row.reduce((sum, item) => sum + item.area, 0);
      if (w >= h) {
        const strip = rowArea / h;
        let offset = y;
        row.forEach(item => { const height = item.area / strip; rects.push({...item, x, y:offset, w:strip, h:height}); offset += height; });
        x += strip; w -= strip;
      } else {
        const strip = rowArea / w;
        let offset = x;
        row.forEach(item => { const width = item.area / strip; rects.push({...item, x:offset, y, w:width, h:strip}); offset += width; });
        y += strip; h -= strip;
      }
    }
    return rects;
  }

  function currentStocks() {
    const focus = $('techFocus').value;
    const adjacent = $('techAdjacent').checked;
    const search = $('techSearch').value.trim().toLowerCase();
    return data.stocks.filter(stock =>
      (adjacent || !stock.is_adjacent || focus === 'family:adjacent' || focus === `group:${stock.group_id}`) &&
      (focus === 'all' || (focus.startsWith('family:') && stock.family_id === focus.slice(7)) ||
        (focus.startsWith('group:') && stock.group_id === focus.slice(6))) &&
      (!search || `${stock.ticker} ${stock.name} ${stock.group} ${stock.tags.join(' ')}`.toLowerCase().includes(search)));
  }
  function size(members) {
    return $('techEqual').checked ? members.length : members.reduce((sum, row) => sum + row.market_cap_usd, 0);
  }
  function bucket(stocks, key) {
    const grouped = new Map();
    stocks.forEach(stock => {
      const id = stock[key + '_id'];
      if (!grouped.has(id)) grouped.set(id, {id, label:stock[key], members:[]});
      grouped.get(id).members.push(stock);
    });
    return [...grouped.values()].sort((a,b) => size(b.members) - size(a.members));
  }
  function leaf(stock, rect) {
    const value = stock.returns[period];
    const style = `left:${rect.x}px;top:${rect.y}px;width:${rect.w}px;height:${rect.h}px;background:${color(value)}`;
    const label = rect.w > 37 && rect.h > 21 ? `<strong>${escapeHtml(stock.ticker)}</strong>` : '';
    const change = rect.w > 54 && rect.h > 48 ? `<small>${pct(value)}</small>` : '';
    const title = `${stock.ticker}｜${stock.group}｜市值 ${capText(stock.market_cap_usd)}｜${pct(value)}`;
    return `<button type="button" class="tech-tile${selected === stock.ticker ? ' selected' : ''}" data-ticker="${escapeHtml(stock.ticker)}" ` +
      `style="${style}" aria-label="${escapeHtml(title)}" title="${escapeHtml(title)}">${label}${change}</button>`;
  }
  function groupHtml(group, rect, zoomed = false) {
    if (rect.w < 2 || rect.h < 2) return '';
    const header = !zoomed && rect.w > 75 && rect.h > 48 ? 24 : 0;
    const head = header ? `<button type="button" class="tech-group-title" data-focus="group:${escapeHtml(group.id)}" title="放大 ${escapeHtml(group.label)}">${escapeHtml(group.label)} <small>${group.members.length}</small></button>` : '';
    const inner = squarify(group.members.map(stock => ({value:$('techEqual').checked ? 1 : stock.market_cap_usd, stock})),
                            3, header + 2, Math.max(0, rect.w - 6), Math.max(0, rect.h - header - 5));
    return `<div class="tech-group" style="left:${rect.x}px;top:${rect.y}px;width:${rect.w}px;height:${rect.h}px" title="${escapeHtml(group.label)}">` +
      head + inner.map(tile => leaf(tile.stock, tile)).join('') + '</div>';
  }
  function familyHtml(family, rect) {
    if (rect.w < 2 || rect.h < 2) return '';
    const header = rect.w > 90 && rect.h > 52 ? 28 : 0;
    const head = header ? `<button type="button" class="tech-family-title" data-focus="family:${escapeHtml(family.id)}" title="放大 ${escapeHtml(family.label)}">${escapeHtml(family.label)} <small>${family.members.length}</small></button>` : '';
    const groups = bucket(family.members, 'group');
    const inner = squarify(groups.map(group => ({value:size(group.members), group})), 3, header + 2,
                            Math.max(0, rect.w - 6), Math.max(0, rect.h - header - 5));
    return `<div class="tech-family" style="left:${rect.x}px;top:${rect.y}px;width:${rect.w}px;height:${rect.h}px">` +
      head + inner.map(tile => groupHtml(tile.group, tile)).join('') + '</div>';
  }
  function stat(members) {
    const priced = members.filter(row => row.returns['1m'] != null);
    const count = priced.length;
    const cap = priced.reduce((total, row) => total + row.market_cap_usd, 0);
    const ma = members.filter(row => row.above_ma50 != null);
    return {count:members.length, priced:count,
      up:count ? 100 * priced.filter(row => row.returns['1m'] > 0).length / count : null,
      equal:count ? priced.reduce((total, row) => total + row.returns['1m'], 0) / count : null,
      cap:cap ? priced.reduce((total, row) => total + row.returns['1m'] * row.market_cap_usd, 0) / cap : null,
      ma:ma.length ? 100 * ma.filter(row => row.above_ma50).length / ma.length : null};
  }
  function renderBreadth(stocks) {
    const focus = $('techFocus').value;
    const rows = focus.startsWith('group:') ? bucket(stocks, 'group') :
      focus.startsWith('family:') ? bucket(stocks, 'group') : bucket(stocks, 'family');
    $('techBreadth').innerHTML = rows.map(row => {
      const s = stat(row.members);
      const next = focus === 'all' ? `family:${row.id}` : `group:${row.id}`;
      return `<tr><td><button type="button" class="tech-table-link" data-focus="${escapeHtml(next)}">${escapeHtml(row.label)}</button></td>` +
        `<td>${s.count}／${s.priced}</td><td>${s.up == null ? '—' : s.up.toFixed(0) + '%'}</td>` +
        `<td>${pct(s.equal)}</td><td>${pct(s.cap)}</td><td>${s.ma == null ? '—' : s.ma.toFixed(0) + '%'}</td></tr>`;
    }).join('') || '<tr><td colspan="6">此範圍暫無符合條件的公司。</td></tr>';
  }
  function renderDetails() {
    const stock = data.stocks.find(row => row.ticker === selected);
    if (!stock) return;
    $('techDetail').innerHTML = `<div class="tech-detail-title"><strong>${escapeHtml(stock.ticker)} ${escapeHtml(stock.name)}</strong>` +
      `<span>${capText(stock.market_cap_usd)}${stock.below_threshold ? ' · 觀察名單門檻例外' : ''}</span></div>` +
      `<p>${escapeHtml(stock.family)} ／ ${escapeHtml(stock.group)}。${escapeHtml(stock.reason)}</p>` +
      `<p>題材：${stock.tags.length ? stock.tags.map(escapeHtml).join('、') : '—'}　來源：${stock.sources.map(escapeHtml).join('、')}</p>` +
      `<div class="detail-returns">${PERIODS.map(([id, label]) => `<span>${label} <strong>${pct(stock.returns[id])}</strong></span>`).join('')}</div>` +
      `<p class="panel-desc">報價日 ${escapeHtml(stock.quote_as_of || '無')}；歷史收盤價未調整股息或拆股。` +
      `<a href="https://www.nasdaq.com/market-activity/stocks/${encodeURIComponent(stock.ticker.toLowerCase())}" target="_blank" rel="noopener noreferrer">Nasdaq 公司報價 ↗</a></p>`;
  }
  function render() {
    if (!data) return;
    const stocks = currentStocks();
    const focus = $('techFocus').value;
    const map = $('techMap');
    const width = Math.floor(map.clientWidth), height = map.clientHeight;
    let html = '';
    if (focus.startsWith('group:')) {
      html = squarify(stocks.map(stock => ({value:$('techEqual').checked ? 1 : stock.market_cap_usd, stock})), 1, 1, width - 2, height - 2)
        .map(tile => leaf(tile.stock, tile)).join('');
    } else if (focus.startsWith('family:')) {
      html = squarify(bucket(stocks, 'group').map(group => ({value:size(group.members), group})), 1, 1, width - 2, height - 2)
        .map(tile => groupHtml(tile.group, tile, false)).join('');
    } else {
      html = squarify(bucket(stocks, 'family').map(family => ({value:size(family.members), family})), 1, 1, width - 2, height - 2)
        .map(tile => familyHtml(tile.family, tile)).join('');
    }
    map.innerHTML = html || '<p class="tech-empty">此範圍沒有符合條件的公司。</p>';
    $('techMapNote').textContent = `${stocks.length} 家公司，${stocks.filter(s => s.returns[period] != null).length} 家有本期報價；` +
      ($('techEqual').checked ? '每家公司等大' : '方塊面積按公司市值') + `。價格截至 ${data.as_of}。`;
    $('techPath').textContent = focus === 'all' ? '全部核心科技' :
      $('techFocus').selectedOptions[0].textContent;
    renderBreadth(stocks);
    renderDetails();
  }
  function focusTo(value) {
    $('techFocus').value = value;
    if (value === 'family:adjacent') $('techAdjacent').checked = true;
    render();
  }
  async function init() {
    try {
      const response = await fetch('tech_stock_map.json', {cache:'no-cache'});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      data = await response.json();
      $('techAsOf').textContent = data.as_of;
      $('techHighlights').innerHTML = `<span><strong>${data.coverage.visible}</strong> 家公司</span>` +
        `<span><strong>${data.coverage.priced}</strong> 家有近期股價</span>` +
        `<span>VGT 持股日 <strong>${escapeHtml(data.sources.vgt_report_date)}</strong></span>`;
      $('mapSubtitle').textContent = `分類版本 ${data.taxonomy_version}；市值門檻 ${capText(data.minimum_market_cap_usd)}。科技相鄰預設不顯示。`;
      const families = [...new Map(data.stocks.map(s => [s.family_id, s.family])).entries()];
      const groups = [...new Map(data.stocks.map(s => [s.group_id, {name:s.group, family:s.family}])).entries()];
      $('techFocus').insertAdjacentHTML('beforeend', families.map(([id, name]) => `<option value="family:${escapeHtml(id)}">${escapeHtml(name)}</option>`).join('') +
        groups.map(([id, item]) => `<option value="group:${escapeHtml(id)}">${escapeHtml(item.family)} ／ ${escapeHtml(item.name)}</option>`).join(''));
      $('techEtfs').innerHTML = (data.reference_etfs.items || []).map(etf =>
        `<div class="tech-etf"><strong>${escapeHtml(etf.ticker)}</strong><span>5 日 ${pct(etf.r5_pct)}</span><span>20 日 ${pct(etf.r20_pct)}</span><span>60 日 ${pct(etf.r60_pct)}</span></div>`).join('') +
        `<p class="panel-desc">ETF 報價日 ${escapeHtml(data.reference_etfs.as_of)}；報酬來自既有 ETF 研究資料。</p>`;
      document.querySelectorAll('[data-period]').forEach(button => button.addEventListener('click', () => {
        period = button.dataset.period;
        document.querySelectorAll('[data-period]').forEach(item => item.classList.toggle('active', item === button));
        render();
      }));
      ['techFocus', 'techAdjacent', 'techEqual'].forEach(id => $(id).addEventListener('change', render));
      $('techSearch').addEventListener('input', render);
      mapEvent();
      let timer;
      window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(render, 130); });
      render();
    } catch (error) {
      $('techAsOf').textContent = '資料未就緒';
      $('techHighlights').textContent = '科技股資料尚未產出，請稍後再試。';
      $('techMap').innerHTML = '<p class="tech-empty">科技股地圖暫時無法載入。</p>';
      $('techBreadth').innerHTML = '<tr><td colspan="6">資料暫時無法載入。</td></tr>';
      $('techEtfs').textContent = '資料暫時無法載入。';
    }
  }
  function mapEvent() {
    $('techMap').addEventListener('click', event => {
      const zoom = event.target.closest('[data-focus]');
      if (zoom) { focusTo(zoom.dataset.focus); return; }
      const tile = event.target.closest('[data-ticker]');
      if (tile) { selected = tile.dataset.ticker; render(); $('techDetail').scrollIntoView({behavior:'smooth', block:'nearest'}); }
    });
    $('techBreadth').addEventListener('click', event => {
      const button = event.target.closest('[data-focus]');
      if (button) focusTo(button.dataset.focus);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
