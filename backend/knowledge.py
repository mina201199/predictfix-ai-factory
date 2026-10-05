"""Original demo documents and versioned synthetic manuals, never OEM guidance."""
import json
import re
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DOCUMENTS = [
 {'id':'SOP-DEMO-102', 'title':'示例 E102 主軸過熱檢查', 'section':'§2 檢查順序',
  'text':'E102 是本專案示例錯誤碼，不是通用 CNC 錯誤碼。主軸過熱或振動異常時，依現場規範由合格人員確認停機隔離。檢查冷卻液液位、濾網、循環流量，記錄軸承振動與潤滑狀態；復機由工程師確認。'},
 {'id':'MAN-DEMO-BEARING', 'title':'示例主軸軸承檢查', 'section':'§4 振動與潤滑',
  'text':'主軸軸承內圈、外圈與滾珠故障可能產生不同振動特徵。記錄轉速、負載、振動、溫度与潤滑。檢查異音、對心及固定件。軸承實驗分類結果不能直接換算零件健康度或剩餘壽命。'},
 {'id':'CHECK-DEMO-COOLANT', 'title':'示例冷卻系統檢查表', 'section':'§1 循環系統',
  'text':'冷卻泵、冷卻液、濾網與散熱風扇：檢查液位、清潔度、循環流量、管路洩漏與積塵。過熱未必由軸承造成，需實際量測确认。'},
 {'id':'MAN-DEMO-TOOL', 'title':'示例刀具磨耗紀錄', 'section':'§3 更換紀錄',
  'text':'切削刀具、車削刀片：記錄刀具編號、加工材質、切削時間、切削參數與刃口磨耗。使用比例與健康度不同；剩餘壽命需完整退化資料驗證。'}
]
DOCUMENTS.extend([{'id':f'FAQ-DEMO-{i:02d}','title':q,'section':'常見問題','category':'人員 FAQ','text':a} for i,(q,a) in enumerate([('刀具什麼時候該換？', '換刀不能只看累積時間；記錄加工材質、切削參數、刃口磨耗與加工品質。依機型與刀具規範安排確認，示例週期不能當成原廠標準。'), ('主軸有異音要先記錄什麼？', '記錄機台、時間、轉速、負載、溫度、振動與異音發生條件。依現場規範通報；由合格人員檢查，不自行拆卸運轉中的設備。'), ('冷卻液流量變小怎麼辦？', '記錄流量與液位，確認是否有警報或漏液。依現場規範安排濾網、管路與冷卻泵檢查，不能僅凭過熱判定軸承故障。'), ('機台漏油或漏液要怎麼通報？', '描述位置、時間、液體種類及範圍，附照片與設備編號。依現場規範處理隔離與滑倒風險，交由合格人員確認來源。'), ('尺寸突然不準該查哪裡？', '記錄量測結果、工件批次、程式版本、刀具補正與近期換刀紀錄。由工程師比較刀具磨耗、夾持、熱變位與定位誤差。'), ('換刀後能直接量產嗎？', '依公司規範完成刀具編號、補正與安裝查核，記錄試切與首件量測結果，經授權人員確認後才進入生產。'), ('警報碼 E102 都是過熱嗎？', '不是。E102 在本專案只是示例，實際警報意思必須查對應廠牌、控制器與機型手冊。通報時提供完整警報文字與截圖。'), ('健康度和使用率差在哪？', '設備使用率是排程內運轉時間比例。零件週期使用比例是累積使用量與參考週期的比值。健康度需要量測及驗證，本 DEMO 的健康度為設定值。'), ('建立工單要填什麼？', '至少填機台編號、異常發生時間、症狀、警報文字、量測與照片、近期變更及影響。先確認設備，再安排合適專長人員。'), ('如何挑選維修人員？', '比較專長、相似案例、當班可用性與未結案任務；高分只是規則配對，不代表可以跳過資格與現場安全規範。'), ('交班時應留下哪些紀錄？', '交代機台狀態、未結案工單、已做檢查、待確認項目、備品需求與接手人員。不要只寫已處理，要留量測與判斷依據。'), ('何時能結案？', '記錄問題原因、措施、更換零件及復測結果，依公司流程由授權人員確認。系統結案只是紀錄狀態，不會自動核准復機。'), ('同一機台一直報修怎麼改善？', '先核對工單是否為同一問題、同一零件或不同原因，檢查負載與保養紀錄。報修次數增加是查核線索，不能直接等同故障率。'), ('維修分析為什麼沒有 MTBF？', 'MTBF 需要可靠的故障事件與運轉時間；只有工單不足以計算。建立到結案時間也不是實際修復工時，應另外收集開始維修與完成時間。')],1)])
for d in DOCUMENTS:
    d.setdefault('category','檢查文件')
    d['source_type']='authored_demo_document'
DOCUMENTS.extend([{'id': 'GUIDE-DEMO-01', 'title': '主軸振動事件排查流程', 'section': '完整流程', 'category': '作業流程', 'text': '事件接收：記錄機台、轉速、負載、刀具、材質、發生時間與警報全文。對比近期換刀、撞刀、保養與加工條件變動，不把一次振動升高直接判成軸承故障。\n量測紀錄：記錄感測器位置、單位、採樣條件、溫度與振動波形，同一量測條件才能比較趨勢。CWRU 分類是實驗回放，不能拿分類分數當現場健康度。\n排查順序：依公司安全規範由合格人員完成必要停機與隔離，再確認冷卻、潤滑、刀具夾持、固定件、對心與軸承；禁止由聊天回答直接核准復機。\n工單與驗收：填入現象、量測、檢查項目、原因假設、採取措施與復測結果。復測須記錄負載與轉速，交由授權人員確認；仍有異音或升溫則維持追蹤，不以系統結案代表機台可運轉。'}, {'id': 'GUIDE-DEMO-02', 'title': '冷卻循環異常處理流程', 'section': '完整流程', 'category': '作業流程', 'text': '受理資料：記錄冷卻液液位、流量、溫度、警報、管路外觀、加工條件與發生時段，說明是持續不足還是間歇下降。\n檢查清單：由合格人員依安全規範確認液位、濾網、泵運轉、管路堵塞或洩漏、散熱器積塵。流量不足可能有多個原因，不能直接判定必須換泵。\n備品與派工：先核對泵與濾網料號、適用機型、庫存與替代料授權；冷卻或液壓專長人員較適合初步確認，但班別與實際可用時間仍需查核。\n完成紀錄：保存處理前後流量、溫度與警報變化，記錄清潔或更換項目與照片。復測條件應相同，達到原廠或公司規範後由授權人員判斷。此示例沒有設定通用流量門檻。'}, {'id': 'GUIDE-DEMO-03', 'title': '刀具更換與首件驗收', 'section': '完整流程', 'category': '作業流程', 'text': '換刀判斷：結合切削時間、加工材質、刃口磨耗、尺寸偏差、表面品質與刀具規範；參考週期接近門檻只是提醒，不代表刀具一定損壞。\n更換紀錄：填刀具編號、料號、加工批次、使用時間、補正值、換刀原因、執行人員與時間。不要只記換刀完成而沒有原因或量測。\n首件查核：依作業規範確認裝夾、補正與程式版本，完成試切和首件量測，保存尺寸與表面品質結果。沒有授權確認時不能由聊天助手宣告可量產。\n後續追蹤：若更換後仍異常，對比夾持、程式、熱變位與進給誤差，建立新線索或追蹤工單；不要反覆換刀卻未留下原因。'}, {'id': 'GUIDE-DEMO-04', 'title': '進給螺桿與定位誤差查核', 'section': '完整流程', 'category': '作業流程', 'text': '異常描述：記錄軸向、行程位置、方向、速度、重複性與尺寸偏差，附測量工具及校驗狀態。\n可能線索：潤滑、防塵罩、固定件、負載、熱變位、伺服警報與背隙可作為查核方向。方向不等同已確認故障原因。\n人員與量測：由伺服、螺桿或幾何精度專長人員確認，在公司安全規範與機型手冊下完成量測；不得給所有設備套用同一定位容差。\n驗收與記錄：保存處理前後定位與重複精度、測量條件、校正或更換項目。授權人員審查後才判斷復機。'}, {'id': 'GUIDE-DEMO-05', 'title': '派工、交接與未結案任務管理', 'section': '完整流程', 'category': '作業流程', 'text': '派工前：確認機台與零件、問題影響、必要資格、專長和当班可用時間。技師推薦分數為規則，不是證照或到場承諾。\n負荷判讀：正式任務來自未結案工單；同一人有多個任務時核對開始時間、預計完成時間、現場位置與是否需支援。未結案筆數不能直接當成忙碌時數。\n交接內容：寫清目前設備狀態、已做檢查、量測結果、待確認事項、備品需求與接手人。附工單連結，不只留下機台名稱。\n異常重複：同機台兩張工單先核對是否重複登錄或不同問題，避免重复派工；正式任務和展示案例不得混在同一負荷計算。'}, {'id': 'GUIDE-DEMO-06', 'title': '工單結案與改善追蹤', 'section': '完整流程', 'category': '作業流程', 'text': '結案條件：至少記錄檢查發現、原因、措施、使用零件及復測結果，依公司流程由授權人員確認。工單結案不是復機授權。\n時間資料：建立時間、接單時間、實際開始維修、完成維修、等待備品與復機時間應分開記錄。建立到結案的耗時包含等待，不能稱為純修復工時。\n改善追蹤：查看同設備與同症狀是否再次發生，核對作業條件、備品、保養与根因。報修次數只是線索，不能單憑工單數量估計故障率。\n成效衡量：有真實運轉時間和故障事件才能算 MTBF，有停機與成本資料才能估計節省金額；不足時顯示資料不足，避免虛構收益。'}, {'id': 'GUIDE-DEMO-07', 'title': '設備健康與風險圖例說明', 'section': '完整流程', 'category': '作業流程', 'text': '本系統設備使用率是本班運轉時間占排程時間的比例；零件週期使用比例是累積使用量除以設定參考週期。兩者高不代表一定故障。\n展示健康值：低於45為紅色警示，45到69為黃色注意，70以上為綠色正常；無量測資料以灰色未知呈現。這些門檻是 DEMO 規則，並非校準故障機率。\n巡檢順序：依最低零件健康展示排序，必要時結合使用率、未結案任務與現場影響。高風險和高使用率可作為優先查核方向，不能自行決定停機或換件。\n模型邊界：軸承實驗分类没有正常類別，不能計算真實健康度、剩餘壽命或未来故障風險。後續必須用實機資料獨立驗證。'}, {'id': 'GUIDE-DEMO-08', 'title': '漏油、漏液與現場通報', 'section': '完整流程', 'category': '作業流程', 'text': '通報內容：機台編號、位置、發生時間、液體種類、洩漏範圍、警報、設備狀態與照片；液體種類不明時不要憑顏色下結論。\n現場處理：依公司規範處理人員與滑倒風險，由合格人員確認必要停機與隔離。不得依聊天助手建議拆卸或觸碰運轉中的零件。\n排查資料：核對液位、接頭、密封、管路與近期更換紀錄。將查核結果寫入工單，先確認來源再決定零件。\n修復驗收：保存更換或修復內容、測試條件、處理前後照片與是否再次滲漏，由授權人員確認。'}])
def load_manuals(directory):
    """Keep section boundaries, source lines and applicability with every excerpt."""
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    documents, chunks = [], []
    for entry in manifest['manuals']:
        path = (directory / entry['file']).resolve()
        if path.parent != directory.resolve() or path.suffix != '.md':
            raise ValueError('Manual path must stay inside the corpus directory')
        content = path.read_text(encoding='utf-8')
        metadata = {k: v for k, v in entry.items() if k != 'file'}
        metadata.update(source_type='synthetic_demo_manual', is_synthetic=True,
                        source_path='docs/manuals/' + entry['file'])
        documents.append({**metadata, 'section': '完整手冊', 'text': content})
        lines = content.splitlines()
        boundaries = [i for i, line in enumerate(lines) if re.match(r'^## ', line)]
        for start, end in zip(boundaries, boundaries[1:] + [len(lines)]):
            section = lines[start][3:].strip()
            excerpt = '\n'.join(lines[start + 1:end]).strip()
            if not excerpt:
                continue
            # Each authored section is a coherent unit; preserve whole tables and
            # their qualifications rather than cutting fixed character windows.
            chunks.append({**metadata, 'chunk_id': entry['id'] + ':' + section.split()[0],
                           'section': section, 'line_start': start + 1,
                           'line_end': end, 'text': excerpt})
    return documents, chunks


for document in DOCUMENTS:
    document.setdefault('source_type', 'authored_demo_document')
    document.setdefault('is_synthetic', True)
CHUNKS=[{**d,'section':d['section']+f' · 段 {i//240+1}','text':d['text'][i:i+300]} for d in DOCUMENTS for i in range(0,len(d['text']),240)]
manual_documents, manual_chunks = load_manuals(Path(__file__).resolve().parents[1] / 'docs' / 'manuals')
DOCUMENTS.extend(manual_documents)
CHUNKS.extend(manual_chunks)
vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2,4))
matrix = vectorizer.fit_transform([d['title']+' '+d['text'] for d in CHUNKS])

def retrieve(query, limit=3):
    scores = cosine_similarity(vectorizer.transform([query]), matrix)[0]
    return [{**CHUNKS[i], 'score':round(float(scores[i]),4)}
            for i in scores.argsort()[::-1][:limit] if scores[i] >= .03]
