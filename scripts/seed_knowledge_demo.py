"""Explicit demo-only API seed: approved synthetic work orders and published cases."""
import argparse
import http.cookiejar
import json
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8082')
    args=parser.parse_args()
    from urllib.parse import urlparse
    if urlparse(args.url).hostname not in ['127.0.0.1','localhost']:
        raise SystemExit('Demo seed only accepts localhost')
    opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf=''
    def api(path,body=None,method=None):
        request=urllib.request.Request(args.url+'/api'+path,
            data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
            headers={'Content-Type':'application/json','X-CSRF-Token':csrf},method=method)
        with opener.open(request,timeout=120) as response:return json.load(response)
    if not api('/auth/config')['demo_mode']:
        raise SystemExit('Use start.ps1 -Demo with demonstration data first')
    def login(role):
        nonlocal csrf
        csrf=api('/auth/demo',{'role':role})['csrf']
    login('supervisor')
    scenarios=[
        {'machine':'CNC-03','title':'【合成案例】換刀卡住與刀位資料不一致','component':'換刀機構',
         'conditions':'示範情境：新增刀具後，僅特定刀位出現換刀中斷。',
         'findings':'合成查核：刀具主檔與核准刀位資料不一致，保留變更前後畫面。',
         'root_cause':'示範情境已確認刀具資料不一致；不代表現場通用根因。',
         'actions':'合成處置：合格人員核對適配資料，依核准程序修正刀具資料。',
         'verification':'合成驗收：保存核准程序下的換刀狀態確認與首件結果；沒有通用測試次數。'},
        {'machine':'CNC-06','title':'【合成案例】冷卻多支路流量下降與過濾段','component':'冷卻循環',
         'conditions':'示範情境：多個冷卻使用端供應下降，儲槽液位未顯著改變。',
         'findings':'合成查核：記錄測點、負載與過濾段狀態，確認過濾段問題。',
         'root_cause':'示範情境已確認過濾段影響供應，不直接認定泵損壞。',
         'actions':'合成處置：依核准程序處理已確認的過濾段問題，未更換泵。',
         'verification':'合成驗收：相同測點、負載及介質下比較前後供應；現場允許值仍需原廠文件。'},
        {'machine':'CNC-09','title':'【合成案例】熱機後尺寸漂移與量測條件缺漏','component':'進給與定位',
         'conditions':'示範情境：不同時段量測工具與環境不一致，熱機後工件讀值改變。',
         'findings':'合成查核：缺乏一致的基準、工具校驗及熱條件，無法直接比較。',
         'root_cause':'未知；目前僅確認量測資料不可直接比較，未確認機台故障。',
         'cause_status':'unknown',
         'actions':'合成處置：整理量測工具、基準與工況，保留未知原因並安排追蹤。',
         'verification':'合成驗收：確認紀錄完整性；未宣告幾何精度合格或自動核准生產。'}]
    outputs=[]
    for scenario in scenarios:
        login('supervisor')
        tickets=api('/tickets')
        ticket=next((t for t in tickets if t['issue']==scenario['title']),None)
        if ticket is None:
            ticket=api('/tickets',{'machine':scenario['machine'],'issue':scenario['title'],'engineer':'Amy Chen'})
        tid=ticket['id']
        if ticket['status'] not in ['已完成','待主管審核']:
            login('engineer')
            api('/tickets/'+tid+'/complete',{'note':scenario['findings']+'\n'+scenario['actions']+'\n'+scenario['verification']})
        login('supervisor')
        ticket=next(t for t in api('/tickets') if t['id']==tid)
        if ticket['status']=='待主管審核':
            api('/tickets/'+tid+'/review',{'decision':'approve','note':'合成展示資料，核對示例內容與驗收紀錄'})
        case=api('/tickets/'+tid+'/case-draft',{})
        if case['status']!='published':
            fields={**case['fields'],**{k:scenario[k] for k in ['title','component','conditions','findings','root_cause','actions','verification']},
                    'machine_model':'PF-VMC850-DEMO','cause_status':scenario.get('cause_status','confirmed'),'is_synthetic':True}
            case=api('/cases/'+case['id'],{'revision':case['revision'],'fields':fields},method='PUT')
            case=api('/cases/'+case['id']+'/publish',{'revision':case['revision'],'note':'發布原創合成案例供展示，不作現場維修依據'})
        outputs.append({'case_id':case['id'],'ticket_id':tid,'status':case['status'],'synthetic':True})
    print(json.dumps({'demo_cases':outputs},ensure_ascii=False))


if __name__=='__main__':main()
