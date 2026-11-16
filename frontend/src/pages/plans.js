import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {badge} from '../components/common/status.js';import {field} from '../components/common/fields.js';
const tag=s=>({draft:'草案',active:'生效',cancelled:'已取消'})[s]||s;
const ts=x=>x?x.slice(0,19).replace('T',' '):'—';
function detailHtml(p){let r=p.result;
 const rows=a=>a.map(x=>`<tr><td>${esc(x.code)}</td><td>${esc(x.required_parts.join('、'))}</td><td>${esc(x.kit_names.join(' + '))}</td><td>${esc(x.union_parts.join('、'))}</td><td>${x.idle_parts.length?esc(x.idle_parts.join('、')):'—'}</td></tr>`).join('');
 const urows=r.uncovered.map(u=>`<tr><td>${esc(u.code)}</td><td>${esc(u.required_parts.join('、'))}</td><td>${u.missing.map(m=>`${esc(m.part)}（${esc(m.detail)}）`).join('；')}</td></tr>`).join('');
 return `<article class="rec" id="plandetail"><h3>#${p.id} ${esc(p.name)} ${badge(tag(p.state))}</h3>
 <div class="metrics"><div><strong>${r.covered}/${r.total}</strong>完整覆盖作业</div><div><strong>${r.idle_total}</strong>逐单闲置件总数</div><div><strong>${r.carried_count}/${r.carry_limit}</strong>携带件种</div></div>
 <p>携带件：${esc(r.carried_parts.join('、'))||'—'}<br>依据指纹 ${esc((p.fingerprint||'').slice(0,12))} · 创建 ${esc(ts(p.created_at))}${p.activated_at?` · 生效 ${esc(ts(p.activated_at))}`:''}${p.cancelled_at?` · 取消 ${esc(ts(p.cancelled_at))}`:''} · 求解 ${esc(r.solver)}</p>
 <h3>逐单对账 · 已覆盖 ${r.allocations.length} 单</h3>
 <div class="scroll"><table><thead><tr><th>作业</th><th>需要件</th><th>分配备件包</th><th>用件并集</th><th>闲置件</th></tr></thead><tbody>${rows(r.allocations)||'<tr><td>无</td></tr>'}</tbody></table></div>
 <h3>未覆盖 ${r.uncovered.length} 单 · 原因</h3>
 <div class="scroll"><table><thead><tr><th>作业</th><th>需要件</th><th>缺失件与原因</th></tr></thead><tbody>${urows||'<tr><td>全部覆盖</td></tr>'}</tbody></table></div></article>`}
export function render(){let approved=state.kits.filter(k=>k.status==='approved');
 return `<div class="split"><section class="panel"><h2>联备方案 / ${state.plans.length}</h2>
 <p>按作业与已签核备件包联合备料：每单可选多包、用件取并集、逐件对账；在携带件种上限内先最多完整覆盖作业，再最少逐单闲置件总数。草案不占用作业，确认生效才占用，取消即释放。</p>
 ${state.plans.map(p=>`<article class="rec"><h3>#${p.id} ${esc(p.name)} ${badge(tag(p.state))}</h3><p>覆盖 ${p.result.covered}/${p.result.total} · 闲置 ${p.result.idle_total} 件 · 携带 ${p.result.carried_count}/${p.carry_limit} 种</p><p>${p.state==='draft'?`<button data-confirm="${p.id}">确认生效</button> `:''}${p.state!=='cancelled'?`<button data-cancel="${p.id}">取消</button> `:''}<button data-detail="${p.id}">逐单对账</button></p></article>`).join('')||'<p class="notice">尚无联备方案。在右侧勾选作业与备件包后试算。</p>'}
 ${state.planDetail?detailHtml(state.planDetail):''}</section>
 <aside class="side"><h2>试算联合备料</h2><form id="plantrial">
 ${field('方案名称','name','text','required value="班组联合备料方案"')}
 ${field('携带件种上限','carry_limit','number','min=1 max=12 step=1 value=6 required')}
 <label>设备过滤<select id="jobfilter"><option value="">全部设备</option><option>泵组</option><option>压缩机</option><option>风机</option></select></label>
 <fieldset class="checks"><legend>参与作业</legend><p><button type="button" data-checkall>全选</button> <button type="button" data-checknone>清空</button></p>
 <div class="checklist">${state.jobs.map(j=>`<label class="check" data-equ="${esc(j.equipment)}"><input type="checkbox" name="job_ids" value="${j.id}" ${j.occupied_by?'disabled':''} ${j.occupied_by?'':'checked'}>${esc(j.code)} · ${esc(j.parts.join('+'))}${j.occupied_by?` · 方案#${j.occupied_by}占用`:''}</label>`).join('')}</div></fieldset>
 <fieldset class="checks"><legend>已签核备件包</legend><div class="checklist">${approved.map(k=>`<label class="check"><input type="checkbox" name="kit_ids" value="${k.id}" checked>${esc(k.name)} · ${esc(k.parts.join('+'))}</label>`).join('')||'暂无已签核备件包'}</div></fieldset>
 <button class="primary">试算联合备料</button></form>
 <p>试算生成草案，不占用作业；确认时若作业已修订或来源包已变化，将拒绝生效并要求重新试算。</p></aside></div>`}
