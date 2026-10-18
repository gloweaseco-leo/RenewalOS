const $ = (id) => document.getElementById(id);
let entries=[], selected=null, aiConfigured=false, tasks=[], taskSelected=null;
const todayISO=()=>new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
const eventId=(prefix)=>prefix+'-'+(crypto.randomUUID?crypto.randomUUID():Math.random().toString(36).slice(2));
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
function showView(name){document.querySelectorAll('.page').forEach(n=>n.classList.toggle('visible',n.id===name));document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name));const conf={opportunities:['续费机会池','把续费机会变成行动','基于事实识别需要关注的客户，辅助员工跟进，记录真实成交。'],tasks:['销售待办','今日销售任务与结果追踪','任务分配、到期提醒、操作历史与续费合同事实保持关联。'],insights:['经营验证','衡量真实经营贡献','流水不等于增量价值。没有成熟实验，不声称AI带来收益。'],import:['CSV数据导入','独立的数据接入方式','不依赖奥冠系统；当前只允许导入合法授权的去识别化数据。']}[name];$('viewName').textContent=conf[0];$('pageTitle').textContent=conf[1];$('pageDescription').textContent=conf[2];}
function tag(arm){return arm==='ai'?'AI组':arm==='rules'?'规则组':'对照组';}
function renderList(){const q=$('search').value.trim().toLowerCase(),arm=$('arm').value,status=$('status').value;let list=entries.filter(r=>(arm==='all'||r.arm===arm)&&(status==='all'||(status==='active'?r.is_active:!r.is_active))&&[r.learner_id,r.guardian_alias,r.course_type].join('|').toLowerCase().includes(q));$('listCount').textContent=list.length;const target=$('opportunityList');clear(target);if(!list.length){target.append(el('div','没有匹配的续费机会。','empty'));return;}
  list.forEach(r=>{const btn=el('button',undefined,'opp-row'+(selected===r.opportunity_id?' selected':''));btn.type='button';const icon=el('div',r.learner_id.slice(-2),'opp-icon');const main=el('div',undefined,'opp-main');main.append(el('strong',r.guardian_alias+' · '+r.learner_id),el('p',r.reason));const meta=el('div',undefined,'opp-meta');meta.append(el('span',r.is_active?'优先级 '+r.priority:'已结束/归档',r.is_active?'score':'tag'),el('span',tag(r.arm),'tag '+r.arm));btn.append(icon,main,meta);btn.addEventListener('click',()=>{selected=r.opportunity_id;renderList();renderDetail();});target.append(btn);});
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
  if(r.arm==='ai' && r.is_active){
    let b=el('button','请求真实AI建议','button light');b.style.marginTop='13px';b.disabled=!aiConfigured;b.title=aiConfigured?'真实模型API已经配置':'未配置真实模型API';b.addEventListener('click',async()=>{b.disabled=true;try{await call('/api/opportunities/'+encodeURIComponent(r.opportunity_id)+'/ai-advice',{method:'POST'});toast('结构化模型建议通过机器检查，仍需员工审核。');await refresh();}catch(e){toast(e.message)}finally{b.disabled=!aiConfigured;}});node.append(b);
  }
  node.append(el('div',undefined,'divider'),el('h3','跟进记录 · 仅员工人工执行'));
  if(!r.is_active){node.append(el('div','此机会已归档：保留完整事实链，但不允许继续创建额外营销跟进。','detail-note'));attachFollowupHistory(node,r);attachSalesPanel(node,r);attachTimeline(node,r);return;}
  if(r.arm==='control'){node.append(el('div','对照组只保留正常既有服务，不实施本产品额外定向触达。成交记录只是业务事实，不是额外触达。','detail-note'));attachFollowupHistory(node,r);attachSalesPanel(node,r);attachTimeline(node,r);return;}
  let form=el('form',undefined,'detail-form');let ownerLabel=el('label','责任人'),owner=el('input');owner.placeholder='例如：值班顾问';owner.value=r.last_owner||'';owner.required=true;owner.maxLength=50;ownerLabel.append(owner);
  let statusLabel=el('label','跟进状态'),sel=el('select');[['planned','计划中'],['contacted','已联系'],['no_response','未响应'],['not_suitable','暂不适合营销'],['closed','已结束']].forEach(([v,t])=>{let opt=el('option',t);opt.value=v;sel.append(opt);});statusLabel.append(sel);
  let noteLabel=el('label','结果与下一步','wide'),note=el('textarea');note.placeholder='记录下一步行动，不填写敏感个人信息';note.rows=3;note.maxLength=1000;noteLabel.append(note);
  let submit=el('button','保存跟进记录','button primary');submit.type='submit';submit.className+=' wide';form.append(ownerLabel,statusLabel,noteLabel,submit);
  form.addEventListener('submit',async(e)=>{e.preventDefault();submit.disabled=true;try{await call('/api/followups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opportunity_id:r.opportunity_id,owner:owner.value,status:sel.value,note:note.value})});toast('跟进记录已保存');await refresh();}catch(x){toast(x.message);}finally{submit.disabled=false;}});
  node.append(form);
  attachTaskPanel(node,r);
  attachFollowupHistory(node,r);
  attachSalesPanel(node,r);
  attachTimeline(node,r);
}
function attachFollowupHistory(node,r){
  const history=el('div',undefined,'event-lines');
  node.append(history);
  call('/api/followups/'+encodeURIComponent(r.opportunity_id)).then(data=>{
    if(selected!==r.opportunity_id)return;
    clear(history);
    if(!data.items.length){history.append(el('p','暂无跟进记录。','small'));return;}
    data.items.slice(0,30).forEach(e=>history.append(el('div',e.logged_at+' · '+e.owner+' · '+e.status+(e.note?' · '+e.note:''),'event-line')));
  }).catch(()=>{if(selected===r.opportunity_id)history.append(el('p','跟进记录暂不可读取。','small'));});
}

// G0.6: this records SIMULATED contract and cash facts on localhost only.
// No payment processor is integrated and no UI can claim the result is actual cash.
function attachSalesPanel(node,r){
  node.append(el('div',undefined,'divider'),el('h3','合成续费成交模拟 · 不是真实收款'));
  const holder=el('section',undefined,'sale-panel');
  holder.append(el('p','在本机生成可追溯的合成合同、付款与退款。用于验证完整产品流程，不得作为客户实际成交证明。','small'));
  const content=el('div',undefined,'sale-content');holder.append(content);node.append(holder);
  const labelInput=(name,type,value)=>{
    const label=el('label',name),input=el('input');input.type=type;input.required=true;
    if(value!==undefined)input.value=value;
    if(type==='number'){input.min='0.01';input.max='1000000';input.step='0.01';}
    if(type==='date')input.max=todayISO();
    label.append(input);return [label,input];
  };
  const request=async(path,payload,button)=>{
    button.disabled=true;
    try{await call(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      toast('已写入合成交易事实，真实收款及AI增量尚未验证。');
      const desired=$('status');desired.value='all';await refresh();
    }catch(e){toast(e.message);button.disabled=false;}
  };
  const load=async()=>{
    try{
      const sale=await call('/api/demo/sales/'+encodeURIComponent(r.package_id));
      if(selected!==r.opportunity_id)return;
      clear(content);
      if(!sale.contract){
        const form=el('form',undefined,'detail-form');const [amountLabel,amount]=labelInput('新续费合同金额（合成元）','number','2600.00');
        const [dateLabel,day]=labelInput('签署日期','date',todayISO());
        const btn=el('button','创建合成续费合同','button primary');btn.type='submit';btn.className+=' wide';
        form.append(amountLabel,dateLabel,btn);
        const cid=eventId('DC');
        form.addEventListener('submit',e=>{e.preventDefault();request('/api/demo/sales/contracts',{contract_id:cid,source_package_id:r.package_id,amount_cny:amount.value,signed_on:day.value},btn);});
        content.append(form);return;
      }
      content.append(el('p','合同 '+sale.contract.contract_id+' · 签署 '+sale.contract.signed_on+' · 约定 '+fmtMoney(sale.contract.amount_cny)+' · 净收款 '+fmtMoney(sale.net_paid_cny),'small'));
      const pays=sale.payments.filter(p=>p.kind==='payment');
      const refunds=sale.payments.filter(p=>p.kind==='refund');
      const history=el('div',undefined,'event-lines');
      sale.payments.forEach(p=>history.append(el('div',p.event_on+' · '+(p.kind==='payment'?'模拟付款':'模拟退款')+' · '+fmtMoney(p.amount_cny)+' · '+p.event_id,'event-line')));
      content.append(history);
      const amountRemaining=Math.round((sale.contract.amount_cny-pays.reduce((a,p)=>a+p.amount_cny,0))*100)/100;
      if(amountRemaining>0){
        const form=el('form',undefined,'detail-form'),[moneyLabel,money]=labelInput('模拟付款金额（元）','number',String(amountRemaining)),[dateLabel,day]=labelInput('付款日期','date',todayISO());
        const id=eventId('DP'),btn=el('button','记录合成付款','button primary');btn.type='submit';btn.className+=' wide';
        form.append(moneyLabel,dateLabel,btn);form.addEventListener('submit',e=>{e.preventDefault();request('/api/demo/sales/payments',{contract_id:sale.contract.contract_id,event_id:id,event_on:day.value,amount_cny:money.value},btn);});
        content.append(form);
      }
      const refundable=pays.filter(p=>p.refundable_cny>0);
      if(refundable.length){
        const form=el('form',undefined,'detail-form'),chooseLabel=el('label','关联原付款'),choose=el('select');
        refundable.forEach(p=>{let opt=el('option',p.event_id+' · 可退'+fmtMoney(p.refundable_cny));opt.value=p.event_id;choose.append(opt);});chooseLabel.append(choose);
        const [moneyLabel,money]=labelInput('模拟退款金额（元）','number',String(refundable[0].refundable_cny));
        const [dateLabel,day]=labelInput('退款日期','date',todayISO());
        const id=eventId('DR'),btn=el('button','记录合成退款','button light');btn.type='submit';btn.className+=' wide';
        choose.addEventListener('change',()=>{money.value=String(refundable.find(p=>p.event_id===choose.value).refundable_cny);});
        form.append(chooseLabel,moneyLabel,dateLabel,btn);
        form.addEventListener('submit',e=>{e.preventDefault();request('/api/demo/sales/refunds',{payment_event_id:choose.value,event_id:id,event_on:day.value,amount_cny:money.value},btn);});
        content.append(form);
      }
      content.append(el('p',sale.disclaimer,'small'));
    }catch(e){if(selected===r.opportunity_id)content.append(el('p','合成交易事实读取失败：'+e.message,'detail-note'));}
  };
  load();
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
async function refresh(){try{const [data,r,status,cohorts,queue]=await Promise.all([call('/api/opportunities?include_archived=true'),call('/api/report'),call('/api/health'),call('/api/cohorts'),call('/api/tasks')]);entries=data.items;aiConfigured=status.ai_configured;const named=aiConfigured?'真实AI已配置':'规则模式（未配置AI）';$('modelStatus').textContent=named;$('statAI').textContent=aiConfigured?'可调用':'未连接';$('statCount').textContent=entries.filter(x=>x.is_active).length;$('statHigh').textContent=entries.filter(x=>x.is_active&&x.priority>=65).length;$('statFollowed').textContent=entries.filter(x=>x.last_status).length;$('modelBenchmark').disabled=!aiConfigured;renderList();renderDetail();renderReport(r);renderCohorts(cohorts.items);tasks=queue.items;renderTasks(queue.summary);}catch(e){toast(e.message);}}
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
$('search').addEventListener('input',renderList);$('arm').addEventListener('change',renderList);$('status').addEventListener('change',renderList);
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
    $('qualityDetails').textContent='本轮真实模型机器验收：'+r.results.map(x=>x.case_id+': '+(x.accepted?'通过':'拒绝 ('+x.reason+')')).join(' | ')+'。平均延迟：'+(r.average_latency_ms===null?'未知':r.average_latency_ms+'毫秒')+'；Token费用：需在CLI提供模型定价后单独测算；AI效果/ROI：尚未证明。';
  }catch(e){toast(e.message);}finally{btn.disabled=!aiConfigured;}
});

// G0.7: manager-assigned synthetic work queue. No login identity or auto-outreach.
const taskStateName={open:'待执行',in_progress:'处理中',waiting:'等待回复',done:'已完成',cancelled:'已取消'};
const taskDueName={overdue:'逾期',today:'今日',upcoming:'未来',resolved:'已结束'};
function taskJson(path,method,payload){return call(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
function attachTaskPanel(node,r){
  const panel=el('section',undefined,'sale-panel');
  panel.append(el('h3','任务分配 · 只用于授权经营跟进'));
  const holder=el('div',undefined,'task-create-panel');panel.append(holder);node.append(panel);
  const render=async()=>{
    try{
      const data=await call('/api/tasks?store_id='+encodeURIComponent(r.store_id));
      if(selected!==r.opportunity_id)return;
      clear(holder);
      const existing=data.items.find(x=>x.opportunity_id===r.opportunity_id);
      if(existing){
        holder.append(el('p','已分配给 '+existing.owner+' · '+existing.due_on+' · '+taskStateName[existing.status],'small'));
        const btn=el('button','进入销售待办','button light');btn.addEventListener('click',()=>{taskSelected=existing.task_id;showView('tasks');renderTasks();});holder.append(btn);
        return;
      }
      const form=el('form',undefined,'detail-form');
      const ownerLabel=el('label','责任员工代号'),owner=el('input');owner.required=true;owner.maxLength=50;owner.placeholder='顾问A';ownerLabel.append(owner);
      const dueLabel=el('label','任务截止日期'),due=el('input');due.type='date';due.required=true;due.value=todayISO();dueLabel.append(due);
      const noteLabel=el('label','交接说明'),note=el('textarea');note.maxLength=1000;note.rows=2;note.placeholder='仅描述业务行动，不填写联系方式或敏感信息';noteLabel.append(note);
      const btn=el('button','创建员工跟进任务','button primary');btn.type='submit';btn.className+=' wide';form.append(ownerLabel,dueLabel,noteLabel,btn);
      form.addEventListener('submit',async ev=>{ev.preventDefault();btn.disabled=true;try{
        await taskJson('/api/tasks','POST',{opportunity_id:r.opportunity_id,owner:owner.value,due_on:due.value,note:note.value});
        toast('已分配任务；不代表已经联系客户。');await refresh();
      }catch(e){toast(e.message);btn.disabled=false;}});
      holder.append(form);
    }catch(e){holder.append(el('p','任务信息不可用：'+e.message,'detail-note'));}
  };render();
}
function renderTasks(summary){
  summary=summary||{open:tasks.filter(x=>['open','in_progress','waiting'].includes(x.status)).length,
    due_today:tasks.filter(x=>x.due_bucket==='today').length,overdue:tasks.filter(x=>x.due_bucket==='overdue').length,
    resolved:tasks.filter(x=>x.due_bucket==='resolved').length};
  const store=$('taskStore').value.trim(), owner=$('taskOwner').value.trim().toLowerCase(),due=$('taskDue').value;
  const filtered=tasks.filter(t=>(!store||t.store_id===store)&&(!owner||t.owner.toLowerCase()===owner)&&(due==='all'||t.due_bucket===due));
  const scoped=tasks.filter(t=>(!store||t.store_id===store)&&(!owner||t.owner.toLowerCase()===owner));
  $('taskStatOpen').textContent=scoped.filter(t=>['open','in_progress','waiting'].includes(t.status)).length;
  $('taskStatToday').textContent=scoped.filter(t=>t.due_bucket==='today').length;
  $('taskStatOverdue').textContent=scoped.filter(t=>t.due_bucket==='overdue').length;
  $('taskStatResolved').textContent=scoped.filter(t=>t.due_bucket==='resolved').length;
  $('taskListCount').textContent=filtered.length;
  clear($('taskList'));
  if(!filtered.length)$('taskList').append(el('div','没有符合条件的员工任务。请先在续费机会详情创建。','empty'));
  filtered.forEach(t=>{
    const b=el('button',undefined,'opp-row'+(taskSelected===t.task_id?' selected':''));b.type='button';
    b.append(el('div',t.due_on.slice(5),'opp-icon'));
    const label=el('div',undefined,'opp-main');label.append(el('strong',t.guardian_alias+' · '+t.owner),el('p',t.store_id+' · '+t.course_type+' · 截止 '+t.due_on));b.append(label);
    const tags=el('div',undefined,'opp-meta');tags.append(el('span',taskStateName[t.status],'tag'),el('span',taskDueName[t.due_bucket],'tag'));b.append(tags);
    b.addEventListener('click',()=>{taskSelected=t.task_id;renderTasks();});$('taskList').append(b);
  });
  const active=filtered.find(x=>x.task_id===taskSelected);
  if(!active)taskSelected=filtered.length?filtered[0].task_id:null;
  renderTaskDetail(filtered.find(x=>x.task_id===taskSelected));
}
function renderTaskDetail(t){
  const host=$('taskDetail');clear(host);
  if(!t){host.append(el('div','← 选择任务查看操作','empty large'));return;}
  host.append(el('div','WORK TASK · '+t.task_id,'detail-eyebrow'));
  host.append(el('h2',t.guardian_alias+' · '+t.learner_id),el('div','门店 '+t.store_id+' · '+taskStateName[t.status]+' · 截止 '+t.due_on,'detail-subtitle'));
  host.append(el('p','已登记的模拟净收款：'+fmtMoney(t.net_paid_cny)+'。这不是AI增量收益。','small'));
  const link=el('button','查看关联续费机会','button light');link.addEventListener('click',()=>{selected=t.opportunity_id;$('status').value='all';showView('opportunities');renderList();renderDetail();});host.append(link);
  host.append(el('div',undefined,'divider'));
  const frm=el('form',undefined,'detail-form');
  const ol=el('label','负责人代号'),o=el('input');o.value=t.owner;o.required=true;o.maxLength=50;ol.append(o);
  const dl=el('label','截止日期'),d=el('input');d.type='date';d.value=t.due_on;d.required=true;dl.append(d);
  const sl=el('label','任务状态'),s=el('select');Object.entries(taskStateName).forEach(([v,n])=>{const opt=el('option',n);opt.value=v;s.append(opt);});s.value=t.status;if(['done','cancelled'].includes(t.status)&&!t.is_active)s.disabled=true;sl.append(s);
  const nl=el('label','变更原因 / 完成结果'),n=el('textarea');n.rows=2;n.maxLength=1000;n.placeholder='任务结束需记录原因，不得填写个人敏感资料';nl.append(n);
  const btn=el('button','保存任务变更','button primary');btn.type='submit';btn.className+=' wide';if(['done','cancelled'].includes(t.status)&&!t.is_active)btn.disabled=true;
  frm.append(ol,dl,sl,nl,btn);frm.addEventListener('submit',async e=>{e.preventDefault();btn.disabled=true;try{
    await taskJson('/api/tasks/'+encodeURIComponent(t.task_id),'PATCH',{actor:t.owner,owner:o.value,due_on:d.value,status:s.value,note:n.value});
    toast('任务变更已记录，完成任务不等于成交。');await refresh();
  }catch(err){toast(err.message);btn.disabled=false;}});host.append(frm);
  if(['open','in_progress','waiting'].includes(t.status)&&t.is_active){
    host.append(el('div',undefined,'divider'),el('h3','记录实际人工跟进'));
    const follow=el('form',undefined,'detail-form');const fl=el('label','跟进结果'),sel=el('select');
    [['planned','计划中'],['contacted','已联系'],['no_response','未响应'],['not_suitable','暂不适合营销'],['closed','已结束']].forEach(([v,n])=>{const opt=el('option',n);opt.value=v;sel.append(opt);});fl.append(sel);
    const fn=el('label','沟通结果备注'),txt=el('textarea');txt.maxLength=1000;txt.rows=2;fn.append(txt);
    const b=el('button','保存跟进并同步任务状态','button primary');b.type='submit';b.className+=' wide';follow.append(fl,fn,b);
    follow.addEventListener('submit',async ev=>{ev.preventDefault();b.disabled=true;try{
      await taskJson('/api/tasks/'+encodeURIComponent(t.task_id)+'/followups','POST',{actor:t.owner,status:sel.value,note:txt.value});
      toast('已保存人工跟进和任务状态；不等于销售成果。');await refresh();
    }catch(err){toast(err.message);b.disabled=false;}});host.append(follow);
  }else if(!t.is_active && ['open','in_progress','waiting'].includes(t.status)){
    host.append(el('p','机会已归档，不允许新增营销跟进；请人工核验合同事实并关闭任务。','detail-note'));
  }
  host.append(el('div',undefined,'divider'),el('h3','任务操作历史'));
  const events=el('div',undefined,'event-lines');host.append(events);
  call('/api/tasks/'+encodeURIComponent(t.task_id)+'/history').then(r=>{
    if(taskSelected!==t.task_id)return;
    r.items.forEach(h=>events.append(el('div',h.logged_at+' · '+h.actor+' · '+h.event_kind+(h.details?' · '+h.details:''),'event-line')));
  }).catch(()=>events.append(el('p','暂时无法读取任务历史。','small')));
}
['taskStore','taskOwner'].forEach(id=>$(id).addEventListener('input',()=>renderTasks()));
$('taskDue').addEventListener('change',()=>renderTasks());
$('taskReload').addEventListener('click',refresh);
