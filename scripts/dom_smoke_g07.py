"""Browser DOM checks using synthetic mocked API responses. Not live HTTP E2E."""
from pathlib import Path
import shutil
import os
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
html=(root/'static/index.html').read_text()
js=(root/'static/app.js').read_text()
mock=r"""() => {
  const opportunity = {opportunity_id:'O-PKTEST', learner_id:'LTEST', package_id:'PKTEST', guardian_alias:'合成家长',
     store_id:'DEMO-STORE',course_type:'游泳',expires_on:'2026-12-01',is_active:1,arm:'rules',priority:65,
     reason:'剩余2节',rule_advice:'先核实课程进度',model_advice:null,last_owner:null,
     signals:{remaining_sessions:2,days_to_expiry:20,attendance_previous_28d:4,attendance_recent_28d:2}};
  let tasks=[];
  window.fetch = async (url, options={}) => {
    const p=String(url),method=options.method||'GET';let obj={};
    if (p.startsWith('/api/opportunities')) obj={items:[opportunity]};
    else if(p.startsWith('/api/report')) obj={net_paid_cny:0,followup_records:0,attribution_note:'NOT ESTABLISHED',arm_family_counts:{control:0,rules:1,ai:0}};
    else if(p.startsWith('/api/health')) obj={ai_configured:false};
    else if(p.startsWith('/api/cohorts')) obj={items:[]};
    else if(p.startsWith('/api/tasks/T-TEST/history')) obj={items:[{logged_at:'2026-10-18',actor:'顾问甲',event_kind:'created',details:'合成任务'}]};
    else if(p.startsWith('/api/tasks') && method==='GET') obj={items:tasks,summary:{open:tasks.length,due_today:tasks.length,overdue:0,resolved:0}};
    else if(p==='/api/tasks' && method==='POST') {
      const x=JSON.parse(options.body);tasks.push({task_id:'T-TEST',opportunity_id:x.opportunity_id,store_id:'DEMO-STORE',
        owner:x.owner,due_on:x.due_on,status:'open',is_active:1,course_type:'游泳',guardian_alias:'合成家长',
        learner_id:'LTEST',arm:'rules',priority:65,followup_count:0,net_paid_cny:0,due_bucket:'today'});obj={task_id:'T-TEST'};
    } else if(p.startsWith('/api/tasks/T-TEST')&&method==='PATCH') {
      const x=JSON.parse(options.body);tasks[0].status=x.status;tasks[0].owner=x.owner;obj={ok:true};
    } else if(p==='/api/followups/O-PKTEST')obj={items:[]};
    else if(p==='/api/demo/sales/PKTEST')obj={contract:null,payments:[],net_paid_cny:0,disclaimer:'模拟'};
    else obj={ok:true};
    return {ok:true,status:200,json:async()=>obj};
  };
}"""
with sync_playwright() as pw:
    browser_binary=os.getenv('RENEWAL_BROWSER_BINARY') or shutil.which('chromium') or shutil.which('google-chrome')
    browser=pw.chromium.launch(headless=True, executable_path=browser_binary, args=['--no-sandbox'])
    page=browser.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content(html,wait_until='domcontentloaded')
    page.evaluate(mock)
    page.add_script_tag(content=js)
    page.locator('.opp-row').first.wait_for(timeout=4000)
    page.locator('.opp-row').first.click()
    page.locator('.task-create-panel form').wait_for(timeout=4000)
    page.locator('.task-create-panel input').first.fill('顾问甲')
    page.get_by_text('创建员工跟进任务',exact=True).click()
    page.get_by_text('进入销售待办',exact=True).wait_for(timeout=4000)
    page.get_by_text('进入销售待办',exact=True).click()
    page.locator('#tasks.visible').wait_for(timeout=2000)
    page.locator('#taskList .opp-row').first.wait_for(timeout=4000)
    page.locator('#taskList .opp-row').first.click()
    assert page.locator('#taskDetail').get_by_text('顾问甲').count()>0
    assert page.locator('#taskStatOpen').inner_text()=='1'
    assert not errors,errors
    print('DOM_SMOKE_PASS: opportunity → assign task → work queue → task details (mocked API only)')
    browser.close()
