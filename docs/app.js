/* 美股 QDII 看板前端
 * - 静态数据（申购状态/限额/上一日净值）来自 data.json（Actions 每日生成）
 * - 盘中估值/涨跌：JSONP 直连 fundgz（<script> 绕过 CORS），每分钟刷新
 * - 场内溢价率：JSONP 直连腾讯行情，用「场内价 vs 盘中估值」估算
 */
let DATA = null;
let LOFMAP = {};          // 场外code -> 场内secid，如 "513100":"sh513100"
const LIVE = {};          // code -> { gsz, price } 盘中缓存

async function boot() {
  const [d, m] = await Promise.all([
    fetch('data.json?_=' + Date.now()).then(r => r.json()),
    fetch('lof_map.json?_=' + Date.now()).then(r => r.json()).catch(() => ({})),
  ]);
  DATA = d;
  LOFMAP = Object.fromEntries(
    Object.entries(m).filter(([k]) => !k.startsWith('_')));
  document.getElementById('meta').textContent =
    `数据更新：${DATA.updated_at}　来源：${DATA.source}`;
  render();
  refreshLive();
  setInterval(refreshLive, 60000);
}

// 场内可交易的基金：优先用手工映射，其次对「场内交易」的 ETF 按代码前缀推断
// （沪市 5 开头 -> sh，深市 15/16 开头 -> sz；场内 ETF 的基金代码本身就是交易代码）
function deriveSecid(f) {
  if (LOFMAP[f.code]) return LOFMAP[f.code];
  if (f.buy_status === '场内交易') return (f.code[0] === '5' ? 'sh' : 'sz') + f.code;
  return '';
}

function statusClass(s) {
  if (!s) return '';
  if (s.includes('暂停') || s.includes('封闭') || s.includes('终止')) return 'closed';
  if (s.includes('限') || s.includes('大额') || s.includes('限购')) return 'limit';
  if (s.includes('开放')) return 'open';
  return '';
}

function render() {
  const kw = (document.getElementById('search').value || '').trim();
  const flt = document.getElementById('filter').value;
  const app = document.getElementById('app');
  app.innerHTML = '';

  let nTotal = 0, nClosed = 0, nLimit = 0, nOpen = 0;

  for (const c of DATA.companies) {
    const funds = c.funds.filter(f => {
      const hit = !kw || (c.company + f.name + f.code).includes(kw);
      const cls = statusClass(f.buy_status);
      return hit && (!flt || cls === flt);
    });
    // 统计基于全量（不受搜索影响），下面单独算
    if (!funds.length) continue;

    const rows = funds.map(f => {
      const secid = deriveSecid(f);
      return `
      <tr data-code="${f.code}" data-secid="${secid}">
        <td>${f.code}</td>
        <td class="name">${f.name}${secid ? ' <small>·场内</small>' : ''}</td>
        <td><span class="badge ${statusClass(f.buy_status)}">${f.buy_status || '—'}</span></td>
        <td>${f.daily_limit || '—'}</td>
        <td>${f.nav ?? '—'}<br><small>${f.nav_date || ''}</small></td>
        <td class="live-gsz">—</td>
        <td class="live-zzl">—</td>
        <td class="live-prem">${secid ? '…' : '—'}</td>
      </tr>`;
    }).join('');

    app.insertAdjacentHTML('beforeend', `
      <section class="company">
        <h2>${c.company} <small>(${funds.length})</small></h2>
        <div class="table-wrap"><table>
          <thead><tr>
            <th>代码</th><th>名称</th><th>申购状态</th><th>单日限额</th>
            <th>上一日净值</th><th>盘中估值</th><th>估算涨跌</th><th>溢价率</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
      </section>`);
  }

  // 全量统计
  for (const c of DATA.companies) for (const f of c.funds) {
    nTotal++;
    const cls = statusClass(f.buy_status);
    if (cls === 'closed') nClosed++;
    else if (cls === 'limit') nLimit++;
    else if (cls === 'open') nOpen++;
  }
  document.getElementById('stats').innerHTML = `
    <div class="stat">基金总数<b>${nTotal}</b></div>
    <div class="stat">开放申购<b class="up" style="color:var(--open)">${nOpen}</b></div>
    <div class="stat">限购<b style="color:var(--limit)">${nLimit}</b></div>
    <div class="stat">暂停申购<b style="color:var(--closed)">${nClosed}</b></div>`;
}

/* ---------- 盘中实时 ---------- */
function refreshLive() {
  document.querySelectorAll('tr[data-code]').forEach(tr => {
    loadScript(`https://fundgz.1234567.com.cn/js/${tr.dataset.code}.js?_=${Date.now()}`);
    const secid = tr.dataset.secid;
    if (secid) {
      loadScript(`https://qt.gtimg.cn/q=${secid}&_=${Date.now()}`, () => onQuote(secid));
    }
  });
}

function loadScript(src, onload) {
  const s = document.createElement('script');
  s.src = src;
  s.onload = () => { if (onload) onload(); s.remove(); };
  s.onerror = () => s.remove();
  document.body.appendChild(s);
}

// fundgz 回调（接口固定调用 jsonpgz）
function jsonpgz(j) {
  const tr = document.querySelector(`tr[data-code="${j.fundcode}"]`);
  if (!tr) return;
  const zzl = parseFloat(j.gszzl);
  (LIVE[j.fundcode] ||= {}).gsz = parseFloat(j.gsz);
  tr.querySelector('.live-gsz').textContent = j.gsz;
  const cell = tr.querySelector('.live-zzl');
  cell.textContent = (zzl >= 0 ? '+' : '') + j.gszzl + '%';
  cell.className = 'live-zzl ' + (zzl >= 0 ? 'up' : 'down');
  recalcPremium(j.fundcode);
}

// 腾讯行情把结果写进全局变量 v_<secid>，形如 "1~名称~代码~当前价~..."
function onQuote(secid) {
  const raw = window['v_' + secid];
  if (!raw) return;
  const price = parseFloat(raw.split('~')[3]);
  const code = secid.replace(/^(sh|sz)/, '');
  if (price) { (LIVE[code] ||= {}).price = price; recalcPremium(code); }
}

// 溢价率 ≈ (场内价 - 盘中估值) / 盘中估值
function recalcPremium(code) {
  const tr = document.querySelector(`tr[data-code="${code}"]`);
  if (!tr || !tr.dataset.secid) return;
  const { price, gsz } = LIVE[code] || {};
  const base = gsz || parseFloat(tr.querySelector('.live-gsz').textContent);
  if (!price || !base) return;
  const prem = (price - base) / base * 100;
  const cell = tr.querySelector('.live-prem');
  cell.textContent = (prem >= 0 ? '+' : '') + prem.toFixed(2) + '%';
  cell.className = 'live-prem ' + (prem >= 0 ? 'up' : 'down');
}

document.getElementById('search').addEventListener('input', render);
document.getElementById('filter').addEventListener('change', render);
boot();
