from pathlib import Path
import shutil,hashlib,json,xml.etree.ElementTree as ET,html
root=Path('/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/architecture')
out=Path('/Users/tywww/.codex/visualizations/2026/10/13/01a13598-6feb-7f70-b06e-5bea303588dc/docs-refresh/final-qa');out.mkdir(exist_ok=True)
files=['runtime-boundaries.html','runtime-boundaries.drawio','module-architecture.html','module-architecture.drawio','codebase-reading-guide.md','README.md']
for name in files:shutil.copyfile(root/name,out/name)
for name in ['runtime-boundaries','module-architecture']:
 t=ET.parse(root/(name+'.drawio'));allcells=t.findall('.//mxCell');cells={c.get('id'):c for c in allcells};assert len(cells)==len(allcells)
 def box(c):
  g=c.find('mxGeometry');assert g is not None
  x,y=float(g.get('x','0')),float(g.get('y','0'));p=cells.get(c.get('parent'))
  if p is not None and p.get('vertex')=='1':px,py,*_=box(p);x+=px;y+=py
  return x,y,float(g.get('width','0')),float(g.get('height','0'))
 nodes=[];edges=[];back=[]
 for c in cells.values():
  if c.get('edge')=='1':
   assert c.get('source') in cells and c.get('target') in cells
   a=box(cells[c.get('source')]);b=box(cells[c.get('target')]);es=dict(p.split('=',1) for p in c.get('style','').split(';') if '=' in p)
   start=(a[0]+a[2]*float(es.get('exitX','1')),a[1]+a[3]*float(es.get('exitY','.5')));end=(b[0]+b[2]*float(es.get('entryX','0')),b[1]+b[3]*float(es.get('entryY','.5')))
   points=[start]+[(float(p.get('x')),float(p.get('y'))) for p in c.findall('./mxGeometry/Array/mxPoint')]+[end];routed=[start]
   for i,point in enumerate(points[1:]):
    prev=routed[-1]
    if prev[0]!=point[0] and prev[1]!=point[1]:
     vertical=(i==0 and es.get('exitY') in {'0','1'}) or (point==end and es.get('entryX') in {'0','1'})
     routed.append((prev[0],point[1]) if vertical else (point[0],prev[1]))
    routed.append(point)
   coord=' '.join(f'{x},{y}' for x,y in routed);edges.append(f'<polyline points="{coord}" fill="none" stroke="{es.get("strokeColor","#3974af")}" stroke-width="{es.get("strokeWidth","1")}" marker-end="url(#arrow)"/>')
  if c.get('vertex')!='1':continue
  x,y,w,h=box(c);sty=dict(p.split('=',1) for p in c.get('style','').split(';') if '=' in p);swim='swimlane' in c.get('style','');pad=2 if 'text;' in c.get('style','') else 4 if swim else float(sty.get('spacing','8'));lh=float(sty.get('startSize','34')) if swim else h
  (back if swim else nodes).append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{sty.get("fillColor","none")}" stroke="{sty.get("strokeColor","none")}"/><foreignObject x="{x+pad}" y="{y+pad}" width="{w-pad*2}" height="{lh-pad*2}"><div data-source-id="{c.get("id")}" xmlns="http://www.w3.org/1999/xhtml" style="font:{sty.get("fontSize","14")}px/1.2 sans-serif;color:{sty.get("fontColor","#20242c")};white-space:pre-wrap;overflow-wrap:anywhere">{html.escape(c.get("value",""))}</div></foreignObject>')
 m=t.find('.//mxGraphModel');width=int(m.get('pageWidth'));height=int(m.get('pageHeight'))
 (out/(name+'-source.html')).write_text(f'<!doctype html><html><head><meta charset="utf-8"><title>{name} XML几何核验</title></head><body style="margin:0;background:#f8fafc"><svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#3974af"/></marker></defs>{"".join(back+edges+nodes)}</svg></body></html>')
manifest={'source_root':str(root),'files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files},'source_preview':'XML geometry/labels; not native Draw.io export'}
(out/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(str(out))
