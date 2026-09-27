// ETF research page: theme-ETF constituent health, the theme-ETF signal
// back-test and the sector-ETF momentum back-test.  Split from the rotation
// page so that page stays about the S&P 500 / Nasdaq-100 constituents.
// Every section degrades to a plain message when its file is not published yet.
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

  async function getJSON(path) {
    try {
      const response = await fetch(path, {cache: 'no-cache'});
      return response.ok ? await response.json() : null;
    } catch (error) {
      return null;
    }
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

  const HEALTH_TONE = {
    broad_advance: 'positive', narrow_advance: 'warning', mixed: 'neutral',
    narrow_decline: 'warning', broad_decline: 'negative', data_limited: 'neutral'
  };

  function flowText(flows) {
    if (!flows) return '—';
    const nport = flows.nport || {};
    const est = flows.estimated || {};
    const head = nport.net_3m_pct == null ? '—'
      : `<span class="${tone(nport.net_3m_pct)}">${signed(nport.net_3m_pct)}</span>`;
    const estimate = est.flow_20d_pct != null
      ? `估計 20 日 ${signed(est.flow_20d_pct)}` + (est.flow_5d_pct != null ? `｜5 日 ${signed(est.flow_5d_pct)}` : '')
      : `每日紀錄 ${est.sessions_recorded || 0}／21 天`;
    return `${head}<small>N-PORT ${esc(nport.months || '—')}</small><small>${estimate}</small>`;
  }

  function renderEtfHealth(health) {
    const body = document.getElementById('etfHealthBody');
    const note = document.getElementById('etfHealthNote');
    if (!body) return;
    if (!health) {
      body.innerHTML = '<tr><td colspan="8" class="panel-desc">尚未產出 etf_health.json：SEC 排程抓到主題 ETF 持股後，' +
        '下一次每日排程會產生。</td></tr>';
      return;
    }
    const rows = health.etfs.map(row => {
      const etf = row.etf;
      const top = row.concentration.top_contributors.map(item =>
        `${esc(item.ticker)} ${signed(item.contribution_pp, 'pp')}`).join('、');
      const flags = row.flags.map(flag =>
        `<span class="tag warning" title="${esc(health.flags[flag] || flag)}">${esc(health.flags[flag] || flag)}</span>`).join('');
      return `<tr>
        <td><strong>${esc(row.ticker)}</strong><small>${esc(row.theme)}</small></td>
        <td class="state ${HEALTH_TONE[row.state] || ''}">${esc(health.states[row.state] || row.state)}${flags ? `<div class="tags">${flags}</div>` : ''}</td>
        <td><span class="${tone(etf.rs20_pct)}">${signed(etf.rs20_pct, 'pp')}</span>
          <small>5 日 ${signed(etf.r5_pct)}｜20 日 ${signed(etf.r20_pct)}｜60 日 ${signed(etf.r60_pct)}</small></td>
        <td>${plain(row.breadth.above_ma50_equal_pct, '%', 0)}／${plain(row.breadth.above_ma50_weighted_pct, '%', 0)}
          <small>站上 20 日均線 ${plain(row.breadth.above_ma20_weighted_pct, '%', 0)}</small></td>
        <td><span class="${tone(row.returns.equal_minus_cap_pp)}">${signed(row.returns.equal_minus_cap_pp, 'pp')}</span>
          <small>等權 ${signed(row.returns.equal_weighted_r20_pct)}｜市值 ${signed(row.returns.cap_weighted_r20_pct)}</small></td>
        <td>${row.concentration.top3_share_pct == null ? '—' : plain(row.concentration.top3_share_pct, '%', 0)}
          <small>${top || '—'}</small></td>
        <td>${flowText(row.flows)}</td>
        <td>${plain(row.constituents.coverage_pct, '%', 0)}<small>${row.constituents.priced}／${row.constituents.common_stock} 檔｜` +
          `${esc(row.holdings_report_date || '—')}</small></td>
      </tr>`;
    });
    const missing = health.unavailable.map(row =>
      `<tr><td><strong>${esc(row.ticker)}</strong><small>${esc(row.theme)}</small></td>` +
      `<td colspan="7" class="panel-desc">${esc(row.reason)}</td></tr>`);
    body.innerHTML = rows.concat(missing).join('');
    if (note) {
      note.textContent = `${health.as_of} 收盤；SPY 20 日 ${signed(health.benchmark_r20_pct)}。` +
        `清單 ${health.etf_list_version}、規則 ${health.rule_version}。${health.note}`;
    }
  }

  const THEME_VERDICT_TONE = {
    supported: 'positive', partial_not_adoptable: 'warning', not_supported: 'negative', insufficient_sample: 'neutral'
  };

  function renderThemeSignals(result) {
    const target = document.getElementById('themeSignalSummary');
    if (!target) return;
    if (!result) {
      target.innerHTML = '<div class="panel-desc">主題 ETF 訊號回測尚未執行：會隨每月回測一起產生。</div>';
      return;
    }
    const cell = stats => stats && stats.months
      ? `<span class="${tone(stats.mean_ic)}">${stats.mean_ic}</span>` +
        `<small>${esc(stats.start)}～${esc(stats.end)}｜${stats.months} 個月` +
        `${stats.mean_ic_interval ? `｜區間 ${stats.mean_ic_interval[0]}～${stats.mean_ic_interval[1]}` : ''}</small>`
      : '—';
    const rows = result.signals.map(signal => `<tr>
        <td><strong>${esc(signal.label)}</strong><small>${signal.expected_sign == null ? '方向不預設' : '預期正向'}</small></td>
        <td class="state ${THEME_VERDICT_TONE[signal.verdict] || ''}">${esc(result.verdicts[signal.verdict] || signal.verdict)}</td>
        <td>${cell(signal.calibration)}</td>
        <td>${cell(signal.holdout)}<small>樣本外自 ${esc(signal.holdout_start)}</small></td>
        <td>${signal.all && signal.all.top3_minus_average_pp != null ? signed(signal.all.top3_minus_average_pp, 'pp') : '—'}` +
          `<small>前三名每月相對平均</small></td>
      </tr>`).join('');
    const coverage = result.holdings_coverage || {};
    target.innerHTML = `
      <h3 class="exposure-title">主題 ETF 訊號：哪一種訊號能排出下個月的強勢族群</h3>
      <p class="panel-desc">每月底用各訊號替 ${result.etfs.length} 檔主題 ETF（清單 ${esc(result.etf_list_version)}）排名，` +
      `和下個月相對等權平均的報酬比較排名相關（IC，` +
      '正值代表排名靠前的下個月較強）。持股類訊號只用當時已申報的 N-PORT（以申報日為準，不偷看未來）。' +
      `規則版本 ${esc(result.version)}，候選事先固定。</p>` +
      `<div class="table-wrap"><table class="state-table sensitivity-table"><thead><tr>` +
      '<th>訊號</th><th>判定</th><th>平均 IC（校準）</th><th>平均 IC（樣本外）</th><th>前三名</th>' +
      `</tr></thead><tbody>${rows}</tbody></table></div>` +
      `<p class="panel-desc">持股涵蓋：${coverage.etf_months_usable ?? 0}／${coverage.etf_months ?? 0} 個 ETF 月份達 ` +
      `${result.min_coverage_pct}%。限制：${esc((result.limitations || []).join('；'))}。</p>` +
      (result.earlier_lists || []).map(list => `<p class="panel-desc">較早的清單 ${esc(list.etf_list_version)}` +
        `（${list.etfs.length} 檔）照樣重算：` + list.signals.map(signal =>
          `${esc(signal.label)} ${esc(result.verdicts[signal.verdict] || signal.verdict)}` +
          `（IC ${signal.calibration.mean_ic ?? '—'}／${signal.holdout.mean_ic ?? '—'}）`).join('；') + '。</p>').join('');
  }

  const STATE_ORDER = ['broad_advance', 'narrow_advance', 'mixed', 'narrow_decline', 'broad_decline', 'data_limited'];

  function renderOverview(health, signals) {
    const target = document.getElementById('etfOverview');
    const asOf = document.getElementById('etfAsOf');
    if (asOf) asOf.textContent = health ? health.as_of : '尚無資料';
    if (!target) return;
    if (!health) {
      target.innerHTML = '<div class="panel-desc">尚未產出 etf_health.json。</div>';
      return;
    }
    const counts = STATE_ORDER.map(state => {
      const rows = health.etfs.filter(row => row.state === state);
      return rows.length ? `<div class="etf-count"><span class="state ${HEALTH_TONE[state] || ''}">` +
        `${esc(health.states[state])}</span><strong>${rows.length}</strong>` +
        `<small>${rows.map(row => esc(row.ticker)).join('、')}</small></div>` : '';
    }).join('');
    const verdicts = signals ? signals.signals.filter(signal => signal.verdict === 'supported').length : null;
    const conclusion = signals == null ? '訊號回測尚未執行。'
      : verdicts ? `${verdicts} 種訊號通過回測，詳見下方。`
        : `${signals.signals.length} 種訊號在 ${signals.etfs.length} 檔 ETF 上都沒有通過回測：` +
          '下表描述「現在的漲跌是廣泛還是集中」，不預測下個月哪個族群會強。';
    target.innerHTML = `<div class="etf-counts">${counts}</div>` +
      `<p class="panel-desc">${esc(health.as_of)} 收盤，${health.etfs.length} 檔有持股資料` +
      `${health.unavailable.length ? `、${health.unavailable.length} 檔尚無` : ''}；SPY 20 日 ` +
      `${signed(health.benchmark_r20_pct)}。${esc(conclusion)}</p>`;
  }

  async function init() {
    const [health, signals, momentum] = await Promise.all([
      getJSON('etf_health.json'),
      getJSON('market_rotation_history/backtest/theme_etf_signals.json'),
      getJSON('market_rotation_history/backtest/sector_etf_momentum.json')
    ]);
    renderOverview(health, signals);
    renderEtfHealth(health);
    renderThemeSignals(signals);
    renderEtfMomentum(momentum);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
