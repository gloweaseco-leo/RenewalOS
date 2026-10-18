'use strict';
// No localStorage access: in-memory session only. All business reads/writes go to PostgreSQL-scoped /api/v1/orgs/... routes.
const $=id=>document.getElementById(id);
const state={token:null,user:null,memberships:{},authBackend:null,org:'',store:'',role:null,tab:'opportunities',items:[],selected:null,version:0,drafts:{}};
const CODES={open:'待处理',assigned:'已分配',contacted:'已跟进',signed:'已签约',paid:'已收款',closed:'已关闭',
  control:'对照组',rules:'规则组',ai:'AI组',in_progress:'跟进中',waiting:'待反馈',done:'已完成',cancelled:'已取消',
  contacted:'已联系',no_answer:'未接通',customer_declined:'客户拒绝',followup_later:'稍后跟进'};
function el(tag,value,cls){const x=document.createElement(tag);if(value!==undefined)x.textContent=String(value??'');if(cls)x.className=cls;return x;}
function clear(n){n.replaceChildren();}
function text(id,value){$(id).textContent=String(value??'');}
function msg(value,error=false){const n=$('status');n.textContent=String(value);n.className=error?'error':'';}
function name(value){return CODES[value]||value||'—';}
function cash(n){return n===null||n===undefined?'—':'¥'+(Number(n)/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});}
function uid(prefix){const v=globalThis.crypto?.randomUUID?.()||String(Date.now())+'-'+Math.random().toString(36).slice(2,10);return prefix+'-'+v;}
function iso(){return new Date().toISOString().slice(0,10);}
async function createFact(kind, resource, route, field, prefix, payload){
  // The same submitted form reuses its event ID after a network timeout.
  // Once the server acknowledges it, the draft ID is retired.
  const key=[state.org,state.store,kind,resource].join('|');
  if(!state.drafts[key])state.drafts[key]=uid(prefix);
  const id=state.drafts[key];
  const result=await api(url(route),{...payload,[field]:id});
  delete state.drafts[key];
  return result;
}
function validId(value){return /^[A-Za-z0-9_-]{2,64}$/.test(value);}
function logoutUI(){state.token=null;state.user=null;state.memberships={};state.authBackend=null;state.org='';state.store='';state.role=null;state.tab='opportunities';state.selected=null;state.items=[];state.version++;state.drafts={};
  document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab==='opportunities'));
  $('managementTab').hidden=true;
  $('loginPanel').hidden=false;$('workspace').hidden=true;clear($('list'));clear($('detail'));text('roleBadge','未认证');}
async function api(url,body){const headers={'Accept':'application/json'};
  if(state.token)headers.Authorization='Bearer '+state.token;
  if(body!==undefined)headers['Content-Type']='application/json';
  const response=await fetch(url,{method:body===undefined?'GET':'POST',headers,cache:'no-store',
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json().catch(()=>({}));
  if(response.status===401){logoutUI();throw Error('登录失效，请重新登录');}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'请求失败（HTTP '+response.status+'）');
  return data;
}
function url(part=''){return '/api/v1/orgs/'+encodeURIComponent(state.org)+'/stores/'+encodeURIComponent(state.store)+'/'+part;}
function context(){const org=$('org').value.trim(),store=$('store').value;
  if(!validId(org)||!validId(store))throw Error('请填写有效机构代号并选择授权门店');
  const key=state.authBackend==='postgres'?org+':'+store:store;
  if(!state.token||!state.memberships[key])throw Error('当前账户没有该机构/门店权限');
  state.org=org;state.store=store;state.role=state.memberships[key];
  $('managementTab').hidden=state.role!=='manager';
  if(state.role!=='manager' && state.tab==='management'){state.tab='opportunities';state.selected=null;document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n.dataset.tab==='opportunities'));}
  text('roleBadge',state.role==='manager'?'经理':'员工');
  text('scopeNote',org+' / '+store+' / '+state.user+' · PostgreSQL业务数据');
}
function field(label,value){const d=el('div',undefined,'fact');d.append(el('small',label),el('strong',value===undefined?'—':value));return d;}
function form(title,fields,caption,submit){const section=el('section',undefined,'section');section.append(el('h3',title));
  const f=el('form',undefined,'form');const values={};
  for(const [key,label,type,val,options] of fields){const l=el('label',label);let x;
    if(type==='select'){x=el('select');for(const [v,txt] of options){const option=el('option',txt);option.value=v;x.append(option);}}
    else if(type==='textarea'){x=el('textarea');x.value=val||'';x.maxLength=1000;}
    else{x=el('input');x.type=type||'text';if(val!==undefined)x.value=val;if(type==='number'){x.min='0.01';x.step='0.01';}if(type==='text')x.maxLength=64;}
    x.required=key!=='note';values[key]=x;l.append(x);f.append(l);
  }
  const btn=el('button',caption||'保存','primary');btn.type='submit';f.append(btn);
  f.addEventListener('submit',async e=>{e.preventDefault();btn.disabled=true;const obj={};for(const [key,x] of Object.entries(values))obj[key]=x.value.trim();
    try{await submit(obj);msg('已写入受认证的模拟经营记录');await reload({keepSelection:true});}
    catch(err){msg(err.message,true);}finally{btn.disabled=false;}
  });section.append(f);return section;
}
function cents(value){const n=Number(value);if(!Number.isFinite(n)||n<=0||!/^\d+(?:\.\d{1,2})?$/.test(value))throw Error('金额需为大于零的人民币元，最多两位小数');return Math.round(n*100);}
async function reload({keepSelection=false}={}){
  const v=++state.version;
  try{context();}catch(err){state.items=[];state.selected=null;clear($('list'));clear($('detail'));text('listCount','—');msg(err.message,true);return;}
  text('listTitle',state.tab==='management'?'门店经营复盘':state.tab==='tasks'?'销售待办':'续费机会');
  const part=state.tab==='management'?'management':state.tab;
  try{const data=await api(url(part));if(v!==state.version)return;
    const items=state.tab==='management'?[{id:'management',title:'本门店经营快照',report:data}]:(data.items||[]);
    state.items=items;state.selected=keepSelection?state.selected:null;
    if(state.selected && !items.some(x=>(x.opportunity_id||x.task_id||x.id)===state.selected))state.selected=null;
    renderList();await renderDetail();msg('已从PostgreSQL读取授权范围内的数据。');
  }catch(err){if(v!==state.version)return;state.items=[];clear($('list'));clear($('detail'));text('listCount','—');msg(err.message,true);}
}
function renderList(){const box=$('list');clear(box);text('listCount',state.items.length);
  if(!state.items.length){box.append(el('p','授权范围内暂无记录，或尚未创建合成数据。','empty'));return;}
  for(const item of state.items){const key=item.opportunity_id||item.task_id||item.id;const btn=el('button',undefined,'record'+(state.selected===key?' active':''));btn.type='button';
    if(state.tab==='opportunities'){btn.append(el('strong',item.opportunity_id),el('small','优先级 '+item.priority+' · '+name(item.stage)+' · 原课包 '+item.source_package_id));}
    if(state.tab==='tasks'){btn.append(el('strong',item.task_id),el('small',item.opportunity_id+' · '+item.assigned_user_id+' · '+name(item.status)+' · '+item.due_on));}
    if(state.tab==='management'){btn.append(el('strong',item.title),el('small','只计算已记录的模拟经营事实'))}
    btn.addEventListener('click',()=>{state.selected=key;renderList();renderDetail().catch(e=>msg(e.message,true));});box.append(btn);
  }
}
async function renderDetail(){const pane=$('detail');clear(pane);if(!state.selected){pane.append(el('p','选择一条机会或任务，查看有权限的经营信息与操作。','muted'));return;}
  if(state.tab==='management'){renderManager(state.items[0]?.report);return;}
  const record=state.items.find(x=>(x.opportunity_id||x.task_id)===state.selected);if(!record)return;
  const opportunityId=record.opportunity_id;
  const version=state.version;
  try{
    const data=await api(url('opportunities/'+encodeURIComponent(opportunityId)));
    if(version!==state.version||state.selected!==(record.opportunity_id||record.task_id))return;
    drawOpportunity(data);
  }catch(err){if(version!==state.version)return;pane.append(el('p',err.message,'error'));}
}
function drawOpportunity(data){const pane=$('detail');clear(pane);const o=data.opportunity,t=data.task;
  pane.append(el('h3','机会 '+o.opportunity_id));
  const grid=el('div',undefined,'detail-grid');
  for(const x of [field('课程',o.course_type),field('阶段',o.stage==='contacted'?'已跟进':name(o.stage)),field('实验分组',name(o.arm)),field('优先级',o.priority),
      field('学员代号',o.learner_alias),field('剩余课时',o.remaining_sessions),field('课包到期',o.expires_on),field('负责员工',o.assigned_user_id||'未分配')])grid.append(x);
  pane.append(grid);
  if(o.signals&&Object.keys(o.signals).length){const s=el('p','经营信号（结构化）：'+JSON.stringify(o.signals),'disclaimer small');pane.append(s);}
  const pending=['open','assigned','contacted'].includes(o.stage);
  if(state.role==='manager'&&!t&&pending&&o.arm!=='control'&&o.contact_consent){
    pane.append(form('分配员工任务',[['assigned_user_id','员工账号','text',''],['due_on','截止日期','date',iso()]],'创建任务',v=>
      createFact('task',o.opportunity_id,'tasks','task_id','task',{opportunity_id:o.opportunity_id,assigned_user_id:v.assigned_user_id,due_on:v.due_on})));
  }
  if(t){const s=el('section',undefined,'section');s.append(el('h3','执行任务'));
    const div=el('div',undefined,'detail-grid');for(const x of [field('任务ID',t.task_id),field('负责人',t.assigned_user_id),field('状态',name(t.status)),field('期限',t.due_on)])div.append(x);s.append(div);pane.append(s);
    if(pending&&o.arm!=='control'&&o.contact_consent&&t.status!=='done'&&t.status!=='cancelled'&&(state.role==='manager'||t.assigned_user_id===state.user)){
      pane.append(form('记录客户跟进',[['result','处理结果','select',null,[['contacted','已联系'],['no_answer','未接通'],['customer_declined','客户拒绝'],['followup_later','稍后跟进']]],['note','沟通记录（不录入真实身份信息）','textarea','']],
        '保存跟进',v=>createFact('followup',o.opportunity_id,'followups','followup_id','follow',{opportunity_id:o.opportunity_id,result:v.result,note:v.note})));
    }
  }
  const section=el('section',undefined,'section');section.append(el('h3','跟进事件（不可修改）'));
  if(!data.followups.length)section.append(el('p','目前没有跟进事件。','muted'));
  const list=el('ul',undefined,'events');for(const e of data.followups){list.append(el('li',e.recorded_at.slice(0,16).replace('T',' ')+' · '+e.actor_user_id+' · '+name(e.result)+' · '+e.note));}section.append(list);pane.append(section);
  if(state.role==='manager')renderFinance(data,pane);
  pane.append(el('p',data.disclaimer,'disclaimer'));
}
function renderFinance(data,pane){const o=data.opportunity,c=data.contract;
  if(!c){if(o.stage!=='closed')pane.append(form('登记模拟续费合同',[
    ['signed_on','签约日期','date',iso()],['amount_yuan','合同金额（元）','number','3000']],'创建合成合同',v=>
    createFact('contract',o.opportunity_id,'contracts','contract_id','contract',{opportunity_id:o.opportunity_id,signed_on:v.signed_on,amount_cents:cents(v.amount_yuan)})));
    return;}
  const section=el('section',undefined,'section');section.append(el('h3','合同与资金事件（经理权限）'));
  const grid=el('div',undefined,'detail-grid');for(const x of [field('合同ID',c.contract_id),field('签约金额',cash(c.contracted_amount_cents)),field('模拟净收款',cash(c.net_paid_cents)),field('资金来源',c.provenance)])grid.append(x);section.append(grid);
  const ul=el('ul',undefined,'events');
  // Render each event using textContent, never interpret any imported data as HTML.
for(const e of data.cash_events){ul.append(el('li',e.event_id+' · '+e.occurred_on+' · '+(e.kind==='payment'?'模拟付款':'模拟退款')+' · '+cash(e.amount_cents)+(e.refund_of?' · 原付款 '+e.refund_of:'')));}
  if(!data.cash_events.length)ul.append(el('li','尚未登记任何模拟资金事件。'));
  section.append(ul);pane.append(section);
  const paid=data.cash_events.filter(x=>x.kind==='payment').reduce((n,x)=>n+x.amount_cents,0);
  if(paid<c.contracted_amount_cents){pane.append(form('登记模拟付款',[
    ['amount_yuan','本次模拟收款（元）','number','1000'],['occurred_on','记录日期','date',iso()]],'登记付款',v=>
      createFact('payment',c.contract_id,'cash-events','event_id','pay',{contract_id:c.contract_id,kind:'payment',amount_cents:cents(v.amount_yuan),occurred_on:v.occurred_on,refund_of:null})));
  }
  const payments=data.cash_events.filter(x=>x.kind==='payment');
  if(payments.length){pane.append(form('登记模拟退款',[
    ['refund_of','对应原付款','select',null,payments.map(e=>[e.event_id,e.event_id+' · '+cash(e.amount_cents)])],
    ['amount_yuan','模拟退款金额（元）','number','100'],['occurred_on','退款日期','date',iso()]],'登记退款',v=>
    createFact('refund',c.contract_id+'|'+v.refund_of,'cash-events','event_id','refund',{contract_id:c.contract_id,kind:'refund',amount_cents:cents(v.amount_yuan),refund_of:v.refund_of,occurred_on:v.occurred_on})));
  }
}
function renderManager(report){const pane=$('detail');clear(pane);if(!report)return;
  pane.append(el('h3','本门店经营事实（非因果ROI）'));
  const grid=el('div',undefined,'detail-grid');grid.append(field('模拟净收款',cash(report.synthetic_cash_net_cents)),field('模拟资金事件数',report.cash_event_count));
  pane.append(grid);
  for(const [title,data] of [['续费机会阶段',report.stages],['员工任务状态',report.task_statuses]]){
    const section=el('section',undefined,'section');section.append(el('h3',title));const items=Object.entries(data||{});
    if(!items.length)section.append(el('p','暂无记录','muted'));
    for(const [status,count] of items)section.append(el('p',name(status)+'：'+count+'条'));
    pane.append(section);
  }
  pane.append(el('p',report.disclaimer||'模拟流水不代表真实到账，也不是AI增量收入。','disclaimer'));
}
$('loginForm').addEventListener('submit',async e=>{e.preventDefault();const btn=e.currentTarget.querySelector('button');btn.disabled=true;
  try{const data=await api('/api/auth/login',{username:$('username').value.trim(),password:$('password').value});
    state.token=data.access_token;state.memberships=data.memberships||{};state.user=data.user_id;state.authBackend=data.identity_backend||'sqlite';
    $('password').value='';const selector=$('store');clear(selector);
    for(const [key,role] of Object.entries(state.memberships)){
      const compound=state.authBackend==='postgres';
      const pair=compound?key.split(':'):[null,key];
      const opt=el('option',(compound?pair[0]+' / ':'')+pair[1]+' / '+name(role));
      opt.value=pair[1];opt.dataset.org=pair[0]||'';selector.append(opt);
    }
    if(state.authBackend==='postgres'){ $('org').value=selector.selectedOptions[0]?.dataset.org||''; }
    $('loginPanel').hidden=true;$('workspace').hidden=false;text('welcome',data.user_id+' 的续费经营工作台');
    msg('已登录。填写机构代号，验证数据库所属机构与门店后才能查看业务。');
  }catch(err){logoutUI();msg(err.message,true);}finally{btn.disabled=false;}
});
$('logout').addEventListener('click',async()=>{try{if(state.token)await api('/api/auth/logout',{});}catch(_e){}logoutUI();msg('已退出，未在浏览器保存会话。');});
$('reload').addEventListener('click',()=>reload());
$('org').addEventListener('change',()=>{state.version++;clear($('list'));clear($('detail'));state.selected=null;msg('机构已变更，请刷新并重新验证权限。');});
$('store').addEventListener('change',()=>{if(state.authBackend==='postgres')$('org').value=$('store').selectedOptions[0]?.dataset.org||'';state.version++;clear($('list'));clear($('detail'));state.selected=null;msg('门店已变更，请刷新并重新验证权限。');});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{
  state.tab=b.dataset.tab;state.selected=null;document.querySelectorAll('[data-tab]').forEach(n=>n.classList.toggle('active',n===b));
  reload();
}));
