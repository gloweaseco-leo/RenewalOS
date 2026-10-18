'use strict';
// In-memory bearer only: no localStorage, cookies, or persistent JS token storage.
const byId=id=>document.getElementById(id);
let token=null, memberships={};
function status(message){byId('status').textContent=message;}
function clear(node){while(node.firstChild)node.firstChild.remove();}
function text(node,value){node.textContent=String(value??'');}
async function call(url,body){
  const h={'Accept':'application/json'};
  if(token)h.Authorization='Bearer '+token;
  if(body!==undefined)h['Content-Type']='application/json';
  const response=await fetch(url,{method:body===undefined?'GET':'POST',headers:h,
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(data.detail||'请求失败');
  return data;
}
byId('loginForm').addEventListener('submit',async e=>{
  e.preventDefault();
  try{
    const data=await call('/api/auth/login',{username:byId('username').value,password:byId('password').value});
    token=data.access_token;memberships=data.memberships;
    byId('password').value='';
    const selector=byId('store');clear(selector);
    for(const [store,role] of Object.entries(memberships)){
      const option=document.createElement('option');option.value=store;text(option,store+' / '+role);selector.append(option);
    }
    byId('welcome').textContent='工作台 / '+data.user_id;
    byId('loginPanel').hidden=true;byId('workspace').hidden=false;
    status('登录成功。当前仅可访问已授权门店。');
  }catch(err){token=null;status(err.message)}
});
byId('logout').addEventListener('click',async()=>{
  try{if(token)await call('/api/auth/logout',{});}catch(_ignored){}
  token=null;memberships={};clear(byId('results'));byId('workspace').hidden=true;
  byId('loginPanel').hidden=false;status('已退出。');
});
async function load(kind){
  if(!token)return status('请先登录。');
  const store=byId('store').value, role=memberships[store];
  if(!store)return status('没有任何已授权门店。');
  const suffix=kind==='management'?'management':kind;
  try{
    const data=await call('/api/v1/stores/'+encodeURIComponent(store)+'/'+suffix);
    const items=kind==='management'?data.cases:(data.items||[]);
    const target=byId('results');clear(target);
    text(byId('scopeNote'),store+' / '+role+' / '+items.length+'条（仅只读）');
    for(const item of items){
      const node=document.createElement('div');node.className='item';
      const heading=document.createElement('strong');text(heading,item.opportunity_id||item.task_id);
      const detail=document.createElement('div');
      text(detail,kind==='tasks'?[item.owner,item.status,item.due_on].join(' / '):
        [item.guardian_alias||item.learner_id,item.stage_label||item.reason].join(' / '));
      node.append(heading,detail);target.append(node);
    }
    if(!items.length)status('授权范围内没有记录。');else status('已加载授权范围内的数据。');
  }catch(err){clear(byId('results'));status(err.message)}
}
byId('loadOpportunities').addEventListener('click',()=>load('opportunities'));
byId('loadTasks').addEventListener('click',()=>load('tasks'));
byId('loadManager').addEventListener('click',()=>load('management'));
byId('store').addEventListener('change',()=>{clear(byId('results'));text(byId('scopeNote'),'请重新加载选定门店的数据。')});
