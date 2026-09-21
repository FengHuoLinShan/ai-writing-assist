from pathlib import Path
import json,re,xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'design';data=json.loads((D/'design.json').read_text());ids={s['sid'] for s in data['screens']}
def walk(n):
 yield n
 for c in n.get('children',[]):yield from walk(c)
nodes=[n for s in data['screens'] for n in walk(s)];hotspots=[n for n in nodes if n.get('target')];bad=[n['target'] for n in hotspots if n['target'] not in ids]
for s in data['screens']:ET.parse(D/'screens'/f'{s["sid"]}.svg')
checks={'screen_count':len(ids),'design_nodes':len(nodes),'hotspot_count':len(hotspots),'unknown_targets':bad,'svg_xml_valid':True,'native_figma_runtime_executed':False,'production_backend_tests_executed':False};errors=[]
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1680,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)));page.set_content((D/'prototype.html').read_text());page.wait_for_selector('#art svg');checks['initial_view']=page.locator('#screenTitle').inner_text();page.locator('[data-id="S20"]').click();assert page.locator('#screenTitle').inner_text().startswith('S20');page.locator('#art [data-target="S21"]').first.click();assert page.locator('#screenTitle').inner_text().startswith('S21');page.locator('#back').click();assert page.locator('#screenTitle').inner_text().startswith('S20');checks['map_scene_back_navigation']=True
 page.locator('#info').click();assert page.locator('#notes').is_visible();page.keyboard.press('Escape');assert page.locator('#notes').is_hidden();checks['notes_open_escape']=True
 page.locator('#filter').fill('移动');checks['mobile_filter_count']=page.locator('#list .navitem').count();page.locator('#filter').fill('')
 for sid in sorted(ids):
  page.evaluate('(sid)=>{if(active!==sid)go(sid);}',sid);assert page.locator('#screenTitle').inner_text().startswith(sid)
 checks['all_views_rendered']=True
 page.evaluate("go('S06')");page.screenshot(path=str(ROOT/'design/previews/PROTOTYPE-writing.png'))
 page.evaluate("go('S20')");page.screenshot(path=str(ROOT/'design/previews/PROTOTYPE-map.png'))
 page.set_viewport_size({'width':420,'height':932});page.evaluate("go('S37')");page.wait_for_timeout(80);checks['mobile_prototype_document_width']=page.evaluate('document.documentElement.scrollWidth');page.screenshot(path=str(ROOT/'design/previews/PROTOTYPE-mobile.png'));browser.close()
checks['browser_errors']=errors;assert not errors;assert not bad
(ROOT/'validation/prototype-qa.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));print(json.dumps(checks,ensure_ascii=False,indent=2))
