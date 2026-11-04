"""Prepare or exercise a repeatable, explicitly synthetic maintenance demonstration."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse
import uuid

import httpx

ROOT=Path(__file__).resolve().parents[1]
MACHINE='DEMO-INTERVIEW'
MODEL='PF-INTERVIEW-DEMO'
TITLE='【INTERVIEW DEMO】特定刀位換刀卡住'
QUAL='DEMO換刀資格'
ENGINEER='interview_demo'
ENGINEER_NAME='INTERVIEW DEMO 工程師'


def prepare(client, complete=False):
    def api(method,path,body=None,status=200,key=None):
        kwargs={'json':body} if body is not None else {}
        if key:kwargs['headers']={'Idempotency-Key':key}
        r=client.request(method,'/api'+path,**kwargs)
        if r.status_code!=status:raise RuntimeError(f'{method} {path}: HTTP {r.status_code}: {r.text}')
        return r.json()
    config=api('GET','/auth/config')
    if config['app_mode']!='demo' or not config['demo_mode']:
        raise RuntimeError('This script only writes to an explicitly enabled demo environment.')
    def login(role):
        r=api('POST','/auth/demo',{'role':role,**({'username':ENGINEER} if role=='engineer' else {})})
        client.headers['X-CSRF-Token']=r['csrf']
    login('supervisor')
    accounts=api('GET','/admin/users')
    user=next((u for u in accounts if u['username']==ENGINEER),None)
    if user and (user['name']!=ENGINEER_NAME or user['role']!='engineer' or not user['active']):
        raise RuntimeError('Reserved interview account has conflicting identity or is inactive; refusing to overwrite it.')
    if user is None:
        api('POST','/admin/users',{'username':ENGINEER,'name':ENGINEER_NAME,'role':'engineer',
            'password':secrets.token_urlsafe(32),'specialty':'面試展示換刀','skills':['換刀'],'qualifications':[QUAL]},201)
    people=api('GET','/dispatch')
    amy=next(p for p in people if p['username']==ENGINEER)
    if any(t['issue']!=TITLE and t['status']!='待主管審核'
           and t.get('workflow',{}).get('remaining_minutes') is None for t in amy['tasks']):
        raise RuntimeError('The interview engineer has unrelated unestimated demo work; refusing to alter it.')
    profile={k:amy.get(k,[] if k!='specialty' else '') for k in ['specialty','skills','qualifications']}
    profile['skills']=sorted(set(profile['skills']+['換刀']))
    profile['qualifications']=sorted(set(profile['qualifications']+[QUAL]))
    api('PUT','/admin/users/'+ENGINEER+'/profile',profile)
    now=datetime.now(timezone.utc)
    duties=api('GET','/duties')
    current=next((d for d in duties if d['username']==ENGINEER and
                  datetime.fromisoformat(d['starts_at'])<=now<datetime.fromisoformat(d['ends_at'])),None)
    if current:
        api('PUT','/duties/'+current['id']+'/attendance',{
            'username':ENGINEER,'starts_at':current['starts_at'],'ends_at':current['ends_at'],
            'attendance':'present','capacity_minutes':max(240,current['capacity_minutes']),
            'note':current.get('note') or 'INTERVIEW DEMO 出勤'})
    else:
        end=now+timedelta(hours=4)
        future=[datetime.fromisoformat(d['starts_at']) for d in duties
                if d['username']==ENGINEER and datetime.fromisoformat(d['starts_at'])>now]
        if future:end=min(end,min(future))
        api('POST','/duties',{'username':ENGINEER,'starts_at':now.isoformat(),'ends_at':end.isoformat(),
            'attendance':'present','capacity_minutes':min(240,int((end-now).total_seconds()/60)),
            'note':'INTERVIEW DEMO 虛構出勤；示範開始前更新'},201)
    if not any(m['id']==MACHINE for m in api('GET','/machines')):
        api('POST','/machines',{'id':MACHINE,'name':'INTERVIEW DEMO 加工中心','kind':'mill','machine_model':MODEL},201)
    manuals=api('GET','/knowledge/manuals')
    if not any(m['title']=='INTERVIEW DEMO 換刀排查手冊' and m['active'] for m in manuals):
        api('POST','/knowledge/manuals',{'title':'INTERVIEW DEMO 換刀排查手冊','version':'1',
            'machine_model':MODEL,'component':'換刀','is_synthetic':True,'rights_confirmed':True,
            'source_label':'原創虛構面試資料，不作現場維修依據',
            'content':'# 換刀卡住排查\n\n'+('虛構情境：換刀卡住時，記錄刀位、警報及近期變更，核對刀具主檔與刀位資料。\n'*8)+
                      '\n# 復測與驗收\n\n'+('虛構驗收：保存核准程序、測試條件與結果；未測範圍保留未驗證，不自動核准生產。\n'*8)},201)
    report={'machine':MACHINE,'symptoms':TITLE,'machine_model':MODEL,'component':'換刀',
            'conditions':'虛構：新增刀具後僅特定刀位卡住','alarm':'DEMO-ATC，非通用警報',
            'recent_change':'虛構：更換刀把','scope':'單一刀位','previous_checks':'已保存刀位與刀號，待核對資料','use_llm':False}
    analysis=api('POST','/repair-flow/analyze',report)
    source=next(s for s in analysis['candidates'] if s['machine_models']==[MODEL])
    tickets=api('GET','/tickets')
    ticket=next((t for t in tickets if t['issue']==TITLE and t['status'] not in ['已完成','待主管審核']),None)
    if ticket is None:
        ticket=api('POST','/repair-flow/report',report,201,key='interview-'+uuid.uuid4().hex)
    tid=ticket['id']
    if not ticket['workflow'].get('procedure'):
        ticket=api('PUT','/tickets/'+tid+'/procedure',{'revision':0,'machine_model':MODEL,
            'approval_note':'主管核對虛構手冊與展示範圍，僅供面試操作',
            'steps':[{'label':'核對刀具主檔與刀位資料','kind':'inspect','criterion':'記錄一致性與實際發現',
                      'source_chunk_id':source['chunk_id'],'source_hash':source['source_hash']},
                     {'label':'維修後復測與驗收','kind':'verify','criterion':'保存展示測試條件與結果；未測範圍明確標示'}]})
    api('PUT','/tickets/'+tid+'/estimate',{'remaining_minutes':30,'required_qualifications':[QUAL],
                                        'note':'INTERVIEW DEMO 核准清單估時'})
    rank=api('GET','/dispatch?ticket_id='+tid+'&part=換刀')
    recommended=next(p for p in rank if p['username']==ENGINEER)
    if not recommended['eligible']:raise RuntimeError('Demo engineer is not eligible: '+str(recommended['reasons']))
    if ticket['engineer']!=ENGINEER_NAME:
        ticket=api('PATCH','/tickets/'+tid+'/assign',{'engineer':ENGINEER_NAME,'reason':'INTERVIEW DEMO 合資格且有容量'})
    plans=api('GET','/maintenance-plans')
    if not any(p['title']=='INTERVIEW DEMO 定期核對刀具資料' for p in plans):
        api('POST','/maintenance-plans',{'revision':0,'machine':MACHINE,'machine_model':MODEL,
            'title':'INTERVIEW DEMO 定期核對刀具資料','interval_days':30,
            'next_due':now.astimezone(timezone(timedelta(hours=8))).date().isoformat(),
            'approval_note':'原創虛構保養計畫','steps':[
                {'label':'記錄刀具資料與異常','kind':'inspect','criterion':'保存虛構示範紀錄'},
                {'label':'復核紀錄完整性','kind':'verify','criterion':'核對必要欄位及未測範圍'}]},201)
    items=api('GET','/stock')
    item=next((i for i in items if i['name']=='INTERVIEW DEMO 密封件'),None)
    if item is None:
        item=api('POST','/stock',{'name':'INTERVIEW DEMO 密封件','unit':'個','minimum':3},201)
        api('POST','/stock/'+item['id']+'/movements',{'kind':'receive','quantity':5,
            'note':'面試虛構初始庫存'},key='interview-initial-stock-'+item['id'])
    result={'synthetic':True,'ticket_id':tid,'machine_id':MACHINE,'engineer':ENGINEER_NAME,
            'qualification':QUAL,'ready_for_dispatch':True,'procedure_present':True,'completed':False}
    if complete:
        login('engineer')
        if ticket['status']=='已指派':api('POST','/tickets/'+tid+'/start',{})
        procedure=ticket['workflow']['procedure']
        def results(verification):
            nonlocal procedure
            t=api('PUT','/tickets/'+tid+'/procedure/results',{'revision':procedure['revision'],
                'results':[{'step_id':s['id'],'outcome':verification if s['kind']=='verify' else 'pass',
                            'note':'虛構：驗收未通過，需再排查' if s['kind']=='verify' and verification=='fail'
                            else '虛構：資料已核對，測試條件與結果已保存'} for s in procedure['steps']]})
            procedure=t['workflow']['procedure']
        results('fail')
        api('POST','/tickets/'+tid+'/complete',{'note':'虛構未通過驗收，不應提交成功'},422)
        result['failed_verification_blocked']=True
        results('pass')
        api('POST','/tickets/'+tid+'/work-logs',{'minutes':20,'note':'INTERVIEW DEMO 虛構工時'},201)
        api('POST','/tickets/'+tid+'/complete',{'note':'虛構：核對刀位資料並依核准程序完成復測，記錄示範結果。'})
        login('supervisor')
        api('POST','/tickets/'+tid+'/review',{'decision':'approve','note':'主管核對虛構排查與復測紀錄，僅供面試展示'})
        case=api('POST','/tickets/'+tid+'/case-draft',{},201)
        fields={**case['fields'],'component':'換刀','conditions':report['conditions'],
                'cause_status':'hypothesis','root_cause':'虛構假設：刀位資料不一致，非通用故障根因',
                'is_synthetic':True}
        case=api('PUT','/cases/'+case['id'],{'revision':case['revision'],'fields':fields})
        api('POST','/cases/'+case['id']+'/publish',{'revision':case['revision'],'note':'核對虛構原文與適用範圍後發布'})
        evidence=api('POST','/assist',{'question':'換刀卡住刀位資料','machine_model':MODEL,'use_llm':False})
        assert any(s['id']==case['id'] for s in evidence['citations'])
        result.update(completed=True,case_id=case['id'],published_case_retrievable=True)
    api('POST','/auth/logout',{})
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8082')
    parser.add_argument('--walkthrough',action='store_true',help='Exercise failed verification, completion and case publication')
    args=parser.parse_args()
    if urlparse(args.url).hostname not in ['127.0.0.1','localhost']:raise SystemExit('Local demonstration only')
    with httpx.Client(base_url=args.url,timeout=30) as client:result=prepare(client,args.walkthrough)
    filename='validation-walkthrough-report.json' if args.walkthrough else 'validation-demo-report.json'
    (ROOT/'artifacts'/filename).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
