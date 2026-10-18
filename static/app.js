const $ = (id) => document.getElementById(id);
let entries=[], selected=null, aiConfigured=false;
const SCHEMAS={
  learners:'learner_id, family_id, guardian_alias, store_id, contact_consent (yes/no)',
  packages:'package_id, learner_id, course_type, purchased_on (YYYY-MM-DD), expires_on, purchased_sessions, remaining_sessions, price_cny',
  attendance:'event_id, learner_id, session_date (YYYY-MM-DD), status (present / absent / excused)',
  renewals:'renewal_id, learner_id, source_package_id, paid_on (YYYY-MM-DD), amount_cny, status (paid / refunded / void)',
  contracts:'contract_id, learner_id, source_package_id, signed_on (YYYY-MM-DD), contracted_amount_cny',
  cash_events:'event_id, contract_id, event_on (YYYY-MM-DD), kind (payment / refund), amount_cny, refund_of (refund must reference payment event; payment blank)'
};
const fmtMoney=(n)=> n==null?'—':'¥'+Number(n).toLocaleString('zh-CN',{maximumFractionDigits:2});
const el=(tag, text, cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;};
const clear=(node)=>{while(node.firstChild)node.firstChild.remove();};
function toast(message){$('toast').textContent=message;$('toast').style.display='block';clearTimeout(window._toastTimeout);window._toastTimeout=setTimeout(()=>$('toast').style.display='none',4200);}
async function call(url,options={}){let response=await fetch(url,options);let data=await response.json().catch(()=>({}));if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'服务暂时不可用');return data;}
function showView(name){document.querySelectorAll('.page').forEach(n=>n.classList.toggle('visible',n.id===name));document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name));const conf={opportunities:['续费机会池','把续费机会变成行动','基于事实识别需要关注的客户，辅助员工跟进，记录真实成交。'],insights:['经营验证','衡量真实经营贡献','流水不等于增量价值。没有成熟实验，不声称AI带来收益。'],import:['CSV数据导入','独立的数据接入方式','不依赖奥冠系统；当前只允许导入合法授权的去识别化数据。']}[name];$('viewName').textContent=conf[0];$('pageTitle').textContent=conf[1];$('pageDescription').textContent=conf[2];}
function tag(arm){return arm==='ai'?'AI组':arm==='rules'?'规则组':'对照组';}
function renderList(){const q=$('search').value.trim().toLowerCase(),arm=$('arm').value;let list=entries.filter(r=>(arm==='all'||r.arm===arm)&&[r.learner_id,r.guardian_alias,r.course_type].join('|').toLowerCase().includes(q));$('listCount').textContent=list.length;const target=$('opportunityList');clear(target);if(!list.length){target.append(el('div','没有匹配的续费机会。','empty'));return;}
  list.forEach(r=>{const btn=el('button',undefined,'opp-row'+(selected===r.opportunity_id?' selected':''));btn.type='button';const icon=el('div',r.learner_id.slice(-2),'opp-icon');const main=el('div',undefined,'opp-main');main.append(el('strong',r.guardian_alias+' · '+r.learner_id),el('p',r.reason));const meta=el('div',undefined,'opp-meta');meta.append(el('span','优先级 '+r.priority,'score'),el('span',tag(r.arm),'tag '+r.arm));btn.append(icon,main,meta);btn.addEventListener('click',()=>{selected=r.opportunity_id;renderList();renderDetail();});target.append(btn);});
}
function renderDetail(){let r=entries.find(x=>x.opportunity_id===selected);let node=$('detail');clear(node);if(!r){node.append(el('div','← 从左侧选择客户，查看证据与行动','empty large'));return;}
  node.append(el('div','RENEWAL OPPORTUNITY · '+r.opportunity_id,'detail-eyebrow'));
  let title=el('div',undefined,'detail-title');title.append(el('h2',r.guardian_alias+' · '+r.learner_id),el('span',tag(r.arm),'tag '+r.arm));node.append(title,el('div',r.course_type+' · '+r.store_id+' · 到期 '+r.expires_on,'detail-subtitle'),el('div',undefined,'divider'),el('h3','信号依据 · 仅做事实判断'));
  let signals=el('div',undefined,'signals');for(let [text,value] of [['剩余课时',r.signals.remaining_sessions+' 节'],['到期倒计时',r.signals.days_to_expiry+' 天'],['前28天到课',r.signals.attendance_previous_28d+' 次'],['近28天到课',r.signals.attendance_recent_28d+' 次']])signals.append(el('span',text+'：'+value,'signal'));node.append(signals,el('div',undefined,'divider'),el('h3','建议采取的行动'));
  node.append(el('div',r.arm==='control'?'正常服务对照组：本产品不提供额外定向建议。':r.rule_advice,'advice'));if(r.model_advice){
    node.append(el('div','结构化模型建议 ['+r.model_source+'] · '+(r.model_review_status==='approved'?'人工已确认':r.model_review_status==='rejected'?'人工已拒绝':'待人工审核')+'：'+r.model_advice,'advice source'));
    node.append(el('p','未知事项：'+r.model_uncertainty,'small'));
    let review=el('div',undefined,'header-actions');
    [['approved','人工认可'],['rejected','拒绝建议']].forEach(([decision,label])=>{
      let b=el('button',label,'button light');b.type='button';b.addEventListener('click',async()=>{
        let reviewer=prompt('请输入审核员工代号（仅记录代号，不填写敏感信息）');if(!reviewer||!reviewer.trim())return;
        b.disabled=true;
        try{await call('/api/opportunities/'+encodeURIComponent(r.opportunity_id)+'/ai-review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewer:reviewer.trim(),decision})});toast('人工审核已记录；这不代表建议已产生续费增量。');await refresh();}catch(e){toast(e.message)}finally{b.disabled=false;}
      });review.append(b);
    });node.append(review);
  }
  if(r.arm==='ai'){
    let b=el('button','请求真实AI建议','button light');b.style.marginTop='13px';b.disabled=!aiConfigured;b.title=aiConfigured?'真实模型API已经配置':'未配置真实模型API';b.addEventListener('click',async()=>{b.disabled=true;try{await call('/api/opportunities/'+encodeURIComponent(r.opportunity_id)+'/ai-advice',{method:'POST'});toast('结构化模型建议通过机器检查，仍需员工审核。');await refresh();}catch(e){toast(e.message)}finally{b.disabled=!aiConfigured;}});node.append(b);
  }
  node.append(el('div',undefined,'divider'),el('h3','跟进记录 · 仅员工人工执行'));
  if(r.arm==='control'){node.append(el('div','对照组只保留正常既有服务，不实施本产品额外定向触达。','detail-note'));attachTimeline(node,r);return;}
  let form=el('form',undefined,'detail-form');let ownerLabel=el('label','责任人'),owner=el('input');owner.placeholder='例如：值班顾问';owner.value=r.last_owner||'';owner.required=true;owner.maxLength=50;ownerLabel.append(owner);
  let statusLabel=el('label','跟进状态'),sel=el('select');[['planned','计划中'],['contacted','已联系'],['no_response','未响应'],['not_suitable','暂不适合营销'],['closed','已结束']].forEach(([v,t])=>{let opt=el('option',t);opt.value=v;sel.append(opt);});statusLabel.append(sel);
  let noteLabel=el('label','结果与下一步','wide'),note=el('textarea');note.placeholder='记录下一步行动，不填写敏感个人信息';note.rows=3;note.maxLength=1000;noteLabel.append(note);
  let submit=el('button','保存跟进记录','button primary');submit.type='submit';submit.className+=' wide';form.append(ownerLabel,statusLabel,noteLabel,submit);
  form.addEventListener('submit',async(e)=>{e.preventDefault();submit.disabled=true;try{await call('/api/followups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opportunity_id:r.opportunity_id,owner:owner.value,status:sel.value,note:note.value})});toast('跟进记录已保存');await refresh();}catch(x){toast(x.message);}finally{submit.disabled=false;}});
  node.append(form);
  attachTimeline(node,r);
}
function attachTimeline(node,r){
  let timelineButton=el('button','查看课包→合同→付款/退款时间线','button light');timelineButton.style.marginTop='14px';node.append(timelineButton);
  let eventsBlock=el('div',undefined,'event-lines');node.append(eventsBlock);
  timelineButton.addEventListener('click',async()=>{try{
    const data=await call('/api/cycles/'+encodeURIComponent(r.package_id)+'/timeline');clear(eventsBlock);
    data.events.forEach(ev=>eventsBlock.append(el('div',ev.event_at+' · '+ev.event_type+' · '+ev.reference_id+(ev.amount_cny!=null?' · '+fmtMoney(ev.amount_cny):''),'event-line')));
    eventsBlock.append(el('p',data.disclaimer,'small'));
  }catch(e){toast(e.message);}});
}
function renderReport(data){$('netPaid').textContent=fmtMoney(data.net_paid_cny);$('followupEvents').textContent=data.followup_records;$('attributionNote').textContent=data.attribution_note;let holder=$('armBars');clear(holder);const n=Math.max(1,...Object.values(data.arm_family_counts));[['control','正常运营'],['rules','规则辅助'],['ai','AI辅助']].forEach(([arm,name])=>{let line=el('div',undefined,'arm-row');line.append(el('span',name));let track=el('div',undefined,'track');let fill=el('div',undefined,'fill');fill.style.width=(100*data.arm_family_counts[arm]/n)+'%';track.append(fill);line.append(track,el('strong',data.arm_family_counts[arm]+'户'));holder.append(line);});}
async function refresh(){try{const [data,r,status,cohorts]=await Promise.all([call('/api/opportunities'),call('/api/report'),call('/api/health'),call('/api/cohorts')]);entries=data.items;aiConfigured=status.ai_configured;const named=aiConfigured?'真实AI已配置':'规则模式（未配置AI）';$('modelStatus').textContent=named;$('statAI').textContent=aiConfigured?'可调用':'未连接';$('statCount').textContent=entries.length;$('statHigh').textContent=entries.filter(x=>x.priority>=65).length;$('statFollowed').textContent=entries.filter(x=>x.last_status).length;$('modelBenchmark').disabled=!aiConfigured;renderList();renderDetail();renderReport(r);renderCohorts(cohorts.items);}catch(e){toast(e.message);}}
document.querySelectorAll('.nav').forEach(n=>n.addEventListener('click',()=>showView(n.dataset.view)));
$('loadDemo').addEventListener('click',async()=>{if(entries.length&&!confirm('重新载入合成数据会清空本地当前所有导入和跟进记录，确定继续吗？'))return;try{await call('/api/demo/reset',{method:'POST'});selected=null;toast('已载入36名合成学员，所有数据均为模拟');await refresh();}catch(e){toast(e.message);}});
$('recompute').addEventListener('click',async()=>{try{const r=await call('/api/recompute',{method:'POST'});toast('重新识别完成，得到'+r.opportunities+'条有效机会');await refresh();}catch(e){toast(e.message);}});
function renderCohorts(cohorts){let container=$('cohortReports');clear(container);if(!cohorts.length){container.append(el('p','尚无已冻结队列；冻结前的机会池不构成实验样本。','small'));return;}
  cohorts.forEach(c=>{let card=el('div',undefined,'cohort-card');card.append(el('strong',c.store_id+' · '+c.opened_on+' · '+(c.mature?'观察期结束':'观察中')));
    let detail=el('div',undefined,'cohort-grid');[['control','正常运营'],['rules','规则辅助'],['ai','AI辅助']].forEach(([arm,title])=>{
      let a=c.arms[arm];detail.append(el('div',title+'：'+a.eligible_families+'户 · 实际净收款'+fmtMoney(a.net_paid_cny),'cohort-arm'));
    });card.append(detail,el('p',c.attribution_note,'small'));container.append(card);});
}
$('freezeCohort').addEventListener('click',async()=>{let store=$('cohortStore').value.trim();if(!store){toast('请输入门店代号');return;}
  try{const c=await call('/api/cohorts/freeze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({store_id:store})});
   toast('冻结完成：'+Object.values(c.arms).reduce((x,a)=>x+a.member_packages,0)+'个合格课包，重复调用不会修改冻结结果');await refresh();
  }catch(e){toast(e.message);}});
$('search').addEventListener('input',renderList);$('arm').addEventListener('change',renderList);
$('importKind').addEventListener('change',()=>{$('schemaText').textContent=SCHEMAS[$('importKind').value];});$('schemaText').textContent=SCHEMAS.learners;
$('upload').addEventListener('click',async()=>{const file=$('csvFile').files[0];if(!file){toast('先选择CSV文件');return;}if(file.size>2*1024*1024){toast('文件超过2MB');return;}let btn=$('upload');btn.disabled=true;try{let r=await call('/api/import/'+$('importKind').value,{method:'POST',headers:{'Content-Type':'text/csv; charset=utf-8'},body:await file.arrayBuffer()});toast('已导入'+r.imported+'条；全部数据导入后请重新计算');$('importHint').textContent=r.message;}catch(e){toast(e.message)}finally{btn.disabled=false;}});
refresh();

function recalcScenario(){const p=Number($('calcPrice').value),m=Number($('calcMargin').value),c=Number($('calcCost').value),n=Number($('calcCustomers').value);if(p<=0||m<=0||m>100||c<0||n<=0){$('calcDeals').textContent='参数无效';$('calcUplift').textContent='—';return;}const deals=Math.ceil(c/(p*m/100));$('calcDeals').textContent=deals+' 单';$('calcUplift').textContent=(deals/n*100).toFixed(1)+' 个百分点';}
['calcPrice','calcMargin','calcCost','calcCustomers'].forEach(x=>$(x).addEventListener('input',recalcScenario));recalcScenario();

// G0.4: Evaluation is explicit user action, never part of automatic refresh.
$('baselineTest').addEventListener('click',async()=>{
  try{const r=await call('/api/quality/baseline');$('qualityBaseline').textContent=r.machine_passed+'/'+r.cases;
  $('qualityDetails').textContent='规则基线：'+r.disclaimer;}
  catch(e){toast(e.message);}
});
$('modelBenchmark').addEventListener('click',async()=>{
  if(!aiConfigured){toast('没有配置真实模型，无法运行真实模型评测');return;}
  if(!confirm('将调用真实模型最多4次，仅使用合成业务信号，可能产生API费用。继续？'))return;
  const btn=$('modelBenchmark');btn.disabled=true;
  try{const r=await call('/api/quality/benchmark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_cases:4})});
    $('qualityModel').textContent=r.machine_passed+'/'+r.cases;
    $('qualityDetails').textContent=r.results.map(x=>x.case_id+': '+(x.accepted?'通过':'拒绝 ('+x.reason+')')).join(' | ')+'。'+r.disclaimer;
  }catch(e){toast(e.message);}finally{btn.disabled=!aiConfigured;}
});