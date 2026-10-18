"""G0.8 Chromium DOM action test with mocked GET API, not HTTP E2E."""
from pathlib import Path
import shutil, os
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
mock=r'''() => {
 const opp={opportunity_id:'O-X',learner_id:'L-X',package_id:'PK-X',guardian_alias:'合成监护人',
 store_id:'DEMO-STORE',course_type:'游泳',expires_on:'2026-12-01',is_active:1,
 arm:'rules',priority:90,reason:'剩余3节',rule_advice:'人工核实服务体验',model_advice:null,
 signals:{remaining_sessions:3,days_to_expiry:20,attendance_previous_28d:4,attendance_recent_28d:2}};
 window.fetch=async (url)=>{
  const path=String(url); let result={};
  if(path.startsWith('/api/opportunities')) result={items:[opp]};
  else if(path.startsWith('/api/report'))result={net_paid_cny:0,followup_records:0,attribution_note:'NOT ESTABLISHED',arm_family_counts:{control:0,rules:1,ai:0}};
  else if(path.startsWith('/api/health'))result={ai_configured:false};
  else if(path.startsWith('/api/cohorts'))result={items:[]};
  else if(path.startsWith('/api/tasks'))result={items:[],summary:{total:0,open:0,due_today:0,overdue:0,resolved:0}};
  else if(path.startsWith('/api/management/overview'))result={summary:{opportunities:1,active_non_control:1,task_overdue:0,linked_net_cash_cny:0},
  stage_counts:{control:0,net_paid:0,legacy_paid:0,contract_no_net:0,followed:0,assigned:0,unassigned:1},
  stage_labels:{control:'对照组',net_paid:'净收款',legacy_paid:'旧流水',contract_no_net:'签约无付款',followed:'已跟进',assigned:'已分配',unassigned:'待分配'},
  milestones:{assigned:0,followed:0,contracted:0,linked_net_paid:0,legacy_net_paid:0,control:0},
  alerts:[{kind:'high_priority_unassigned',label:'高优先级机会尚未分配任务',urgency:2,opportunity_id:'O-X',task_id:null,store_id:'DEMO-STORE',owner:null,priority:90}],
  owner_workload:[],cases:[{opportunity_id:'O-X',guardian_alias:'合成监护人',stage_label:'待分配',store_id:'DEMO-STORE',owner:null,net_paid_cny:0,task_id:null}],
  case_count:1,limitations:['仅模拟数据','无ROI']};
  else if(path.startsWith('/api/followups'))result={items:[]};
  else if(path.startsWith('/api/demo/sales'))result={contract:null,payments:[],net_paid_cny:0,disclaimer:'合成'};
  return {ok:true,status:200,json:async()=>result};
 }
}'''
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path=os.getenv('RENEWAL_BROWSER_BINARY') or shutil.which('chromium'),args=['--no-sandbox'])
    page=browser.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content((root/'static/index.html').read_text(),wait_until='domcontentloaded')
    page.evaluate(mock)
    page.add_script_tag(content=(root/'static/app.js').read_text())
    page.locator('[data-view="management"]').click()
    page.locator('#management.visible').wait_for(timeout=5000)
    page.wait_for_function("document.getElementById('mgOpportunities').textContent==='1'")
    assert page.locator('#mgNetCash').inner_text()=='¥0'
    assert page.locator('#mgAlerts .manager-case').count()==1
    page.locator('#mgAlerts .manager-case').first.click()
    page.locator('#opportunities.visible').wait_for(timeout=4000)
    assert '合成监护人' in page.locator('#detail').inner_text()
    assert not errors,errors
    browser.close()
print('G08_DOM_SMOKE_PASS: management overview → alert → linked opportunity, mocked API only')