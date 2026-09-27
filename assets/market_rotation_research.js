// Research layer of the rotation page: absolute market environment, sector
// absolute states with concentration warnings, and the C-quality back-test.
// Independent of market_rotation_legacy.js; every section degrades to a
// plain message when its file is not published yet.
(() => {
  'use strict';

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
  const signed = (value, suffix = '%') =>
    value == null ? '—' : `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}${suffix}`;
  const plain = (value, suffix = '%', digits = 1) =>
    value == null ? '—' : `${Number(value).toFixed(digits)}${suffix}`;
  const tone = value => value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';

  const MARKET_READING = {
    broad_expansion: '上漲擴散到多數公司與板塊：相對排名與絕對趨勢方向一致。',
    narrow_leadership: '市場上漲，但集中在少數大型股或少數板塊：排名靠前的板塊要先看集中度。',
    rotation_divergence: '大盤變化有限、板塊強弱差距擴大：資金可能在板塊之間重新配置。',
    broad_retreat: '整體市場退潮：排名靠前的板塊多半只是跌得較少，不代表資金正在擴張。',
    stabilizing: '市場仍弱，但短期廣度與動能開始改善；尚未確認轉強。',
    neutral_mixed: '各項證據互相矛盾，不強迫分類；以下方各板塊的絕對狀態為準。',
    insufficient_data: '資料不足，不產生市場狀態。'
  };
  const STATE_TONE = {
    broad_expansion: 'positive', narrow_leadership: 'warning', rotation_divergence: 'neutral',
    broad_retreat: 'negative', stabilizing: 'info', neutral_mixed: 'neutral', insufficient_data: 'neutral',
    confirmed_leading: 'positive', cooling: 'warning', early_improvement: 'info',
    unconfirmed_rebound: 'neutral', clear_lagging: 'negative', small_sample_clue: 'neutral'
  };
  const TAG_TONE = {
    relative_only: 'warning', single_issuer_dominance: 'danger', liquidity_concentration: 'warning',
    volume_unconfirmed: 'neutral', small_sample: 'neutral', pending_change: 'info'
  };
  const STRUCTURE = {
    broad: '次產業廣泛確認', mixed: '次產業結構混合', concentrated: '強勢可能集中',
    insufficient_children: '正式次產業不足 3 個'
  };
  const CHECK_LABELS = {
    'R20>0': '20 日等權報酬 > 0', 'R20<0': '20 日等權報酬 < 0', 'R60>0': '60 日等權報酬 > 0',
    'R5>0': '5 日等權報酬 > 0', 'B20≥60%': '站上 20 日均線 ≥ 60%', 'B60≥55%': '站上 60 日均線 ≥ 55%',
    'B20<50%': '站上 20 日均線 < 50%', 'B20≤35%': '站上 20 日均線 ≤ 35%', 'B60≤40%': '站上 60 日均線 ≤ 40%',
    'UDVR5≥1.1': '上漲／下跌成交額 ≥ 1.1', 'UDVR5≤0.8': '上漲／下跌成交額 ≤ 0.8',
    '≥7 sectors R20>0': '≥ 7 個板塊 20 日上漲', '≤3 sectors R20>0': '≤ 3 個板塊 20 日上漲',
    '≤5 sectors R20>0': '≤ 5 個板塊 20 日上漲', 'LWGAP≥3pp': '流動性加權領先 ≥ 3pp',
    'ΔB20_5≥10pp': '20 日均線廣度 5 日內 +10pp', 'down-volume share falling': '下跌成交額占比下降',
    'fewer 20-session lows': '20 日新低家數減少', '-3%≤R20≤3%': '20 日等權報酬介於 ±3%',
    'SDISP≥8pp': '板塊分化 ≥ 8pp', '≥2 sectors A5≥0 and ≥2 A5<0': '加速與減速板塊各 ≥ 2 個'
  };
  const REASONS = {
    median_not_positive: '中位數公司並未勝過市場',
    negative_without_top1: '移除最大貢獻者後轉為落後',
    state_falls_without_top1: '移除最大貢獻者後狀態降級',
    removal_impact_ge_3pp: '單一公司影響 ≥ 3pp'
  };

  async function getJSON(path) {
    try {
      const response = await fetch(path, {cache: 'no-cache'});
      return response.ok ? await response.json() : null;
    } catch (error) {
      return null;
    }
  }

  function stateText(state, labels) {
    if (!state) return '—';
    const shown = state.confirmed || state.raw;
    let text = esc(labels[shown] || shown);
    if (state.confirmed && state.days_in_state) {
      text += `<small>${state.since_is_lower_bound ? '至少 ' : ''}${state.days_in_state} 個交易日</small>`;
    }
    if (state.pending) {
      text += `<small class="pending">→ ${esc(labels[state.pending] || state.pending)}` +
        ` 待確認 ${state.pending_days}／${state.confirm_sessions}</small>`;
    }
    return text;
  }

  function checkList(spec) {
    if (!spec) return '';
    const passed = spec.checks.filter(item => item.passed).length;
    const label = code => esc(CHECK_LABELS[code] || code);
    const gate = spec.gate ? `<li class="${spec.gate.passed ? 'ok' : 'fail'}">前提：${label(spec.gate.code)}` +
      `<span>${esc(spec.gate.value ?? '—')}</span></li>` : '';
    return `<div class="check-count">符合 ${passed}／${spec.checks.length}（需 ${spec.required}）</div>` +
      `<ul class="check-list">${gate}${spec.checks.map(item =>
        `<li class="${item.passed ? 'ok' : 'fail'}">${label(item.code)}<span>${esc(item.value ?? '—')}</span></li>`
      ).join('')}</ul>`;
  }

  function renderMarket(research, zh) {
    const target = document.getElementById('marketEnvironment');
    if (!target) return;
    if (!research) {
      target.innerHTML = '<div class="panel-desc">市場環境研究層尚未產出：合併後下一次每日排程會開始發布。</div>';
      return;
    }
    const data = research.data;
    const market = data.market;
    const labels = data.labels.market_states;
    const shown = market.state.confirmed || market.state.raw;
    const e = market.evidence;
    const lead = market.leadership;
    const sp = market.indexes['S&P 500'] || {};
    const nq = market.indexes['Nasdaq-100'] || {};
    const evidence = [
      ['20 日等權報酬', signed(e.R20), tone(e.R20)],
      ['60 日等權報酬', signed(e.R60), tone(e.R60)],
      ['站上 20 日均線', plain(e.B20), ''],
      ['站上 60 日均線', plain(e.B60), ''],
      ['上漲／下跌成交額（5 日）', e.UDVR5 == null ? '—' : e.UDVR5.toFixed(2), tone((e.UDVR5 ?? 1) - 1)],
      ['20 日正報酬板塊', `${e.sectors_positive_20d}／11`, ''],
      ['板塊分化（P75−P25）', plain(e.SDISP, 'pp', 2), ''],
      ['20 日新高−新低', e.NHNL == null ? '—' : `${e.NHNL > 0 ? '+' : ''}${e.NHNL}`, tone(e.NHNL)],
      ['S&P 500／Nasdaq-100 20 日', `${signed(sp.return_20d)}／${signed(nq.return_20d)}`, '']
    ];
    const others = Object.entries(market.checks).filter(([name]) => name !== shown);
    target.innerHTML = `
      <div class="env-head">
        <div>
          <div class="env-label">主要狀態</div>
          <div class="env-state ${STATE_TONE[shown] || ''}">${stateText(market.state, labels)}</div>
        </div>
        <div><div class="env-label">領漲類型</div><div class="env-value">${esc(lead.label)}</div>
          <div class="panel-desc">相對最強：${esc(lead.top_sectors.map(zh).join('、') || '—')}</div></div>
        <div><div class="env-label">資料信心</div>
          <div class="env-value">${market.confidence === 'high' ? '高' : '低'}</div></div>
      </div>
      <p class="env-reading">${esc(MARKET_READING[shown] || '')}</p>
      <div class="env-evidence">${evidence.map(([label, value, cls]) =>
        `<div><span>${esc(label)}</span><strong class="${cls}">${esc(value)}</strong></div>`).join('')}</div>
      ${market.shown_state_checks ? `<div class="env-checks"><h3>「${esc(labels[shown])}」的判斷依據</h3>` +
        checkList(market.shown_state_checks) + '</div>' : ''}
      <details class="env-details"><summary>其他市場狀態為什麼不成立</summary>
        <div class="env-other">${others.map(([name, spec]) =>
          `<div><h4>${esc(labels[name])}</h4>${checkList(spec)}</div>`).join('')}</div>
      </details>`;
  }

  function concentrationText(conc) {
    if (!conc || conc.mean_relative_20d == null) return '—';
    let text = `中位數 ${signed(conc.median_relative_20d, 'pp')}`;
    if (conc.top_contributor) {
      text += `<small>移除 ${esc(conc.top_contributor.ticker)}：${signed(conc.mean_relative_20d, 'pp')}` +
        ` → ${signed(conc.mean_without_top1, 'pp')}</small>`;
    }
    if (conc.single_issuer_dominance) {
      text += `<small class="negative">${conc.reasons.map(code => esc(REASONS[code] || code)).join('；')}</small>`;
    }
    return text;
  }

  function renderSectors(research, rotation) {
    const body = document.getElementById('sectorStateBody');
    if (!body) return;
    if (!research) {
      body.innerHTML = '<tr><td colspan="7" class="panel-desc">板塊絕對狀態尚未產出。</td></tr>';
      return;
    }
    const labels = research.data.labels;
    const ranked = new Map(((rotation && rotation.sectors) || []).map((row, index) => [row.key, [index + 1, row]]));
    const sectors = research.data.groups.filter(row => row.group_type === 'sector')
      .sort((a, b) => ((ranked.get(a.name_en) || [99])[0]) - ((ranked.get(b.name_en) || [99])[0]));
    body.innerHTML = sectors.map(row => {
      const [rank, v1] = ranked.get(row.name_en) || [null, null];
      const name = v1 && v1.name_zh !== v1.name ? `${v1.name_zh}<small>${esc(row.name_en)}</small>` : esc(row.name_en);
      const shown = row.state.confirmed || row.state.raw;
      const tags = row.risk_tags.map(tag =>
        `<span class="tag ${TAG_TONE[tag] || ''}">${esc(labels.risk_tags[tag] || tag)}</span>`).join('');
      const children = row.children || {};
      return `<tr>
        <td><strong>${rank ? `#${rank} ` : ''}${name}</strong></td>
        <td class="state ${STATE_TONE[shown] || ''}">${stateText(row.state, labels.group_states)}</td>
        <td><span class="${tone(row.evidence.RS20)}">${signed(row.evidence.RS20, 'pp')}</span>
          <small>本身 <span class="${tone(row.evidence.R20)}">${signed(row.evidence.R20)}</span></small></td>
        <td>${plain(row.evidence.BPOS20, '%', 0)}／${plain(row.evidence.BMA20, '%', 0)}
          <small>持續性 ${plain(row.evidence.P10, '%', 0)}</small></td>
        <td class="tags">${tags || '<span class="panel-desc">—</span>'}</td>
        <td>${concentrationText(row.concentration)}</td>
        <td>${esc(STRUCTURE[children.structure] || '—')}<small>${children.formal_child_count ?? 0} 個正式次產業` +
          `${children.child_confirmation_pct != null ? `｜確認 ${plain(children.child_confirmation_pct, '%', 0)}` : ''}</small></td>
      </tr>`;
    }).join('');
  }

  function renderBacktest(result, labels) {
    const target = document.getElementById('backtestSummary');
    if (!target) return;
    if (!result) {
      target.innerHTML = '<div class="panel-desc">回測尚未執行：每月 3 日自動執行，也可以在 GitHub Actions ' +
        '手動觸發「Market rotation back-test」。</div>';
      return;
    }
    const method = result.methodology;
    const stateLabels = (labels && labels.group_states) || {};
    const rows = Object.entries(result.by_state).map(([state, block]) => {
      const all = block.all['60d'];
      const holdout = block.holdout['60d'];
      return `<tr>
        <td class="state ${STATE_TONE[state] || ''}">${esc(stateLabels[state] || state)}</td>
        <td>${all.events}<small>${esc({higher: '較高信心', moderate: '中信心', exploratory: '探索性',
          insufficient: '樣本不足'}[all.confidence] || all.confidence)}</small></td>
        <td class="${tone(all.median_excess)}">${signed(all.median_excess, 'pp')}</td>
        <td>${plain(all.win_rate)}</td>
        <td class="negative">${signed(all.p10_excess, 'pp')}</td>
        <td>${signed(all.median_mae, 'pp')}</td>
        <td>${holdout.events ? `${signed(holdout.median_excess, 'pp')}<small>${holdout.events} 次</small>` : '—'}</td>
      </tr>`;
    }).join('');
    const base = result.unconditional['60d'];
    target.innerHTML = `
      <p class="notice warn"><strong>C 級歷史：</strong>用今天的成分股回算過去（${esc(result.period.start)}～` +
      `${esc(result.period.end)}），已退出指數的公司不在樣本內，有存活者偏誤；只能看方向與樣本量，` +
      '不是已驗證的交易規則。</p>' +
      `<div class="table-wrap"><table><thead><tr><th>確認後狀態</th><th>事件數</th><th>60 日中位超額</th>` +
      '<th>勝率</th><th>最差 10%</th><th>中位 MAE</th><th>樣本外 60 日</th></tr></thead>' +
      `<tbody>${rows}</tbody></table></div>` +
      `<p class="panel-desc">比較基準：任一板塊任一天之後 60 日的中位超額 ${signed(base.median_excess, 'pp')}` +
      `（勝率 ${plain(base.win_rate)}）。狀態要比這個基準好，才有辨識力。規則版本 ${esc(method.rule_version)}；` +
      `樣本外自 ${esc(result.period.holdout_start)}。</p>`;
  }

  async function init() {
    const [research, rotation, backtest] = await Promise.all([
      getJSON('market_rotation_research.json'),
      getJSON('market_rotation.json'),
      getJSON('market_rotation_history/backtest/sector_results.json')
    ]);
    const names = new Map(((rotation && rotation.sectors) || []).map(row => [row.key, row.name_zh]));
    renderMarket(research, name => names.get(name) || name);
    renderSectors(research, rotation);
    renderBacktest(backtest, research && research.data.labels);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
