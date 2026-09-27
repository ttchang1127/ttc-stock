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

  const CRITERIA = {
    enough_events: '校準期領先與落後事件各 ≥ 30',
    expected_direction: '領先勝過基準、落後輸給基準',
    holds_out_of_sample: '最後 6 個月（樣本外）方向一致',
    downside_not_worse: '領先的最差 10% 不比基準差',
    interval_excludes_zero: '領先優勢的 90% 區間不含 0',
    more_than_one_horizon: '20／60／120 日至少兩個期間成立'
  };
  const VERDICT_TONE = {
    supported_pending_a_b_history: 'positive', partial_not_adoptable: 'warning',
    not_supported: 'negative', insufficient_sample: 'neutral'
  };

  function renderSensitivity(result) {
    const target = document.getElementById('sensitivitySummary');
    if (!target) return;
    if (!result) {
      target.innerHTML = '<div class="panel-desc">規則敏感度研究尚未執行：會隨每月回測一起產生。</div>';
      return;
    }
    const rows = result.variants.map(variant => {
      const cal = variant.samples.calibration['60d'];
      const hold = variant.samples.holdout['60d'];
      const interval = cal.leading_edge_interval_pp;
      const marks = Object.entries(variant.criteria).map(([key, value]) =>
        `<li class="${value === true ? 'ok' : value === null ? 'na' : 'fail'}">${esc(CRITERIA[key] || key)}` +
        `<span>${value === null ? '無法檢查' : value ? '符合' : '不符合'}</span></li>`).join('');
      return `<tr>
        <td><strong>${esc(variant.label)}</strong></td>
        <td class="state ${VERDICT_TONE[variant.verdict] || ''}">${esc(result.verdicts[variant.verdict] || variant.verdict)}</td>
        <td class="${tone(cal.leading_edge_pp)}">${signed(cal.leading_edge_pp, 'pp')}<small>${cal.leading_events} 次` +
          `${interval ? `｜區間 ${signed(interval[0], '')}～${signed(interval[1], '')}` : ''}</small></td>
        <td class="${tone(cal.lagging_edge_pp)}">${signed(cal.lagging_edge_pp, 'pp')}<small>${cal.lagging_events} 次</small></td>
        <td class="${tone(hold.leading_edge_pp)}">${signed(hold.leading_edge_pp, 'pp')}<small>領先 ${hold.leading_events}／落後 ${hold.lagging_events} 次</small></td>
        <td class="criteria"><ul class="check-list">${marks}</ul></td>
      </tr>`;
    }).join('');
    target.innerHTML = `
      <h3 class="exposure-title">規則敏感度：換一種規則會不會比較有用？</h3>
      <p class="panel-desc">候選規則在看到結果前就固定（版本 ${esc(result.version)}），失敗的也一併公開。` +
      '「優勢」＝狀態之後 60 日的中位超額，減去同一期間任一板塊任一天的中位超額；落後的優勢＝基準減狀態' +
      '（正值表示落後板塊確實表現較差）。校準期不使用最後 6 個月的價格。</p>' +
      `<div class="table-wrap"><table class="state-table sensitivity-table"><thead><tr>` +
      '<th>候選規則</th><th>判定</th><th>已確認領先優勢（校準）</th><th>明確落後優勢（校準）</th>' +
      `<th>領先優勢（樣本外）</th><th>檢查項目</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  const ETF_VERDICT_TONE = {supported: 'positive', partial: 'warning', not_supported: 'negative'};

  function renderEtfMomentum(result) {
    const target = document.getElementById('etfMomentumSummary');
    if (!target) return;
    if (!result) {
      target.innerHTML = '<div class="panel-desc">板塊 ETF 中期動能回測尚未執行：會隨每月回測一起產生。</div>';
      return;
    }
    const cell = stats => stats && stats.months
      ? `<span class="${tone(stats.excess_cagr_pp)}">${signed(stats.excess_cagr_pp, 'pp')}</span>` +
        `<small>資訊比率 ${stats.information_ratio ?? '—'}｜勝率 ${plain(stats.hit_rate)}</small>`
      : '—';
    const rows = result.variants.map(variant => {
      const cal = variant.calibration;
      const interval = variant.calibration_mean_excess_interval_pp;
      return `<tr>
        <td><strong>${esc(variant.label)}</strong></td>
        <td class="state ${ETF_VERDICT_TONE[variant.verdict] || ''}">${esc(result.verdicts[variant.verdict] || variant.verdict)}</td>
        <td>${cell(cal)}<small>${esc(cal.start || '')}～${esc(cal.end || '')}` +
          `${interval ? `｜月均區間 ${signed(interval[0], '')}～${signed(interval[1], '')}` : ''}</small></td>
        <td>${cell(variant.holdout)}<small>${esc(variant.holdout.start || '')}～${esc(variant.holdout.end || '')}</small></td>
        <td>${plain(cal.strategy_max_drawdown)}<small>等權 ${plain(cal.equal_weight_max_drawdown)}</small></td>
        <td>${variant.all.annual_turnover ?? '—'}<small>倍／年</small></td>
      </tr>`;
    }).join('');
    const ranking = result.latest_ranking;
    const chips = ranking.rows.map(row =>
      `<span class="tag ${row.rank <= 3 ? 'info' : ''}">#${row.rank} ${esc(row.ticker)} ${signed(row.momentum_pct)}</span>`).join('');
    target.innerHTML = `
      <h3 class="exposure-title">板塊 ETF 中期動能：學術研究的時間尺度</h3>
      <p class="panel-desc">每月底依「12 個月前到 1 個月前」的報酬排名 11 檔 SPDR 板塊 ETF，持有前 3 名到下次調整，` +
      '和「全部等權」比較；每換手 1 元扣 0.1%。ETF 價格是真實可投資的序列，沒有成分股存活者偏誤。' +
      `2016 年起為樣本外。規則版本 ${esc(result.version)}，候選事先固定。</p>` +
      `<div class="table-wrap"><table class="state-table sensitivity-table"><thead><tr>` +
      '<th>候選規則</th><th>判定</th><th>年化超額（校準）</th><th>年化超額（樣本外）</th>' +
      `<th>最大回撤（校準）</th><th>換手率</th></tr></thead><tbody>${rows}</tbody></table></div>` +
      `<p class="panel-desc">${esc(ranking.as_of)} 的 12 減 1 個月排名（僅供對照，研究中）：</p><div class="tags">${chips}</div>`;
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

  const PRIORITY = {
    review_now: ['立即覆核', 'danger'], monitor: ['持續觀察', 'info'], data_blocked: ['資料阻擋', 'warning']
  };
  const DIGEST_STATUS = {
    awaiting_history: '每日快照尚未開始累積：合併後第一次每日排程會建立第一筆，之後才能比較變化。',
    baseline: '今天是第一筆快照，已建立比較基準；下一個交易日起列出變化。',
    baseline_after_rule_change: '規則版本更新，今天重新建立比較基準，不把重新分類當成變化。'
  };

  function eventCard(event) {
    const holders = event.related_holdings.length
      ? `<span class="tag danger">你的持股：${esc(event.related_holdings.join('、'))}</span>` : '';
    const ev = event.evidence || {};
    const facts = ['RS20', 'RS60', 'A5', 'BPOS20'].filter(key => ev[key] != null)
      .map(key => `${key} ${key === 'BPOS20' ? plain(ev[key], '%', 0) : signed(ev[key], 'pp')}`).join('｜');
    return `<li class="digest-event ${event.priority.toLowerCase()}"><span class="digest-priority">${esc(event.priority)}</span>
      <div><strong>${esc(event.text)}</strong>${holders}${facts ? `<small>${esc(facts)}</small>` : ''}</div></li>`;
  }

  function renderDigest(digest) {
    const target = document.getElementById('rotationDigest');
    if (!target) return;
    if (!digest) {
      target.innerHTML = '<div class="panel-desc">每日變化摘要尚未產出。</div>';
      return;
    }
    const events = digest.events || [];
    const notable = events.filter(e => e.priority !== 'P3');
    const pending = events.filter(e => e.priority === 'P3');
    const shown = notable.slice(0, 5);
    let body = digest.headline ? `<p class="env-reading">${esc(digest.headline)}</p>` : '';
    body += `<div class="panel-desc">資料截至 ${esc(digest.as_of || '—')}｜比較 ${esc(digest.compared_with || '—')}` +
      `｜規則 ${esc(digest.rule_version || '—')}</div>`;
    if (DIGEST_STATUS[digest.status]) {
      body += `<p class="digest-quiet">${esc(DIGEST_STATUS[digest.status])}</p>`;
    } else if (!notable.length) {
      body += `<p class="digest-quiet">已讀已記錄：相較 ${esc(digest.compared_with)}，沒有新增風險、確認改善或結論變化。` +
        '排名與原始數字已更新，但不重複列入重點。</p>';
    } else {
      body += `<ul class="digest-list">${shown.map(eventCard).join('')}</ul>`;
      if (notable.length > shown.length) {
        body += `<details><summary>另有 ${notable.length - shown.length} 項變化</summary>` +
          `<ul class="digest-list">${notable.slice(5).map(eventCard).join('')}</ul></details>`;
      }
    }
    if (pending.length) {
      body += `<details><summary>待確認線索 ${pending.length} 項（不通知）</summary>` +
        `<ul class="digest-list">${pending.map(eventCard).join('')}</ul></details>`;
    }
    target.innerHTML = body;
  }

  function stateCell(view) {
    if (!view || !view.state) return '<small>無研究資料</small>';
    const pending = view.pending ? `<small class="pending">→ ${esc(view.pending_label)} 待確認</small>` : '';
    return `<small class="state ${STATE_TONE[view.state] || ''}">${esc(view.state_label)}</small>${pending}`;
  }

  function renderExposure(exposure) {
    const target = document.getElementById('portfolioExposure');
    if (!target) return;
    if (!exposure) {
      target.innerHTML = '<div class="panel-desc">持股曝險尚未產出。</div>';
      return;
    }
    const issuer = exposure.issuer_concentration || {};
    const sectors = exposure.sector_concentration.sectors || [];
    const palette = ['#38bdf8', '#a78bfa', '#2dd4bf', '#f59e0b', '#fb7185', '#94a3b8'];
    const bar = sectors.map((row, index) =>
      `<span style="width:${row.weight}%;background:${palette[index % palette.length]}" ` +
      `title="${esc(row.name_zh)} ${plain(row.weight)}">${row.weight >= 12 ? esc(row.name_zh) : ''}</span>`).join('');
    const legend = sectors.map((row, index) =>
      `<li><i style="background:${palette[index % palette.length]}"></i>${esc(row.name_zh)} ${plain(row.weight)}` +
      `<small>${esc(row.tickers.join('、'))}｜${esc(row.rotation.state_label)}</small></li>`).join('');
    const rows = exposure.positions.map(p => {
      const [label, cls] = PRIORITY[p.research_priority] || [p.research_priority, ''];
      return `<tr>
        <td><strong>${esc(p.ticker)}</strong><small>${plain(p.weight)}</small></td>
        <td>${esc(p.sector_zh)}${stateCell(p.sector_rotation)}</td>
        <td>${esc(p.industry)}${stateCell(p.industry_rotation)}</td>
        <td><span class="tag ${cls}">${esc(label)}</span></td>
        <td class="reasons">${p.reasons.map(r => `<div>${esc(r)}</div>`).join('')}</td>
      </tr>`;
    }).join('');
    const coverage = exposure.coverage;
    const look = exposure.look_through || {};
    const lookHtml = look.available ? `
      <h3 class="exposure-title">含基金看穿（直接個股＋${esc(look.funds.map(f => f.ticker).join('、'))}）</h3>
      <p class="panel-desc">把基金拆成成分股後，你的總資產實際押在哪裡。直接個股占總資產 ${plain(look.direct_share_pct)}；` +
      `基金成分取自 SEC N-PORT：${look.funds.map(f => `${esc(f.ticker)} ${esc(f.report_date)}`).join('、')}` +
      `（每季申報、延遲約 60 天）；未對應代號的權重 ${plain(look.unmapped_weight_pct)}。</p>
      <div class="sector-bar" role="img" aria-label="含基金的板塊權重">${look.sectors.map((row, index) =>
        `<span style="width:${row.weight}%;background:${palette[index % palette.length]}" title="${esc(row.name_zh)} ${plain(row.weight)}">` +
        `${row.weight >= 12 ? esc(row.name_zh) : ''}</span>`).join('')}</div>
      <ul class="sector-legend">${look.sectors.map((row, index) =>
        `<li><i style="background:${palette[index % palette.length]}"></i>${esc(row.name_zh)} ${plain(row.weight)}</li>`).join('')}</ul>
      <div class="table-wrap"><table class="state-table exposure-table"><thead><tr>
        <th>股票</th><th>占總資產</th><th>直接持有</th><th>經由基金</th></tr></thead><tbody>
        ${look.top_positions.map(row => `<tr>
          <td><strong>${esc(row.ticker)}</strong>${row.overlap ? '<small class="pending">直接＋基金重疊</small>' : ''}</td>
          <td>${plain(row.weight, '%', 2)}</td><td>${plain(row.direct_weight, '%', 2)}</td>
          <td>${Object.entries(row.via_weight).map(([fund, w]) => `${esc(fund)} ${plain(w, '%', 2)}`).join('｜') || '—'}</td>
        </tr>`).join('')}</tbody></table></div>
      <p class="panel-desc">${esc(look.note)}。</p>`
      : `<p class="panel-desc">含基金看穿：${esc(look.reason || '尚無基金持股資料')}</p>`;
    target.innerHTML = `
      <h3 class="exposure-title">我的直接個股曝險</h3>
      <div class="env-evidence">
        <div><span>直接個股</span><strong>${coverage.priced_positions}／${coverage.total_positions} 檔</strong></div>
        <div><span>最大單一公司</span><strong>${esc(issuer.top1 ? issuer.top1.ticker : '—')} ${plain(issuer.top1 && issuer.top1.weight)}</strong></div>
        <div><span>前三大合計</span><strong>${plain(issuer.top3_weight)}</strong></div>
        <div><span>相當於幾檔等權個股</span><strong>${issuer.effective_positions ?? '—'}</strong></div>
        <div><span>相當於幾個等權板塊</span><strong>${exposure.sector_concentration.effective_sectors ?? '—'}</strong></div>
      </div>
      ${(exposure.needs_review || []).map(text => `<p class="notice">需要覆核：${esc(text)}</p>`).join('')}
      <div class="sector-bar" role="img" aria-label="直接個股的板塊權重">${bar}</div>
      <ul class="sector-legend">${legend}</ul>
      <div class="table-wrap"><table class="state-table exposure-table"><thead><tr>
        <th>持股／權重</th><th>板塊與狀態</th><th>次產業與狀態</th><th>研究優先度</th><th>原因</th>
      </tr></thead><tbody>${rows}</tbody></table></div>
      <p class="panel-desc">權重用最新市值計算（不是成本），股價截至 ${esc(exposure.price_as_of || '—')}；排除 ` +
      `${esc((exposure.excluded_funds || []).join('、') || '—')}。${esc(exposure.not_an_action)}。</p>` + lookHtml;
  }

  async function init() {
    const [research, rotation, backtest, digest, exposure, sensitivity, etfMomentum] = await Promise.all([
      getJSON('market_rotation_research.json'),
      getJSON('market_rotation.json'),
      getJSON('market_rotation_history/backtest/sector_results.json'),
      getJSON('market_rotation_daily_digest.json'),
      getJSON('portfolio_equity_exposure.json'),
      getJSON('market_rotation_history/backtest/sensitivity.json'),
      getJSON('market_rotation_history/backtest/sector_etf_momentum.json')
    ]);
    renderSensitivity(sensitivity);
    renderEtfMomentum(etfMomentum);
    renderDigest(digest);
    renderExposure(exposure);
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
