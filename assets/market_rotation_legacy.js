    let rotationData = null;
    let researchData = null;
    let universeData = null;
    let rotationChart = null;
    let chartLevel = 'sectors';
    let tableLevel = 'sectors';
    let selectedSector = null;
    let selectedIndustry = null;
    const chartSelections = {sectors: new Set(), industries: new Set()};

    const COLORS = {
      leading: '#22c55e', improving: '#22d3ee', weakening: '#f59e0b', lagging: '#fb7185'
    };
    const scoreParts = [
      ['rank_relative_strength_20d', '20 日相對強弱', 20],
      ['rank_relative_strength_60d', '60 日相對強弱', 15],
      ['rank_acceleration_5d', '5 日加速度', 15],
      ['rank_breadth', '市場廣度', 25],
      ['rank_dollar_volume_expansion', '成交額擴張', 15],
      ['rank_persistence', '相對持續性', 10]
    ];

    const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[char]));
    const signed = (value, suffix = '%') => value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`;
    const tone = value => value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';
    const nameOf = row => row.name_zh === row.name ? row.name : `${row.name_zh} (${row.name})`;

    function setStatus(type, html) {
      const node = document.getElementById('status');
      node.className = `notice ${type || ''}`;
      node.innerHTML = html;
    }

    function renderHeader() {
      const c = rotationData.coverage;
      document.getElementById('asOf').textContent = rotationData.as_of;
      document.getElementById('coverage').textContent = `涵蓋 ${c.priced_securities}/${c.universe_securities} 檔（${c.coverage_pct}%）`;
      document.getElementById('sourceText').innerHTML =
        `價格：Yahoo Finance；成分：<a href="${rotationData.sources.sp500_constituents}" target="_blank" rel="noopener">S&amp;P 500</a>、` +
        `<a href="${rotationData.sources.nasdaq100_constituents}" target="_blank" rel="noopener">Nasdaq-100</a>`;
      setStatus('', `<strong>重要：</strong>${escapeHtml(rotationData.methodology.label)}。` +
        `本頁衡量「哪一群股票的價格、廣度與成交參與正在變強」，不能當作基金流向或真實資金淨流入。`);
    }

    function renderMetrics() {
      const leading = rotationData.sectors.filter(row => row.quadrant === 'leading')[0] || rotationData.sectors[0];
      const improving = rotationData.sectors
        .filter(row => row.quadrant === 'improving')
        .sort((a,b) => (b.score_change_5d ?? -999) - (a.score_change_5d ?? -999))[0];
      document.getElementById('topSector').textContent = leading ? leading.name_zh : '—';
      document.getElementById('topSectorNote').textContent = leading
        ? `輪動 ${leading.rotation_score.toFixed(1)} 分｜20 日相對 ${signed(leading.relative_strength_20d, 'pp')}` : '資料不足';
      document.getElementById('improvingSector').textContent = improving ? improving.name_zh : '目前無改善象限';
      document.getElementById('improvingSector').className = `metric-value ${improving ? 'positive' : 'neutral'}`;
      document.getElementById('improvingNote').textContent = improving
        ? `5 日加速度 ${signed(improving.acceleration_5d, 'pp')}｜分數變化 ${signed(improving.score_change_5d, '')}` : '等待落後板塊動能翻正';
      const marketReturn = rotationData.benchmark.return_20d;
      const marketVolume = rotationData.benchmark.dollar_volume_expansion;
      const marketReturnNode = document.getElementById('marketReturn');
      const marketVolumeNode = document.getElementById('marketVolume');
      marketReturnNode.textContent = signed(marketReturn);
      marketVolumeNode.textContent = signed(marketVolume);
      marketReturnNode.className = `metric-value ${tone(marketReturn)}`;
      marketVolumeNode.className = `metric-value ${tone(marketVolume)}`;
    }

    function renderVerdicts() {
      const rows = rotationData.sectors;
      const lead = rows.filter(r => r.quadrant === 'leading')[0];
      const improve = rows.filter(r => r.quadrant === 'improving').sort((a,b) => b.acceleration_5d - a.acceleration_5d)[0];
      const weaken = rows.filter(r => r.quadrant === 'weakening').sort((a,b) => a.acceleration_5d - b.acceleration_5d)[0];
      const broad = [...rows].sort((a,b) => b.breadth - a.breadth)[0];
      const cards = [
        lead && ['相對領先', nameOf(lead), `20 日相對 ${signed(lead.relative_strength_20d, 'pp')}，廣度 ${lead.breadth.toFixed(1)}%。先確認 60 日相對是否也為正。`, 'leading'],
        improve && ['正在改善', nameOf(improve), `短線加速度 ${signed(improve.acceleration_5d, 'pp')}，但 20 日相對仍為負；屬觀察候選，不是已完成輪動。`, 'improving'],
        weaken && ['領先但降溫', nameOf(weaken), `20 日仍勝市場 ${signed(weaken.relative_strength_20d, 'pp')}，加速度 ${signed(weaken.acceleration_5d, 'pp')}。留意是否滑向落後象限。`, 'weakening'],
        broad && ['參與最廣', nameOf(broad), `${broad.breadth.toFixed(1)}% 的綜合廣度，較能排除少數大型股單獨拉動。`, broad.quadrant]
      ].filter(Boolean);
      document.getElementById('verdicts').innerHTML = cards.map(card => `
        <div class="verdict">
          <div class="verdict-kicker">${escapeHtml(card[0])}</div>
          <div class="verdict-title ${card[3]}">${escapeHtml(card[1])}</div>
          <div class="verdict-copy">${escapeHtml(card[2])}</div>
        </div>`).join('');
    }

    const quadrantBackground = {
      id: 'quadrantBackground',
      beforeDraw(chart) {
        const {ctx, chartArea, scales} = chart;
        if (!chartArea || !scales.x || !scales.y) return;
        const x0 = scales.x.getPixelForValue(0);
        const y0 = scales.y.getPixelForValue(0);
        const {left, right, top, bottom} = chartArea;
        ctx.save();
        const areas = [
          [x0, top, right-x0, y0-top, 'rgba(34,197,94,.055)', '領先'],
          [left, top, x0-left, y0-top, 'rgba(34,211,238,.045)', '改善'],
          [x0, y0, right-x0, bottom-y0, 'rgba(245,158,11,.045)', '轉弱'],
          [left, y0, x0-left, bottom-y0, 'rgba(251,113,133,.04)', '落後']
        ];
        areas.forEach(([x,y,w,h,color,label]) => {
          ctx.fillStyle = color; ctx.fillRect(x,y,w,h);
          ctx.fillStyle = 'rgba(203,213,225,.35)'; ctx.font = '700 12px Outfit';
          ctx.fillText(label, x + 9, y + 17);
        });
        ctx.restore();
      }
    };

    const endpointLabels = {
      id: 'endpointLabels',
      afterDatasetsDraw(chart) {
        const {ctx} = chart;
        ctx.save();
        ctx.font = '700 11px Outfit, Noto Sans TC';
        chart.data.datasets.forEach((dataset, index) => {
          const meta = chart.getDatasetMeta(index);
          const point = meta.data[meta.data.length - 1];
          if (!point) return;
          ctx.fillStyle = dataset.borderColor;
          ctx.fillText(dataset.shortLabel, point.x + 7, point.y - 5);
        });
        ctx.restore();
      }
    };

    const trajectoryDirection = {
      id: 'trajectoryDirection',
      afterDatasetsDraw(chart) {
        const {ctx} = chart;
        ctx.save();
        chart.data.datasets.forEach((dataset, index) => {
          const points = chart.getDatasetMeta(index).data;
          if (points.length < 2) return;
          const start = points[0];
          const previous = points[points.length - 2];
          const end = points[points.length - 1];
          const dx = end.x - previous.x;
          const dy = end.y - previous.y;
          if (Math.hypot(dx, dy) < 2) return;

          // Hollow start ring plus a short label distinguishes the oldest
          // observation from the current, larger endpoint marker.
          ctx.strokeStyle = dataset.borderColor;
          ctx.fillStyle = '#111a2d';
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(start.x, start.y, 5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
          ctx.font = '800 10px Outfit, Noto Sans TC';
          ctx.fillStyle = dataset.borderColor;
          ctx.fillText('起', start.x + 7, start.y + 3);

          // Arrowhead follows the final segment, so its tip always identifies
          // the newest trading date even when the path loops across quadrants.
          ctx.save();
          ctx.translate(end.x, end.y);
          ctx.rotate(Math.atan2(dy, dx));
          ctx.fillStyle = dataset.borderColor;
          ctx.strokeStyle = '#e5f6ff';
          ctx.lineWidth = 1.25;
          ctx.beginPath();
          ctx.moveTo(5, 0); ctx.lineTo(-14, -8); ctx.lineTo(-10, 0); ctx.lineTo(-14, 8);
          ctx.closePath(); ctx.fill(); ctx.stroke();
          ctx.restore();
        });
        ctx.restore();
      }
    };

    function renderTrajectoryPeriod() {
      const sample = rotationData.sectors.find(row => row.trajectory?.length)?.trajectory || [];
      const node = document.getElementById('trajectoryPeriod');
      if (!sample.length) {
        node.textContent = '路徑期間：資料不足';
        return;
      }
      node.textContent = `路徑期間：${sample[0].date} → ${sample[sample.length - 1].date}（${sample.length} 個交易日）`;
    }

    function showChartUnavailable() {
      const canvas = document.getElementById('rotationChart');
      if (!canvas || document.getElementById('chartUnavailable')) return;
      canvas.hidden = true;
      canvas.parentElement.style.height = 'auto';
      const note = document.createElement('p');
      note.id = 'chartUnavailable';
      note.className = 'notice';
      note.setAttribute('role', 'status');
      note.innerHTML = '<strong>圖表元件載入失敗：</strong>Chart.js 無法取得，四象限路徑圖暫不顯示；資料本身正常，下方排名、數值與個股不受影響。';
      canvas.after(note);
    }

    function renderChart() {
      // A blocked or failed chart CDN must not stop the ranking, numbers
      // and stock lists from rendering, nor be reported as a data failure.
      if (typeof Chart === 'undefined') { showChartUnavailable(); return; }
      const available = chartLevel === 'industries' ? rotationData.industries.slice(0, 20) : rotationData.sectors;
      const rows = available.filter(row => chartSelections[chartLevel].has(row.key));
      const xMax = Math.max(1, ...rows.flatMap(row => (row.trajectory || []).map(p => Math.abs(p.x || 0)))) * 1.28;
      const yMax = Math.max(1, ...rows.flatMap(row => (row.trajectory || []).map(p => Math.abs(p.y || 0)))) * 1.28;
      const datasets = rows.map(row => {
        const points = row.trajectory?.length ? row.trajectory : [{x: row.relative_strength_20d, y: row.acceleration_5d, date: rotationData.as_of}];
        return {
          label: nameOf(row), shortLabel: row.name_zh,
          data: points, parsing: false, showLine: true,
          borderColor: COLORS[row.quadrant], backgroundColor: COLORS[row.quadrant],
          borderWidth: 1.6, pointRadius: points.map((_, i) => i === points.length - 1 ? Math.min(8, 4 + Math.max(0, row.dollar_volume_expansion || 0) / 15) : 1.8),
          pointHoverRadius: 7, tension: .18
        };
      });
      if (rotationChart) rotationChart.destroy();
      rotationChart = new Chart(document.getElementById('rotationChart'), {
        type: 'scatter', data: {datasets}, plugins: [quadrantBackground, trajectoryDirection, endpointLabels],
        options: {
          responsive: true, maintainAspectRatio: false,
          animation: {duration: 450}, interaction: {mode: 'nearest', intersect: false},
          scales: {
            x: {min: -xMax, max: xMax, grid: {color: ctx => ctx.tick.value === 0 ? 'rgba(226,232,240,.5)' : 'rgba(148,163,184,.08)'}, ticks: {color: '#8fa1b9', callback: v => `${Number(v).toFixed(Math.abs(v) >= 10 ? 0 : 1)}%`}, title: {display: true, text: '20 日相對強弱（百分點）', color: '#b8c6d9'}},
            y: {min: -yMax, max: yMax, grid: {color: ctx => ctx.tick.value === 0 ? 'rgba(226,232,240,.5)' : 'rgba(148,163,184,.08)'}, ticks: {color: '#8fa1b9', callback: v => `${Number(v).toFixed(Math.abs(v) >= 10 ? 0 : 1)}%`}, title: {display: true, text: '5 日相對動能加速度（百分點）', color: '#b8c6d9'}}
          },
          plugins: {
            legend: {display: false},
            tooltip: {callbacks: {label(context) {
              const row = rows[context.datasetIndex];
              const point = context.raw;
              return [`${nameOf(row)}｜${point.date || rotationData.as_of}`, `20日相對 ${signed(point.x, 'pp')}｜加速度 ${signed(point.y, 'pp')}`, `輪動分數 ${row.rotation_score.toFixed(1)}｜廣度 ${row.breadth.toFixed(1)}%`];
            }}}
          }
        }
      });
    }

    function renderChartFilters() {
      const available = chartLevel === 'industries' ? rotationData.industries.slice(0, 20) : rotationData.sectors;
      const selected = chartSelections[chartLevel];
      const filters = document.getElementById('chartSeriesFilters');
      filters.innerHTML = `
        <span class="series-filter-label">勾選顯示：</span>
        ${available.map(row => `
          <label class="series-option" style="--series-color:${COLORS[row.quadrant]}">
            <input type="checkbox" value="${escapeHtml(row.key)}" ${selected.has(row.key) ? 'checked' : ''}>
            <i class="series-dot"></i>${escapeHtml(row.name_zh)}
          </label>`).join('')}
        <button class="toggle filter-action" type="button" data-chart-preset="top3">前 3 名</button>
        <button class="toggle filter-action" type="button" data-chart-preset="all">全選</button>
        <button class="toggle filter-action" type="button" data-chart-preset="none">全部清除</button>
        <span class="selection-count">已選 ${selected.size}／${available.length}${selected.size ? '' : '（請勾選要比較的項目）'}</span>`;
      filters.querySelectorAll('input[type="checkbox"]').forEach(input => input.addEventListener('change', () => {
        if (input.checked) selected.add(input.value); else selected.delete(input.value);
        renderChartFilters(); renderChart();
      }));
      filters.querySelectorAll('[data-chart-preset]').forEach(button => button.addEventListener('click', () => {
        selected.clear();
        if (button.dataset.chartPreset === 'all') available.forEach(row => selected.add(row.key));
        if (button.dataset.chartPreset === 'top3') available.slice(0, 3).forEach(row => selected.add(row.key));
        renderChartFilters(); renderChart();
      }));
    }

    function renderTable() {
      const rows = rotationData[tableLevel];
      const isIndustry = tableLevel === 'industries';
      if (isIndustry && !rows.some(row => row.key === selectedIndustry)) selectedIndustry = rows[0]?.key || null;
      document.getElementById('rankingTableHelp').textContent = isIndustry
        ? '點選任一次產業列，股票名單會直接在該列下方展開。pp＝百分點；「權重差」為成交額流動性加權與等權報酬差。'
        : '點選板塊列可同步查看右上拆解。pp＝百分點；「權重差」為成交額流動性加權與等權報酬差。';
      document.getElementById('rankingBody').innerHTML = rows.map((row, index) => {
        const isSelected = isIndustry && row.key === selectedIndustry;
        return `
        <tr class="ranking-row${isSelected ? ' selected' : ''}" data-key="${escapeHtml(row.key)}"${isSelected ? ' aria-expanded="true"' : ''}>
          <td><span class="rank">${index + 1}</span><strong>${escapeHtml(nameOf(row))}</strong>${isIndustry ? `<span class="member-hint">點選查看納入的 ${row.member_count} 檔股票</span>` : ''}</td>
          <td><span class="pill ${row.quadrant}">${escapeHtml(row.quadrant_zh)}</span></td>
          <td><strong>${row.rotation_score.toFixed(1)}</strong> <span class="${tone(row.score_change_5d)}">(${signed(row.score_change_5d, '')})</span></td>
          <td class="${tone(row.relative_strength_20d)}">${signed(row.relative_strength_20d, 'pp')}</td>
          <td class="${tone(row.acceleration_5d)}">${signed(row.acceleration_5d, 'pp')}</td>
          <td class="${tone(row.relative_strength_60d)}">${signed(row.relative_strength_60d, 'pp')}</td>
          <td>${row.breadth?.toFixed(1) ?? '—'}%</td>
          <td class="${tone(row.dollar_volume_expansion)}">${signed(row.dollar_volume_expansion)}</td>
          <td>${row.persistence?.toFixed(1) ?? '—'}%</td>
          <td class="${tone(row.leadership_gap)}">${signed(row.leadership_gap, 'pp')}</td>
          <td>${row.member_count}</td>
        </tr>
        ${isSelected ? `<tr class="industry-members-row"><td colspan="11">${industryMembersHtml(row)}</td></tr>` : ''}`;
      }).join('');
      document.querySelectorAll('#rankingBody tr.ranking-row').forEach(rowNode => rowNode.addEventListener('click', () => {
        if (tableLevel === 'sectors') {
          selectedSector = rowNode.dataset.key;
          document.getElementById('sectorSelect').value = selectedSector;
          renderSectorDetail();
          return;
        }
        selectedIndustry = rowNode.dataset.key;
        renderTable();
        requestAnimationFrame(() => {
          document.querySelector('#rankingBody tr.ranking-row.selected')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
      }));
    }

    function industryMembersHtml(industry) {
      const members = (universeData?.members || [])
        .filter(member => member.industry === industry.key)
        .sort((a, b) => String(a.ticker).localeCompare(String(b.ticker)));
      const meta = members.length
        ? `本次排名使用 ${members.length} 檔：S&P 500 與 Nasdaq-100 合併股票池中的此分類成分；不是整個市場所有同業。`
        : `這個次產業排名使用 ${industry.member_count} 檔，但成分名單暫時無法載入；請稍後重新整理。`;
      const memberList = members.map(member =>
        `<div class="industry-member" title="來源指數：${escapeHtml((member.indexes || []).join('、') || '—')}｜分類：${escapeHtml(member.classification || '—')}"><strong>${escapeHtml(member.ticker)}</strong><span>${escapeHtml(member.name)}</span></div>`
      ).join('') || '<div class="panel-desc">成分名單資料不足。</div>';
      return `<section class="industry-members" aria-live="polite">
        <h3>${escapeHtml(industry.name_zh)}｜實際納入股票</h3>
        <p class="industry-member-meta">${escapeHtml(meta)}</p>
        <div class="industry-member-list">${memberList}</div>
      </section>`;
    }

    function renderSectorDetail() {
      const row = rotationData.sectors.find(item => item.key === selectedSector) || rotationData.sectors[0];
      if (!row) return;
      selectedSector = row.key;
      const ring = document.getElementById('scoreRing');
      ring.textContent = row.rotation_score.toFixed(0);
      ring.style.setProperty('--score', row.rotation_score);
      document.getElementById('sectorName').textContent = nameOf(row);
      document.getElementById('sectorState').innerHTML = `<span class="pill ${row.quadrant}">${row.quadrant_zh}</span>　5 日分數 ${signed(row.score_change_5d, '')}`;
      document.getElementById('scoreBars').innerHTML = scoreParts.map(([key, label, weight]) => `
        <div class="score-row" title="此項權重 ${weight}%；條形為同日橫向百分位，不是原始報酬。">
          <span>${label} (${weight}%)</span><div class="bar"><i style="width:${row[key] || 0}%"></i></div><strong>${row[key]?.toFixed(0) ?? '—'}</strong>
        </div>`).join('');
      document.getElementById('leaderTitle').textContent = `${row.name_zh}｜板塊內部領漲與落後個股`;
      renderStocks('leaderList', row.leaders || []);
      renderStocks('laggardList', row.laggards || []);
      renderResearchBridge(row);
    }

    function renderResearchBridge(row) {
      const target = document.getElementById('researchBridge');
      if (!target) return;
      const bridge = (researchData?.market_rotation_bridge?.sectors || []).find(item => item.sector_key === row.key);
      if (!bridge) {
        target.innerHTML = '<div class="panel-desc">研究綜合資料尚未建立；輪動圖仍可獨立使用。</div>';
        return;
      }
      const companies = bridge.tracked_companies || [];
      target.innerHTML = `<div class="research-action"><strong>${escapeHtml(bridge.sector_name)}｜${escapeHtml(bridge.quadrant_zh)}</strong><br>${escapeHtml(bridge.research_action || '')}</div>
        <div class="research-bridge-grid">${companies.length ? companies.map(company => `<article class="research-company">
          <strong>${escapeHtml(company.ticker)}｜${escapeHtml(company.thesis_label || '資料不足')}</strong>
          <span>最新證據期：${escapeHtml(company.evidence_period || '—')}</span>
          <span>${company.peer_group ? `${escapeHtml(company.peer_group)}｜有利百分位 ${company.peer_percentile == null ? '—' : company.peer_percentile.toFixed(1)}` : '追蹤名單中可比樣本不足'}</span>
        </article>`).join('') : '<div class="panel-desc">這個板塊目前沒有屬於 S&amp;P 500／Nasdaq-100 的 sec_kb 追蹤公司；不要由空白推論板塊基本面。</div>'}</div>
        <p class="panel-desc">${escapeHtml(bridge.coverage_note || '')}｜輪動資料截至 ${escapeHtml(bridge.as_of || '—')}。</p>`;
    }

    function renderStocks(target, rows) {
      document.getElementById(target).innerHTML = rows.length ? rows.map(row => `
        <div class="stock-row" title="${escapeHtml(row.name)}｜20日報酬 ${signed(row.return_20d)}｜成交額 ${signed(row.dollar_volume_expansion)}">
          <span><strong>${escapeHtml(row.ticker)}</strong> ${escapeHtml(row.name)}</span>
          <span class="${tone(row.relative_strength_20d)}">相對 ${signed(row.relative_strength_20d, 'pp')}</span>
          <span class="${tone(row.dollar_volume_expansion)}">量 ${signed(row.dollar_volume_expansion)}</span>
        </div>`).join('') : '<div class="panel-desc">資料不足</div>';
    }

    function bindControls() {
      document.querySelectorAll('[data-level]').forEach(button => button.addEventListener('click', () => {
        document.querySelectorAll('[data-level]').forEach(item => item.classList.toggle('active', item === button));
        chartLevel = button.dataset.level; renderChartFilters(); renderChart();
      }));
      document.querySelectorAll('[data-table-level]').forEach(button => button.addEventListener('click', () => {
        document.querySelectorAll('[data-table-level]').forEach(item => item.classList.toggle('active', item === button));
        tableLevel = button.dataset.tableLevel; renderTable();
      }));
      document.getElementById('sectorSelect').addEventListener('change', event => {
        selectedSector = event.target.value; renderSectorDetail();
      });
    }

    async function init() {
      try {
        const [response, researchResponse, universeResponse] = await Promise.all([
          fetch('market_rotation.json', {cache: 'no-cache'}),
          fetch('research_synthesis.json', {cache: 'no-cache'}).catch(() => null),
          fetch('market_rotation_universe.json', {cache: 'no-cache'}).catch(() => null),
        ]);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        rotationData = await response.json();
        researchData = researchResponse?.ok ? await researchResponse.json() : null;
        universeData = universeResponse?.ok ? await universeResponse.json() : null;
        if (!rotationData.sectors?.length || !rotationData.industries?.length) throw new Error('資料結構不完整');
        selectedSector = rotationData.sectors[0].key;
        rotationData.sectors.slice(0, 3).forEach(row => chartSelections.sectors.add(row.key));
        rotationData.industries.slice(0, 3).forEach(row => chartSelections.industries.add(row.key));
        const select = document.getElementById('sectorSelect');
        select.innerHTML = rotationData.sectors.map(row => `<option value="${escapeHtml(row.key)}">${escapeHtml(row.name_zh)}</option>`).join('');
        bindControls(); renderHeader(); renderMetrics(); renderVerdicts(); renderChartFilters(); renderTrajectoryPeriod(); renderChart(); renderTable(); renderSectorDetail();
      } catch (error) {
        setStatus('error', `<strong>載入失敗：</strong>無法讀取 market_rotation.json（${escapeHtml(error.message)}）。請確認每日資料流程已成功執行並部署。`);
      }
    }
    init();
