"""G1-D Chromium DOM integration with mocked, scoped HTTP responses.
Not a substitute for browser-over-real-HTTP or production security acceptance.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
HTML=(ROOT/'static/secure.html').read_text()
JS=str(ROOT/'static/secure.js')
MOCK=r'''
window.mock = {actions:[],task:null,contract:null,cash:[],followups:[],stage:'open'};
window.fetch = async function(url, options={}) {
  const action={url,method:options.method||'GET',body:options.body?JSON.parse(options.body):null};
  window.mock.actions.push(action);
  const path=url.split('/');
  let value, code=200;
  if(url==='/api/auth/login') value={access_token:'test-token',user_id:'managerA',memberships:{pool:'manager'}};
  else if(url==='/api/auth/logout')value={ok:true};
  else if(url.endsWith('/opportunities')&&action.method==='GET')value={items:[{opportunity_id:'opp-1',source_package_id:'pack-1',stage:window.mock.stage,priority:80}]};
  else if(url.endsWith('/tasks')&&action.method==='GET')value={items:window.mock.task?[window.mock.task]:[]};
  else if(url.endsWith('/management'))value={stages:{[window.mock.stage]:1},task_statuses:{open:window.mock.task?1:0},synthetic_cash_net_cents:12000,cash_event_count:window.mock.cash.length,incremental_roi:null,disclaimer:'模拟'};
  else if(url.endsWith('/opportunities/opp-1'))value={opportunity:{opportunity_id:'opp-1',source_package_id:'pack-1',learner_id:'learner-1',learner_alias:'甲',assigned_user_id:window.mock.task?'staffA':null,
   arm:'rules',stage:window.mock.stage,priority:80,signals:{remaining_sessions:2},course_type:'swim',remaining_sessions:2,expires_on:'2026-12-31',contact_consent:true},
   task:window.mock.task,followups:window.mock.followups,contract:window.mock.contract,cash_events:window.mock.cash,disclaimer:'模拟测试'};
  else if(url.endsWith('/tasks')&&action.method==='POST'){window.mock.task={task_id:action.body.task_id,assigned_user_id:action.body.assigned_user_id,due_on:action.body.due_on,status:'open'};window.mock.stage='assigned';value={created:true};}
  else if(url.endsWith('/followups')&&action.method==='POST'){window.mock.followups.push({...action.body,actor_user_id:'managerA',recorded_at:'2026-10-18T02:00:00Z'});window.mock.stage='contacted';value={created:true};}
  else if(url.endsWith('/contracts')&&action.method==='POST'){window.mock.contract={contract_id:action.body.contract_id,signed_on:action.body.signed_on,contracted_amount_cents:action.body.amount_cents,net_paid_cents:0,provenance:'synthetic'};window.mock.stage='signed';value={created:true};}
  else if(url.endsWith('/cash-events')&&action.method==='POST'){window.mock.cash.push({...action.body,provenance:'synthetic'});window.mock.contract.net_paid_cents=window.mock.cash.reduce((n,e)=>n+(e.kind==='payment'?e.amount_cents:-e.amount_cents),0);window.mock.stage=window.mock.contract.net_paid_cents>0?'paid':'signed';value={created:true};}
  else {code=404;value={detail:'mock route missing: '+url}};
  return new Response(JSON.stringify(value),{status:code,headers:{'Content-Type':'application/json'}});
};
'''
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page()
    page.set_content(HTML)
    page.evaluate(MOCK+'; true;')
    page.add_script_tag(path=JS)
    page.fill('#username','managerA')
    page.fill('#password','synthetic-only-passphrase')
    page.locator('#loginForm button').click()
    page.locator('#org').fill('g1ca')
    page.locator('#reload').click()
    page.get_by_role('button',name='opp-1').click()
    page.get_by_text('分配员工任务').wait_for(timeout=7000)
    page.get_by_label('员工账号').fill('staffA')
    page.locator('form').filter(has=page.get_by_text('员工账号')).get_by_label('截止日期').fill('2026-11-01')
    page.get_by_role('button',name='创建任务').click()
    page.wait_for_function("window.mock.task!==null")
    page.get_by_role('button',name='销售待办').click()
    assert page.get_by_text('staffA').count()>=1
    page.get_by_role('button',name='续费机会').click()
    page.get_by_role('button',name='opp-1').click()
    page.get_by_role('button',name='保存跟进').click()
    page.wait_for_function('window.mock.followups.length===1')
    page.get_by_role('button',name='创建合成合同').click()
    page.wait_for_function('window.mock.contract!==null')
    page.get_by_role('button',name='登记付款').click()
    page.wait_for_function('window.mock.cash.length===1')
    page.get_by_role('button',name='登记退款').click()
    page.wait_for_function('window.mock.cash.length===2')
    page.get_by_role('button',name='经理复盘').click()
    page.get_by_role('button',name='本门店经营快照').click()
    assert page.get_by_text('模拟净收款').count()>=1
    print('G1-D Chromium DOM smoke PASSED: auth → scope → task → followup → contract → payment → refund → management')
    browser.close()
