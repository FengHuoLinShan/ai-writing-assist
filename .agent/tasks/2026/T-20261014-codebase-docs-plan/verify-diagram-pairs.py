"""Check XML IDs/edges and the exact runtime labels without browser I/O."""
from pathlib import Path
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
ROOT=Path('/Users/tywww/.codex/worktrees/docs-refresh-luna/ai-writing-assist/docs/architecture')
class Labels(HTMLParser):
 def __init__(self):super().__init__();self.active=False;self.labels=[];self.in_heading=False;self.headings=[]
 def handle_starttag(self,tag,attrs):
  if tag=='li':self.active=True;self.labels.append('')
  if tag=='h2':self.in_heading=True;self.headings.append('')
 def handle_endtag(self,tag):
  if tag=='li':self.active=False
  if tag=='h2':self.in_heading=False
 def handle_data(self,d):
  if self.active:self.labels[-1]+=d
  if self.in_heading:self.headings[-1]+=d
for name in ['runtime-boundaries','module-architecture']:
 cells=ET.parse(ROOT/(name+'.drawio')).findall('.//mxCell');by_id={c.get('id'):c for c in cells}
 assert len(by_id)==len(cells)
 for c in cells:
  if c.get('edge')=='1':assert c.get('source') in by_id and c.get('target') in by_id
 if name=='runtime-boundaries':
  parser=Labels();parser.feed((ROOT/(name+'.html')).read_text())
  expected=[by_id[f'{key}-{i}'].get('value') for key in ['writing','evolution','rp','image'] for i in range(5)]
  assert parser.labels==expected,(parser.labels,expected)
  assert len(expected)==20
  assert parser.headings[:4]==[by_id[key+'-heading'].get('value') for key in ['writing','evolution','rp','image']]
  pairs={(c.get('source'),c.get('target')) for c in cells if c.get('edge')=='1'}
  assert pairs=={(f'{key}-{i}',f'{key}-{i+1}') for key in ['writing','evolution','rp','image'] for i in range(4)}
 print(name,'IDs/edges passed; runtime exact-label parity checked' if name=='runtime-boundaries' else 'IDs/edges passed')

# The changed module labels stay image-specific in both sources.
module_html=(ROOT/'module-architecture.html').read_text()
assert 'local_agent 本机图片设备' in module_html
assert '作者 Mac 图片 CLI 租约' in module_html
assert '图片 CLI 出站租约' in by_id['rt_mac'].get('value')
assert '旧 job 兼容' in by_id['local_agent'].get('value') and '旧 job 兼容' in module_html
print('Runtime headings, 16 ordered edges, module image/legacy boundary parity passed.')
