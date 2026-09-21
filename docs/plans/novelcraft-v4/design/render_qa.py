import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
screens=json.loads((ROOT/'design.json').read_text())['screens']
results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=browser.new_page(device_scale_factor=1)
 for s in screens:
  page.set_viewport_size({'width':int(s['w']),'height':int(s['h'])})
  page.set_content('<html><head><meta charset="utf-8"><style>body{margin:0}</style></head><body>'+ (ROOT/'screens'/f"{s["sid"]}.svg").read_text()+'</body></html>')
  page.wait_for_function('document.fonts.status === "loaded"')
  page.screenshot(path=str(ROOT/'previews'/f"{s['sid']}.png"))
  result=page.evaluate('''() => { const out=[]; const texts=[...document.querySelectorAll('text')]; for (const t of texts) {const a=t.getBoundingClientRect();if(a.right>innerWidth+2||a.bottom>innerHeight+2||a.left< -2||a.top< -2)out.push({name:t.dataset.name,kind:'outside',x:a.x,y:a.y,w:a.width,h:a.height});}for(let i=0;i<texts.length;i++){ const a=texts[i].getBoundingClientRect(); if(!a.width||!a.height)continue; for(let j=i+1;j<texts.length;j++){const b=texts[j].getBoundingClientRect();const ox=Math.min(a.right,b.right)-Math.max(a.left,b.left),oy=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);if(ox>4 && oy>4)out.push({kind:'text_overlap',a:texts[i].dataset.name,b:texts[j].dataset.name,overlap:[ox,oy]});}}return {textCount:texts.length,issues:out};}''')
  result['screen']=s['sid'];results.append(result)
 browser.close()
(ROOT.parent/'validation'/'design-initial-qa.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
for r in results:
 if r['issues']:print(r['screen'],len(r['issues']),r['issues'][:8])
print('rendered',len(results))
