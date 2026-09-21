from __future__ import annotations
import json, math, re, html, os, copy
from pathlib import Path
from PIL import ImageFont
ROOT=Path(__file__).resolve().parent
P={'bg':'#F6F4F0','surface':'#FFFDF9','muted':'#EEEBE5','ink':'#1E2A3B','body':'#485365','dim':'#667281','accent':'#284C56','accentSoft':'#E5EEEB','ai':'#6D5C95','aiSoft':'#EFEAF5','success':'#326F62','successSoft':'#E8F1EB','warning':'#91601D','warningSoft':'#F7EEDB','error':'#AC4544','errorSoft':'#F9E8E3','border':'#DEDCD5','white':'#FFFFFF','mapBg':'#182B36','mapLand':'#34504E','mapLine':'#6F8980','mapText':'#E1E9E3'}
REG='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'; BOLD='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
FONTS={}
def measure(s,size=14,bold=False):
 k=(size,bold)
 if k not in FONTS:FONTS[k]=ImageFont.truetype(BOLD if bold else REG,size,index=2)
 return FONTS[k].getlength(s)
def wrap(s,w,size=14,bold=False):
 lines=[]
 for para in str(s).replace('Scene','场景').split('\n'):
  line=''
  for ch in para:
   if line and measure(line+ch,size,bold)>w-2:lines.append(line);line=ch
   else:line+=ch
  lines.append(line)
 return lines
seq=0

def node(typ,name,x=0,y=0,w=0,h=0,**kw):
 global seq
 seq+=1
 return {'id':f'n{seq}','type':typ,'name':name,'x':round(x,3),'y':round(y,3),'w':round(w,3),'h':round(h,3),**kw}

def group(parent,name,x,y,w,h,fill=None,r=0,stroke=None,layout=None):
 n=node('frame',name,x,y,w,h,children=[],fill=fill,r=r,stroke=stroke)
 if layout:n['layout']=layout
 parent['children'].append(n);return n

def rect(p,x,y,w,h,fill='surface',r=0,stroke=None,name='Surface',opacity=1):
 n=node('rect',name,x,y,w,h,fill=fill,r=r,stroke=stroke,opacity=opacity);p['children'].append(n);return n

def line(p,x1,y1,x2,y2,fill='border',sw=1,dash=None,name='Divider'):
 return path(p,f'M {x1} {y1} L {x2} {y2}',stroke=fill,sw=sw,dash=dash,name=name)

def path(p,d,fill=None,stroke=None,sw=1,dash=None,name='Vector',opacity=1):
 n=node('path',name,d=d,fill=fill,stroke=stroke,sw=sw,dash=dash,opacity=opacity);p['children'].append(n);return n

def ellipse(p,x,y,w,h,fill='accent',stroke=None,sw=1,name='Ellipse',opacity=1):
 n=node('ellipse',name,x,y,w,h,fill=fill,stroke=stroke,sw=sw,opacity=opacity);p['children'].append(n);return n

def txt(p,s,x,y,w=None,size=14,color='ink',weight='Regular',lh=1.55,serif=False,name=None):
 bold=weight in ('Bold','Medium','SemiBold')
 w=w if w is not None else math.ceil(measure(str(s),size,bold))+5
 lines=wrap(s,w,size,bold)
 n=node('text',name or str(s).replace('\n',' ')[:54],x,y,w,math.ceil(size*lh*len(lines)),text='\n'.join(lines),font='Noto Serif SC' if serif else 'Noto Sans SC',size=size,weight=weight,lh=round(size*lh,3),color=color)
 p['children'].append(n);return n

def icon(p,name,x,y,size=20,color='dim'):
 g=group(p,'Icon / '+name,x,y,size,size)
 shapes={
 'book':'M 3 4 Q 8 2 12 5 Q 16 2 21 4 L 21 20 Q 16 18 12 21 Q 8 18 3 20 Z M 12 5 L 12 21',
 'home':'M 3 11 L 12 3 L 21 11 M 5 10 L 5 21 L 10 21 L 10 15 L 14 15 L 14 21 L 19 21 L 19 10',
 'write':'M 4 20 L 8 19 L 20 7 L 16 3 L 4 15 Z M 14 5 L 18 9 M 3 22 L 21 22',
 'world':'M 3 12 A 9 9 0 1 0 21 12 A 9 9 0 1 0 3 12 M 3 12 L 21 12 M 12 3 C 5 9 5 15 12 21 C 19 15 19 9 12 3',
 'map':'M 2 5 L 8 2 L 16 5 L 22 2 L 22 19 L 16 22 L 8 19 L 2 22 Z M 8 2 L 8 19 M 16 5 L 16 22',
 'check':'M 4 12 L 9 17 L 20 5',
 'search':'M 16 10 A 6 6 0 1 0 4 10 A 6 6 0 1 0 16 10 M 15 15 L 22 22',
 'spark':'M 12 2 L 15 9 L 22 12 L 15 15 L 12 22 L 9 15 L 2 12 L 9 9 Z',
 'tree':'M 5 3 L 5 19 L 19 19 M 5 7 L 19 7 M 12 7 L 12 13 L 19 13',
 'clock':'M 3 12 A 9 9 0 1 0 21 12 A 9 9 0 1 0 3 12 M 12 6 L 12 12 L 17 15',
 'arrow':'M 4 12 L 20 12 M 14 6 L 20 12 L 14 18',
 'close':'M 5 5 L 19 19 M 19 5 L 5 19',
 'plus':'M 12 4 L 12 20 M 4 12 L 20 12',
 'back':'M 19 12 L 4 12 M 10 6 L 4 12 L 10 18',
 'layers':'M 2 8 L 12 2 L 22 8 L 12 14 Z M 2 13 L 12 19 L 22 13 M 2 18 L 12 24 L 22 18',
 'settings':'M 4 7 L 20 7 M 4 17 L 20 17 M 9 3 L 9 11 M 16 13 L 16 21',
 'expand':'M 9 3 L 3 3 L 3 9 M 15 3 L 21 3 L 21 9 M 3 15 L 3 21 L 9 21 M 21 15 L 21 21 L 15 21',
 'lock':'M 6 10 L 6 7 A 6 6 0 0 1 18 7 L 18 10 M 4 10 L 20 10 L 20 22 L 4 22 Z M 12 14 L 12 18',
 }
 n=path(g,shapes.get(name,shapes['spark']),stroke=color,sw=1.65,name='Stroke')
 n['scale']=size/24
 return g

def button(p,label,x,y,w=None,kind='primary',target=None,size=14):
 w=w or max(90,math.ceil(measure(label,size,True))+36)
 bg='accent' if kind=='primary' else 'error' if kind=='danger' else 'surface' if kind=='secondary' else 'muted' if kind=='disabled' else None
 fg='white' if kind in ('primary','danger') else 'dim' if kind=='disabled' else 'accent' if kind=='quiet' else 'ink'
 g=group(p,'Button / '+label,x,y,w,44,bg,10,'border' if kind=='secondary' else None,{'mode':'HORIZONTAL','pad':16,'align':'CENTER','gap':8})
 t=txt(g,label,0,(44-size*1.55)/2,w,size,fg,'Medium');t['align']='center'
 g['component']='Button/'+kind;g['label']=label
 if target:g['target']=target
 return g

def chip(p,label,x,y,kind='accent',w=None):
 w=w or math.ceil(measure(label,12,True))+20
 g=group(p,'Status / '+label,x,y,w,28,kind+'Soft' if kind+'Soft' in P else 'muted',7,layout={'mode':'HORIZONTAL','pad':10,'align':'CENTER','gap':0})
 t=txt(g,label,0,4,w,12,kind if kind in P else 'dim','Medium');t['align']='center';g['component']='Status/'+kind;g['label']=label
 return g

def panel(p,x,y,w,h,title=None,kicker=None,bg='surface'):
 g=group(p,title or 'Panel',x,y,w,h,bg,16,'border')
 if kicker:txt(g,kicker,24,18,w-48,11,'dim','Medium')
 if title:txt(g,title,24,40 if kicker else 20,w-48,19,'ink','Medium')
 return g

def card(p,x,y,w,h,title,body,tag=None,kind='accent',cta=None,target=None):
 g=panel(p,x,y,w,h)
 yy=22
 if tag:chip(g,tag,22,yy,kind);yy+=43
 title_node=txt(g,title,22,yy,w-44,18 if h<260 else 20,'ink','Medium');yy+=title_node['h']+12
 t=txt(g,body,22,yy,w-44,13 if h<260 else 14,'body');
 if cta:button(g,cta,22,h-64,w-44,'secondary',target)
 return g

def row(p,title,sub,x,y,w,status=None,target=None,ico='book'):
 g=group(p,title,x,y,w,76)
 icon(g,ico,0,12,22,'accent');txt(g,title,36,4,w-170 if status else w-42,15,'ink','Medium');txt(g,sub,36,31,w-70,12,'dim')
 if status:chip(g,status,w-115,8,'success' if status in ('已保存','已核对','已完成') else 'warning',110)
 line(g,0,70,w,70)
 if target:g['target']=target
 return g

NAV=[('home','概览','S01'),('write','写作','S06'),('tree','故事结构','S11'),('world','世界资料','S13'),('map','故事地图','S20'),('check','待我决定','S16')]
SCREENS=[]

def screen(sid,title,category='创作',subtitle='',active='写作',right=False,mobile=False,full=False):
 w,h=(390,844) if mobile else (1440,960)
 s=node('frame',sid+' · '+title,0,0,w,h,children=[],fill='bg',r=0);s.update(sid=sid,title=title,category=category,subtitle=subtitle,mobile=mobile,full=full,notes=[])
 SCREENS.append(s)
 if mobile:
  rect(s,0,0,390,46,'surface');txt(s,'9:41',22,12,80,13,'ink','Medium');txt(s,'5G  ▰',308,12,65,12,'ink')
  return s
 if full:return s
 rect(s,0,0,196,960,'surface');line(s,196,0,196,960)
 rect(s,22,23,32,32,'accent',9);icon(s,'book',28,28,20,'white');txt(s,'NovelCraft',66,21,116,18,'ink','Medium')
 txt(s,'我的作品',24,92,140,11,'dim','Medium');txt(s,'白石城来信',24,119,148,19,'ink','Bold');txt(s,'长篇小说  /  作者工作区',24,151,150,11,'dim')
 for i,(ico,label,target) in enumerate(NAV):
  yy=212+i*52
  if label==active:rect(s,12,yy-7,172,44,'accentSoft',9)
  g=group(s,'Navigation / '+label,24,yy,156,32);icon(g,ico,0,0,20,'accent' if label==active else 'dim');txt(g,label,34,-2,120,14,'accent' if label==active else 'body','Medium' if label==active else 'Regular');g['target']=target
 line(s,24,552,172,552)
 txt(s,'工作状态',24,579,144,11,'dim','Medium');ellipse(s,25,621,6,6,'success');txt(s,'尚未开始理解' if sid in ('S02','S34') else '理解已更新至第 12 章',39,612,139,11,'body');txt(s,'从你的原文开始' if sid in ('S02','S34') else '1 项需要你决定',24,647,148,12,'warning')
 for i,(label,target,ico) in enumerate([('运行与恢复','S28','clock'),('模型与授权','S29','settings')]):
  g=group(s,'Navigation / '+label,24,793+i*48,152,36);icon(g,ico,0,0,18);txt(g,label,32,-2,120,12,'body');g['target']=target
 txt(s,'V4 设计样例 · 非生产数据',24,918,154,10,'dim')
 if sid in ('S06','S07','S10','S17'):
  txt(s,'章节',24,693,148,11,'dim','Medium');button(s,'第 12 章  ▾',18,715,158,'secondary','S11',12)
 rect(s,197,0,1243,64,'surface');line(s,196,64,1440,64)
 txt(s,'白石城来信',228,19,200,13,'body');txt(s,'/  '+category,359,19,300,13,'dim')
 g=group(s,'Command search',932,12,258,40,'bg',10);icon(g,'search',13,10,17);txt(g,'找人物、场景、原文…',42,9,190,12,'dim');g['target']='S42'
 chip(s,'未开始' if sid in ('S02','S34') else '已保存',1210,18,'accent' if sid in ('S02','S34') else 'success',72);button(s,'项目设置',1300,10,110,'quiet','S32',12)
 txt(s,title,228,96,810,28,'ink','Bold');
 if subtitle:txt(s,subtitle,228,141,900 if not right else 800,13,'dim')
 return s


def companion(s,title='接下来，先做这一件事',body='先核对眼前最相关的一项信息。其他建议收在下方，不打断写作。',tag='与你当前的段落有关',primary='查看建议',target='S07'):
 g=panel(s,1068,188,344,700)
 icon(g,'spark',22,22,22,'ai');txt(g,'写作伙伴',55,20,160,17,'ink','Medium');button(g,'当前',16,52,92,'quiet','S06',12);button(g,'讨论',122,52,92,'quiet','S27',12);button(g,'历史',228,52,92,'quiet','S28',12);line(g,22,101,322,101)
 chip(g,tag,22,124,'ai',300)
 txt(g,title,22,174,300,22,'ink','Medium');t=txt(g,body,22,237,300,15,'body');button(g,primary,22,352,300,'primary',target)
 txt(g,'依据',22,425,300,12,'dim','Medium');txt(g,'第 12 章 · 当前选段\n人物：林舟、青竹',22,455,300,13,'body')
 line(g,22,524,322,524);txt(g,'还有 2 个可选方向',22,545,284,14,'ink');txt(g,'不会自动修改正文或采用新设定。',22,590,288,12,'dim');button(g,'展开其他想法',22,630,300,'quiet','S09')
 return g

def landscape(p,x,y,w,h,night=False,name='白石城 / 场景插画'):
 g=group(p,name,x,y,w,h,'mapBg' if night else '#E4E9E2',14)
 g['clip']=True
 sky='#162E3A' if night else '#DCE7E4';rect(g,0,0,w,h,sky,14)
 ellipse(g,w*.68,h*.08,h*.22,h*.22,'#D4C5A0' if night else '#FCF2D4',opacity=.8)
 for off,col in [(0,'#78978B' if not night else '#345157'),(45,'#5F8179' if not night else '#28454D'),(95,'#466B64' if not night else '#203E49')]:
  path(g,f'M 0 {h*.54+off} C {w*.19} {h*.05+off} {w*.26} {h*.5+off} {w*.4} {h*.31+off} S {w*.65} {h*.17+off} {w} {h*.58+off} L {w} {h} L 0 {h} Z',fill=col,name='Mountain ridge')
 path(g,f'M {w*.15} {h} C {w*.45} {h*.53} {w*.52} {h*.8} {w*.73} {h*.49} L {w*.81} {h*.5} C {w*.57} {h*.93} {w*.49} {h*.78} {w*.46} {h} Z',fill='#A5C1B7' if not night else '#5B8188',name='River light')
 cy=h*.50
 for i in range(12):
  bx=w*.36+i*w*.029;bh=h*(.07+.07*((i*7)%5)/5)
  rect(g,bx,cy-bh,w*.024,bh,'#E6DEC8' if not night else '#B8C7BC',1,name='City building')
  path(g,f'M {bx-2} {cy-bh} L {bx+w*.012} {cy-bh-8} L {bx+w*.024+2} {cy-bh} Z',fill='#44615C',name='City roof')
 rect(g,w*.34,cy,w*.39,h*.04,'#C8CFBA' if not night else '#849F96',name='City wall')
 for i in range(17):
  xx=(i*67+17)%(max(1,int(w)));yy=h*.73+(i%3)*h*.055
  path(g,f'M {xx} {yy-22} L {xx-12} {yy+8} L {xx+12} {yy+8} Z',fill='#30534D' if not night else '#17333D',name='Foreground pine')
 return g

def portrait(p,x,y,w,h,who='林舟',tint='#CBDAD6'):
 g=group(p,'人物形象 / '+who,x,y,w,h,tint,12)
 g['clip']=True
 ellipse(g,w*.28,h*.13,w*.45,w*.45,'#E4CEB6')
 path(g,f'M {w*.27} {h*.33} Q {w*.17} {h*.03} {w*.47} {h*.07} Q {w*.79} {h*.05} {w*.74} {h*.37} Q {w*.67} {h*.19} {w*.52} {h*.2} Q {w*.36} {h*.23} {w*.27} {h*.33} Z',fill='#293D40')
 path(g,f'M {w*.04} {h} Q {w*.04} {h*.6} {w*.37} {h*.53} L {w*.5} {h*.66} L {w*.62} {h*.53} Q {w*.98} {h*.62} {w*.99} {h} Z',fill='#496C6A')
 path(g,f'M {w*.37} {h*.53} L {w*.5} {h*.66} L {w*.65} {h*.53} L {w*.58} {h} L {w*.43} {h} Z',fill='#D1CCB8')
 return g

def keyart(p,x,y,w,h):
 g=group(p,'物品形象 / 铜钥匙',x,y,w,h,'#EEE8D9',12)
 ellipse(g,w*.26,h*.18,w*.25,w*.25,None,'#9D783F',max(2,w*.027))
 path(g,f'M {w*.45} {h*.41} L {w*.75} {h*.72} M {w*.63} {h*.58} L {w*.74} {h*.49} M {w*.72} {h*.68} L {w*.84} {h*.58}',stroke='#9D783F',sw=max(4,w*.05),name='Copper key')
 return g

def atlas(p,x,y,w,h,dark=True,journey=False):
 g=group(p,'故事地图 / 不按比例示意',x,y,w,h,'mapBg' if dark else '#E5ECE7',18)
 g['clip']=True
 land='#33514F' if dark else '#CCDCCF'; contours='#57766D' if dark else '#ADC7B4';ink='mapText' if dark else 'accent'
 path(g,f'M 0 {h*.11} C {w*.19} {h*.02} {w*.16} {h*.28} {w*.35} {h*.08} Q {w*.63} {h*.21} {w*.71} 0 L {w} 0 L {w} {h} L 0 {h} Z',fill=land,name='Land mass')
 for i in range(10):
  off=i*32
  path(g,f'M {-40+off} 0 C {w*.28+off} {h*.15} {w*.02+off} {h*.3} {w*.23+off} {h*.45} S {w*.32+off} {h*.77} {w*.53+off} {h}',stroke=contours,sw=.8,opacity=.5,name='Topographic contour')
 path(g,f'M {w*.17} 0 C {w*.46} {h*.2} {w*.2} {h*.28} {w*.42} {h*.49} S {w*.5} {h*.7} {w*.72} {h}',stroke='#80AAA9' if dark else '#90B7B4',sw=24,name='River')
 path(g,f'M {w*.17} 0 C {w*.46} {h*.2} {w*.2} {h*.28} {w*.42} {h*.49} S {w*.5} {h*.7} {w*.72} {h}',stroke='#ACCCBF',sw=2,opacity=.6,name='River center')
 pts=[(.23,.65,'白石城'),(.48,.36,'北岸渡口'),(.70,.55,'回声井'),(.75,.17,'苍岫山'),(.39,.81,'南门旧道')]
 if journey:
  path(g,f'M {w*.23} {h*.65} Q {w*.50} {h*.7} {w*.70} {h*.55}',stroke='#E2C890',sw=2.5,dash='8 8',name='中间路径未知 / 非实际行程')
  txt(g,'中间路径未知',w*.40,h*.65,150,12,ink)
 else:
  path(g,f'M {w*.23} {h*.65} Q {w*.31} {h*.4} {w*.48} {h*.36} L {w*.70} {h*.55}',stroke='#A8A88B' if dark else '#8D9A78',sw=2,dash='3 7',name='既有地理连接示意')
 for i,(xx,yy,label) in enumerate(pts):
  px,py=xx*w,yy*h
  if i==0:
   ellipse(g,px-24,py-24,48,48,'#B7D4C3',opacity=.15);rect(g,px-12,py-10,24,20,'#DCE5D5',4);icon(g,'home',px-10,py-11,20,'accent')
  else:ellipse(g,px-5,py-5,10,10,'#D8DCC8' if dark else 'accent',stroke='#E2C890',sw=1)
  label_size=14 if w<500 else 16
  label_w=min(150,math.ceil(measure(label,label_size,True))+8)
  lx=px+18
  if lx+label_w>w-16:lx=px-18-label_w
  if p.get('sid')=='S20' and i==2:lx=px-18-label_w
  if not (p.get('sid')=='S20' and i==3):txt(g,label,lx,py-16,label_w,label_size,ink,'Medium')
 for i in range(19):
  mx=(i*59+22)%max(1,int(w*.9));my=(i*47+40)%max(1,int(h*.8))
  if abs(mx-w*.23)<70 and abs(my-h*.65)<55:continue
  path(g,f'M {mx-10} {my+11} L {mx} {my-7} L {mx+10} {my+11} M {mx+8} {my+11} L {mx+18} {my-13} L {mx+31} {my+11}',stroke=contours,sw=1.3,name='Mountain symbol')
 compass_y=114 if p.get('sid') in ('S20','S22') else 26
 compass_x=974 if p.get('sid')=='S20' else w-66
 txt(g,'北  ↑',compass_x,compass_y,60,12,ink)
 legend_y=772 if p.get('sid')=='S20' else h-140 if w<500 else h-42
 txt(g,'空间关系示意 · 不按比例',24,legend_y,250,12,ink)
 return g

def prose(p,x,y,w,short=False):
 paragraphs=['暮色落在白石城的石阶上。林舟把湿透的外衣搭在椅背，听见窗外有人轻轻叩了三下。','青竹没有立刻进门。她站在门廊的阴影里，手里攥着那把铜钥匙，像是还没想好应当把它交给谁。','“先放在你这里。”林舟说，“等北岸的信到了，我会回来取。”','她抬起眼，问的却是另一件事：“你真的见过井底的那个人？”','远处传来钟声。林舟的手停在灯芯上，火光晃了一下，照亮了他袖口尚未干透的水迹。']
 yy=y
 for para in paragraphs[:3 if short else 5]:
  t=txt(p,para,x,yy,w,19,'body','Regular',1.95,True);yy+=t['h']+22
 return yy

# S01
s=screen('S01','今天，继续你的故事','作品概览','所有资料围绕这部小说更新；你只需要决定重要的事。',active='概览')
g=panel(s,228,190,760,306);landscape(g,424,0,336,306);txt(g,'继续上次写作',28,25,348,12,'dim','Medium');txt(g,'第 12 章\n没有寄出的信',28,62,355,31,'ink','Bold');txt(g,'停在青竹询问井底之人的段落。\n最近保存的正文与理解范围已对齐。',28,166,345,14,'body');button(g,'继续写作',28,239,180,target='S06')
g=panel(s,1012,190,400,306);txt(g,'需要你决定',24,25,345,20,'ink','Medium');chip(g,'1 项影响后续',24,74,'warning');txt(g,'铜钥匙是暂时保管，\n还是已经赠予青竹？',24,123,345,19,'ink','Medium');txt(g,'系统保留了两种解释，没有擅自改变所有权。',24,189,345,13,'dim');button(g,'看原文再决定',24,239,348,'secondary','S05')
for x,title,body,target in [(228,'理解这本书','追踪人物变化、开放问题与已知边界。','S13'),(632,'在地图中回看','白石城、渡口与故事发生的地方。','S20'),(1036,'探索新方向','从人物、悬念和情绪三个角度展开。','S09')]:
 g=card(s,x,524,376,216,title,body,cta='打开',target=target)
g=panel(s,228,768,1184,120);txt(g,'最近变化',24,19,200,16,'ink','Medium');txt(g,'第 12 章已保存   ·   新增 3 条有据观察   ·   1 条解释待核对   ·   图片未自动生成',24,56,1070,14,'body')
s['notes']=['按创作任务而非模块计数组织首页。','待决定项只计真实领域回执，系统理解与正式设定分开。']
# S02
s=screen('S02','把故事带进来','开始一本书','上传正文后即可继续写作；系统按顺序阅读，不要求你手动运行抽取阶段。',active='概览')
g=panel(s,228,190,1184,208);rect(g,26,26,1132,154,'accentSoft',12);icon(g,'book',56,65,38,'accent');txt(g,'拖入小说正文，或选择文件',116,49,700,23,'ink','Medium');txt(g,'TXT、EPUB、HTML   ·   保留你的原文与版本   ·   示例：白石城来信.txt',116,95,920,14,'body');button(g,'选择文件',910,64,180,'primary','S03')
for x,title,body,tag in [(228,'读取已有正文','从第一章开始建立理解。系统会先核对来源，再按场景逐步推进。','默认推荐'),(632,'从空白开始写','先写一句、一段或一个设想。没有地图或大纲，也能开始。','无需配置'),(1036,'接着已有作品','核对新增、修改和移除的章节；旧版本继续保留。','先看差异')]:card(s,x,426,376,248,title,body,tag)
g=panel(s,228,703,1184,185);txt(g,'自动整理范围',24,24,380,19,'ink','Medium');txt(g,'允许阅读与派生理解；正式设定仍由你采用。\n不自动联网、不生成付费图片、不修改原文。',24,65,756,15,'body');button(g,'查看授权与预算',878,102,280,'secondary','S29')
# S03
s=screen('S03','先核对这次导入','正文来源确认','预览不会覆盖任何章节。确认后追加新版本，系统只重查受影响部分。',active='概览')
g=panel(s,228,190,800,610);txt(g,'白石城来信 · 修订稿.txt',24,25,752,21,'ink','Medium');chip(g,'2 章新增',24,75,'success');chip(g,'1 章修改',134,75,'warning');chip(g,'0 章移除',244,75,'accent');
for i,(t,b,st) in enumerate([('第 10 章 · 雨后的渡口','地点描写发生变化；旧稿保留。','需要重查'),('第 13 章 · 远来的客人','追加到作品末尾，不改变已有章节顺序。','新增'),('第 14 章 · 回声','追加到作品末尾。','新增')]):row(g,t,b,24,139+i*93,752,st,'S33')
txt(g,'处理后：原文版本保留；第 10 章之后的相关理解标记待更新。',24,469,735,14,'body');button(g,'确认导入并开始理解',24,540,752,'primary','S04')
g=card(s,1052,190,360,352,'你仍然掌握原稿','系统不会因为理解结果不同就改写正文。涉及已有设定的变化，会整理成一个可核对的决定包。','保存范围','accent',cta='返回调整',target='S02')
g['children'][-1]['target']='S02'
# S04
s=screen('S04','故事正在逐步被理解','持续演化','你可以继续创作，已提交的结果随时可用；一处不确定不会伪装成全书完成。',active='概览')
g=panel(s,228,190,760,298);txt(g,'已理解至第 12 章',28,23,700,26,'ink','Bold');txt(g,'正在核对第 13 章的身份与事件变化',28,77,700,15,'body');rect(g,28,128,704,8,'muted',4);rect(g,28,128,535,8,'accent',4);txt(g,'原文已读取 14 / 14 章',28,159,340,14,'body');txt(g,'可信批次已提交 12 / 14 章',377,159,350,14,'body');chip(g,'1 项待你决定',28,209,'warning');button(g,'先继续写作',518,209,213,'primary','S06')
g=panel(s,1012,190,400,298);txt(g,'你的控制',24,26,352,20,'ink','Medium');txt(g,'本次范围：第 1—14 章\n仅整理理解与候选，不自动采用。\n已用请求 18 / 60（设计样例）',24,79,352,15,'body');button(g,'暂停自动整理',24,204,352,'secondary','S35')
g=panel(s,228,516,1184,372);txt(g,'不是一个笼统的“完成百分比”',24,20,1120,19,'ink','Medium')
for i,(t,b,st) in enumerate([('原文与检索','最新来源已保存，可直接回读。','已完成'),('世界工作状态','按场景提交；保留人物信念、事实与未知。','已核对'),('持续理解','2 条解释正在重查；不会覆盖已确认事实。','处理中'),('地图与配图','已有地图可浏览；缺图不阻塞正文理解。','可浏览')]):row(g,t,b,24,69+i*68,1136,st,'S28',ico='check')
# S05
s=screen('S05','这把钥匙，是保管还是赠予？','需要你决定','只处理真正影响后续理解的一项歧义。你可以保留未知，不必替系统补全一切。',active='待我决定')
g=panel(s,228,190,702,595);txt(g,'原文 · 第 12 章',24,22,660,13,'dim','Medium');txt(g,'“先放在你这里。等北岸的信到了，\n我会回来取。”',30,78,640,26,'ink','Regular',1.9,True);chip(g,'直接支持：青竹暂时保管',26,219,'success',296);txt(g,'尚不能推出：所有权已经转移',26,268,645,17,'warning','Medium');txt(g,'影响范围',26,339,645,14,'dim','Medium');txt(g,'人物档案中的持有关系\n第 13 章的取回行为检查\n地图上的物品位置说明',26,377,640,16,'body');button(g,'返回原文章节',26,517,650,'secondary','S06')
g=panel(s,954,190,458,595);txt(g,'保留你的意图',24,23,410,22,'ink','Medium');
for i,(t,b) in enumerate([('只是暂时保管','保管者为青竹；所有权保持原状态。'),('明确赠予青竹','生成所有权变更预览，再由你确认。'),('暂不确定','保留未知；后续有新原文时再核对。')]):
 c=group(g,t,24,92+i*115,410,98,'accentSoft' if i==0 else 'surface',10,'accent' if i==0 else 'border');txt(c,t,18,13,371,17,'ink','Medium');txt(c,b,18,46,371,13,'body')
button(g,'采用“暂时保管”这一理解',24,517,410,'primary','S04');s['notes']=['只决定当前命题，不连带采用整批候选。','模型结论不替代作者决定；不确定可继续保留。']
# S06
s=screen('S06','第 12 章 · 没有寄出的信','写作','当前 Scene：门廊的回答   ·   参考范围：截至本场   ·   正文已保存',right=True)
g=panel(s,228,190,816,698);txt(g,'正文',28,18,72,12,'dim','Medium');txt(g,'正文 ▾    B    I    段落',110,18,330,12,'body');button(g,'发布…',574,10,108,'secondary','S36',12);button(g,'专注',696,10,92,'quiet','S08',12);line(g,28,64,788,64);txt(g,'没有寄出的信',58,94,680,30,'ink','Regular',1.6,True);prose(g,58,168,700,True);button(g,'继续写',58,600,144,'primary','S07');button(g,'检查这一章',222,600,170,'secondary','S17');txt(g,'正常写作无需先填人物卡、Scene 或大纲。',58,661,700,12,'dim')
companion(s,'这句承诺，可能影响下一场','林舟承诺会回来取钥匙。可以让青竹的反应围绕“是否信任”展开；不必新增秘密。','原文有据 · 非强制建议','看三个不同方向','S09');
# S07
s=screen('S07','围绕你选中的这一句','就地建议','选段优先于光标段落；未保存文字使用明确的临时快照，不套用旧正文偏移。',right=True)
g=panel(s,228,190,816,698);txt(g,'第 12 章 / 正文',28,23,700,13,'dim');prose(g,48,91,720,True);rect(g,44,370,727,88,'accentSoft',8);txt(g,'“先放在你这里。等北岸的信到了，我会回来取。”',58,389,693,18,'accent','Regular',1.65,True);button(g,'润色表达',48,485,145,'secondary','S10');button(g,'推演人物反应',208,485,182,'primary','S09');button(g,'看依据',405,485,120,'quiet','S19');txt(g,'只对选段提出候选；没有点击采用，不会替换任何正文。',48,585,720,14,'dim')
companion(s,'她可以不回答那个问题','让青竹收好钥匙，却追问井底的人。这个方向强化她的主动性，同时保留原承诺。','基于当前选段','预览局部改写','S10')
# S08
s=screen('S08','专注写作','写作',full=True)
rect(s,0,0,1440,960,'#F7F4EE');button(s,'← 返回工作台',34,22,176,'quiet','S06');txt(s,'白石城来信  /  第 12 章',570,31,420,13,'dim');chip(s,'已保存',1323,30,'success',82)
txt(s,'没有寄出的信',370,136,730,38,'ink','Regular',1.65,True);prose(s,370,237,702);line(s,370,814,1070,814);txt(s,'写下下一句。',370,844,500,18,'dim','Regular',1.7,True);button(s,'查看 1 个相关提醒',1104,858,280,'secondary','S07');s['notes']=['专注状态不自动弹出推荐；仅保留安静入口。']
# S09
s=screen('S09','不要急着选一个答案','探索创意','三个独立视角先各自展开。它们是可选方向，不是投票得出的“正确剧情”。',active='故事结构')
options=[('人物选择','青竹先收好钥匙，却拒绝替他守密。','她不是被动接受任务的人。下一步可让她提出一个不涉及新秘密的交换条件。','代价：需要兑现她的自主行动。','success'),('悬念推进','让北岸来信提前抵达，但信封已经拆开。','读者得到一个新问题，而不是立刻揭晓井底身份。必须交代信为什么在这里。','代价：增加一条必须维护的因果线。','ai'),('情绪留白','她只问：“你这次还会回来吗？”','把重心留在两人的承诺。没有新增设定，也不要求每个细节成为伏笔。','代价：推进较缓，依赖细腻的反应。','warning')]
for i,(tag,title,body,cost,k) in enumerate(options):
 g=card(s,228+i*404,190,376,540,title,body,tag,k);txt(g,cost,22,330,332,14,'body');txt(g,'依赖：当前选段、人物已采用资料\n尚未验证：后续情节效果',22,395,332,12,'dim');button(g,'展开这个方向',22,463,332,'primary' if i==0 else 'secondary','S10')
g=panel(s,228,759,1184,129);txt(g,'也可以不扩大情节。',24,19,650,20,'ink','Medium');txt(g,'保留原文、只借一句反应，或者再换一个角度。系统不强制合并三个方向。',24,61,850,14,'body');button(g,'保留原文',986,49,172,'quiet','S06')
# S10
s=screen('S10','看清差异，再采用','局部改写预览','只修改本次选中的 1 处段落；原版本与未采用方案继续保留。')
g=panel(s,228,190,1184,98);chip(g,'创作候选',22,32,'ai');txt(g,'本次修改：增强青竹的主动回应，不改变钥匙所有权。',162,30,970,16,'ink','Medium')
for x,label,content,bg in [(228,'当前正文','青竹接过钥匙，点了点头。\n她没有再说什么。','errorSoft'),(832,'候选改写','青竹把钥匙收进袖里，却没有点头。\n“替你保管可以，”她说，“守密是另一回事。”','successSoft')]:
 g=panel(s,x,313,580,360);txt(g,label,25,22,530,14,'dim','Medium');rect(g,24,84,532,196,bg,10);txt(g,content,44,111,492,22,'ink','Regular',1.85,True)
g=panel(s,228,699,1184,189);txt(g,'采用会发生什么',24,20,960,18,'ink','Medium');txt(g,'另存工作稿  ·  不发布  ·  不新增世界事实  ·  原审查结果需重新验证',24,60,970,14,'body');button(g,'采用这一处修改',832,119,324,'primary','S06');button(g,'暂存为备选',630,119,182,'secondary','S09')
# S11
s=screen('S11','故事结构，一眼看清','故事结构','总纲、剧情线与场景放在同一条创作路径；拖动改变规划，不冒充已发生事实。',active='故事结构')
g=panel(s,228,190,1184,115);txt(g,'本卷目标：从守住一封信，到选择是否公开真相',24,19,1120,21,'ink','Medium');txt(g,'上位约束：主角不提前得知井底身份；青竹拥有独立行动动机。',24,63,1080,14,'body')
for i,(title,titles) in enumerate([('第一幕 / 入城',['雨后的渡口','门廊的回答']),('第二幕 / 追索',['北岸来信','井边的交易']),('第三幕 / 选择',['城门关闭','未寄出的信'])]):
 g=panel(s,228+i*404,333,376,454);txt(g,title,22,21,334,18,'ink','Medium')
 for j,t in enumerate(titles):
  c=card(g,18,77+j*166,340,147,t,'叙事目标、人物选择与信息边界。',None,cta=None);chip(c,'已采用规划' if i==0 else '规划候选',18,88,'success' if i==0 else 'ai');c['target']='S12'
g=panel(s,228,815,1184,73);txt(g,'剧情线：铜钥匙   ━━━━━━━     北岸来信   ━━━━━     人物信任   ━━━━━━━━━',24,22,1100,14,'body');g['target']='S45'
# S12
s=screen('S12','把一场戏准备好','场景工作区','剧本与人物反应是写作依据，不是尚未写出的事实。采用后才供默认写作使用。',active='故事结构',right=True)
g=panel(s,228,190,816,310);txt(g,'门廊的回答',24,25,740,25,'ink','Bold');chip(g,'已采用剧本',24,75,'success');txt(g,'目标：青竹决定是否接下钥匙。\n冲突：她愿意帮忙，却不愿再次被蒙在鼓里。\n不得发生：揭晓井底人物身份。',24,128,750,17,'body');button(g,'由此继续写',573,243,216,'primary','S06')
for i,(who,body) in enumerate([('林舟','想尽快离开，又不能解释真正的原因。\n可以回避问题；不能无代价说服对方。'),('青竹','希望得到尊重，而不是被分派任务。\n接受保管不等于完全相信。')]):
 g=panel(s,228+i*420,524,396,364);portrait(g,24,24,83,115,who);txt(g,who,127,27,240,23,'ink','Medium');chip(g,'角色视角资料',127,78,'accent');txt(g,body,24,170,348,16,'body');button(g,'探索另一种反应',24,296,348,'secondary','S09')
companion(s,'先补清楚“她为何留下”','角色反应存在多种可能。可以比较直接拒绝、附带条件与暂缓回答，但不强制选取最戏剧化方案。','场景存在 1 项开放选择','比较人物反应','S09')
# S13
s=screen('S13','这本书，我们理解到了哪里','世界资料','正式设定、系统理解与开放问题分层呈现；每条理解都能返回来源。',active='世界资料')
g=panel(s,228,190,1184,96);chip(g,'已采用资料',24,32,'success');chip(g,'系统理解',159,32,'ai');chip(g,'开放问题 4',285,32,'warning');button(g,'描述一个新设定',919,26,240,'primary','S15')
for i,(tag,title,body,target) in enumerate([('人物','林舟','医生；回到白石城。隐瞒经历的原因尚未明确。','S14'),('地点','白石城','城门、北岸渡口与回声井已有可核对连接。','S20'),('物品','铜钥匙','青竹暂时保管；所有权未被新的原文改变。','S14')]):
 g=card(s,228+i*404,314,376,310,title,body,tag,'accent',cta='查看资料与来源',target=target)
g=panel(s,228,652,760,236);txt(g,'本书理解',24,19,700,20,'ink','Medium');txt(g,'信任正在成为两人共同的难题。',24,66,700,22,'ink','Regular',1.6,True);txt(g,'这是有来源的解释，不是世界事实。可保留竞争解释，也可以纠正。',24,112,700,14,'body');button(g,'看依据与其他解释',24,166,320,'secondary','S19')
g=card(s,1012,652,400,236,'一个尚未回答的问题','井边的钟声是否意味着有人已经到达？目前只有相关描写，没有充分证明。','开放问题','warning',cta='继续查证',target='S18');g['children'][-1]['target']='S18'
# S14
s=screen('S14','林舟','人物资料','同一个人物持续积累新观察；身份去重，不会删去后续出现的新信息。',active='世界资料')
g=panel(s,228,190,324,698);portrait(g,22,22,280,350);txt(g,'当前形象参考',22,394,280,12,'dim');button(g,'管理形象',22,443,280,'secondary','S26');chip(g,'原文有据',22,521,'success');txt(g,'医生；第 12 章最后确认在白石城。\n“最后确认”不等于现在仍在此处。',22,568,280,15,'body')
g=panel(s,576,190,836,698);txt(g,'档案  /  变化  /  所知  /  来源',24,20,780,16,'body');line(g,24,61,812,61)
for i,(t,b) in enumerate([('首次出现','第 1 章：林舟以医生身份进入故事。'),('来到白石城','第 8 章：原文直接支持进入城市；不是从地图坐标推测。'),('交出铜钥匙','第 12 章：交给青竹保管，承诺回来取。'),('仍然未知','他为什么回避井底之人的身份；这不是已证实的背叛。')]):row(g,t,b,24,89+i*107,786,'已核对' if i<3 else '未知','S19',ico='clock')
button(g,'这条理解不准确',24,608,250,'secondary','S05');button(g,'查看相关场景',568,608,244,'primary','S12')
# S15
s=screen('S15','先把一个规则说清楚','世界共创','从你的自然语言想法出发；条件、代价和例外按需展开，不先生成制度百科。',active='世界资料',right=True)
g=panel(s,228,190,816,698);chip(g,'世界书工作稿 · 未发布',24,24,'ai');txt(g,'井城的通行规则',24, 83,752,27,'ink','Medium');txt(g,'我的设想',24,148,730,13,'dim','Medium');rect(g,24,182,768,111,'bg',10);txt(g,'夜里城门关闭，但送信人可以凭铜钥匙进城。',42,210,728,18,'body');txt(g,'目前需要决定的只有一项',24,330,740,19,'ink','Medium');txt(g,'钥匙证明“有资格通行”，还是能直接打开城门？\n两种方案带来的守卫责任和失窃风险不同。',24,379,740,18,'body');button(g,'比较两种规则',24,507,260,'primary','S09');button(g,'先存为工作稿',304,507,230,'secondary','S13');txt(g,'可稍后展开：例外 / 执行者 / 代价 / 历史变更',24,610,744,14,'dim')
companion(s,'检查规则，不替你决定风格','以“可执行条件”“人物动机”“社会后果”三个角度检查。只有你采用的内容会成为正式设定。','规则设计助手','查看多角度建议','S09')
# S16
s=screen('S16','先处理真正重要的事','统一审阅','同一问题只出现一次；来源变化会重查，忽略与“事实为假”是不同决定。',active='待我决定')
g=panel(s,228,190,1184,92);chip(g,'现在影响写作 1',24,31,'warning');chip(g,'来源待更新 2',207,31,'error');chip(g,'可选想法 3',366,31,'ai');button(g,'按当前章节筛选',924,24,232,'secondary','S17')
for i,(t,b,st,target) in enumerate([('铜钥匙：暂时保管还是赠予？','影响第 13 章行为检查、人物资料与物品说明。','需要决定','S05'),('第 10 章地点描写已修改','旧空间检查退出当前结果；重新核对后才恢复。','依据已变','S33'),('人物候选可能同名','两条来源指向不同身份；不要按名字直接合并。','核对身份','S43'),('青竹的回答还有一个轻量方向','不新增悬念，只强化她的主动性。','可选建议','S09')]):
 g=panel(s,228,310+i*139,1184,119);icon(g,'check' if i==0 else 'clock' if i<3 else 'spark',24,26,24,'warning' if i<3 else 'ai');txt(g,t,70,20,832,19,'ink','Medium');txt(g,b,70,58,826,14,'body');button(g,'核对' if i<3 else '看看',974,38,184,'secondary',target)
# S17
s=screen('S17','这一章的检查与返修','写作检查','按原文证据和实际覆盖呈现，不把模型说“通过”当成全书没有问题。',active='待我决定',right=True)
g=panel(s,228,190,816,698);chip(g,'本章检查 · 部分覆盖',24,24,'warning');txt(g,'检查对象：第 12 章当前保存稿',24,79,750,22,'ink','Medium')
for i,(t,b,st) in enumerate([('人物动机','已核对当前 Scene 的已采用人物资料。','已核对'),('空间连续性','对白发生于门廊；未推测此前完整路线。','已核对'),('读者信息顺序','本次没有读取未来章节，不签署全书无剧透。','有限范围'),('文风与表达','有 1 处可改善的重复，不影响事实一致性。','可选修改')]):row(g,t,b,24,148+i*97,768,st,'S19',ico='check')
button(g,'只返修选中的问题',24,604,768,'primary','S10');companion(s,'保留事件，只调整回答','这次返修保持交钥匙与询问不变，只让青竹的选择更清楚。返修后重新审查，不沿用旧的通过回执。','定向返修 · 1 处','预览修订','S10')
# S18
s=screen('S18','在原文里找到答案','检索与查证','检索命中不是事实证明。结果保留章节位置、来源版本和实际覆盖。',active='世界资料')
g=panel(s,228,190,1184,94);icon(g,'search',24,31,23,'accent');txt(g,'铜钥匙什么时候交给了青竹？',66,27,780,20,'ink');button(g,'查找',986,24,170,'primary','S19')
for i,(title,body,tag) in enumerate([('第 12 章 · 没有寄出的信','“先放在你这里。”林舟说，“等北岸的信到了，我会回来取。”','直接原文'),('第 13 章 · 远来的客人','青竹碰了碰袖口，确认钥匙还在。','相关后续'),('物品资料 · 铜钥匙','当前保管者：青竹。所有权是否改变，原文尚无新证据。','已采用资料')]):
 g=panel(s,228,315+i*180,1184,156);chip(g,tag,24,20,'success' if i!=1 else 'accent');txt(g,title,177,17,930,18,'ink','Medium');txt(g,body,24,70,1020,18,'body','Regular',1.7,True);icon(g,'arrow',1114,79,22,'accent');g['target']='S19'
txt(s,'本次范围：第 1—14 章 · 排除未来未授权资料 · 查看“未检索范围”',230,893,1160,13,'dim')
# S19
s=screen('S19','这条结论，具体依据是什么','证据追踪','主张、支撑原文与解释强度逐条对应；不会把一整轮资料都当成每句话的引用。',active='世界资料')
g=panel(s,228,190,708,698);chip(g,'原文有据',24,23,'success');txt(g,'青竹暂时保管铜钥匙',24,78,658,27,'ink','Bold');txt(g,'支持',24,151,620,13,'dim','Medium');txt(g,'“先放在你这里。等北岸的信到了，\n我会回来取。”',24,193,658,23,'ink','Regular',1.9,True);txt(g,'不能据此推出',24,342,640,13,'dim','Medium');txt(g,'钥匙已赠予青竹；青竹知道钥匙全部用途；\n钥匙此后一直在青竹身上。',24,383,650,18,'warning');button(g,'返回原文定位',24,603,660,'primary','S06')
g=panel(s,960,190,452,698);txt(g,'本次依据范围',24,25,406,21,'ink','Medium');txt(g,'截止：第 12 章 / 门廊 Scene 之后\n视角：作者核对\n状态：当前保存来源\n理解类型：原文观察与工作解释',24,91,400,16,'body');line(g,24,263,426,263);txt(g,'需要不同视角？',24,296,400,18,'ink','Medium');txt(g,'历史首次阅读与事后解释分开。\n较晚形成的方法、标题和配图也可能泄漏信息。',24,345,400,15,'body');button(g,'调整范围',24,495,404,'secondary','S36');button(g,'提出纠正',24,565,404,'quiet','S05')
# S20
s=screen('S20','在地图里走进故事','故事地图',full=True,active='故事地图');atlas(s,0,0,1440,960,True)
g=group(s,'Map top toolbar',28,24,1384,68,'surface',14);button(g,'← 回到写作',16,12,166,'quiet','S06');txt(g,'白石城与北岸',216,18,470,22,'ink','Medium');chip(g,'当前已采用地图',879,20,'success',174);button(g,'编辑地图',1080,12,136,'secondary','S23');button(g,'全屏',1232,12,132,'quiet','S20')
g=panel(s,28,118,264,263,bg='surface');txt(g,'探索范围',20,20,220,17,'ink','Medium');txt(g,'地图  /  配图  /  场景',20,67,222,13,'body');chip(g,'第 12 章 · 本场之后',20,109,'accent',220);txt(g,'人物与物品只在有据时落点。\n遮挡位置：苍岫山 · 可从列表定位',20,163,220,13,'body')
g=panel(s,1052,118,360,591);landscape(g,18,18,324,178,night=True);txt(g,'白石城',22,219,312,26,'ink','Medium');chip(g,'本场地点 · 原文有据',22,267,'success',280);txt(g,'相关场景',22,320,305,12,'dim','Medium');txt(g,'门廊的回答\n人物：林舟、青竹\n物品：铜钥匙（暂时保管）',22,355,312,16,'body');button(g,'进入这一场',22,467,316,'primary','S21');button(g,'查看来源',22,524,316,'quiet','S19')
g=group(s,'Story ribbon',28,812,1384,120,'surface',15);txt(g,'沿故事回看',22,17,260,14,'ink','Medium')
for i,title in enumerate(['08  入城','09  雨后的渡口','10  北岸来信','11  城门口','12  门廊的回答']):button(g,title,22+i*224,59,208,'primary' if i==4 else 'secondary','S21')
# S21
s=screen('S21','门廊的回答','地图 / 场景舞台',full=True);landscape(s,0,0,1440,960,True)
g=group(s,'Scene toolbar',28,24,1384,66,'surface',14);button(g,'← 回到地图',16,11,172,'quiet','S20');txt(g,'第 12 章 / 门廊的回答',225,18,775,20,'ink','Medium');button(g,'返回这一段正文',1097,11,268,'primary','S06')
g=panel(s,1012,118,400,590);txt(g,'场景中的人物与物品',22,22,355,20,'ink','Medium');portrait(g,22,77,86,113,'林舟');txt(g,'林舟',128,79,246,21,'ink','Medium');chip(g,'本场出现',128,125,'success');portrait(g,22,213,86,113,'青竹','#D8D3DF');txt(g,'青竹',128,215,246,21,'ink','Medium');chip(g,'本场出现',128,261,'success');keyart(g,22,350,86,103);txt(g,'铜钥匙',128,351,246,21,'ink','Medium');txt(g,'青竹保管；所有权未变',128,395,246,13,'body');button(g,'核对在场与来源',22,500,356,'secondary','S19');txt(g,'配图为当前场景参考，不证明人物所知。',22,557,355,11,'dim')
g=panel(s,28,763,930,169);txt(g,'“你真的见过井底的那个人？”',28,22,875,27,'ink','Regular',1.7,True);txt(g,'青竹没有回避，她把选择留给了林舟。',28,85,775,15,'body');button(g,'上一场',28,114,126,'quiet','S22');button(g,'下一场',769,114,136,'quiet','S24')
# S22
s=screen('S22','林舟的旅程，哪些是确定的','地图 / 历史',full=True);atlas(s,0,0,1440,960,True,True)
g=group(s,'History toolbar',28,24,1384,68,'surface',14);button(g,'← 当前地图',16,12,180,'quiet','S20');txt(g,'人物旅程 / 林舟',234,19,670,21,'ink','Medium');chip(g,'当时已知 · 截至第 12 章',1020,21,'accent',342)
g=panel(s,28,119,378,460);txt(g,'有证据的出现节点',22,22,330,20,'ink','Medium')
for i,(t,b) in enumerate([('第 8 章 · 白石城','原文明确进入城市。'),('第 10 章 · 北岸渡口','原文出现；中间路线未知。'),('第 12 章 · 门廊','最后一次确认的位置。')]):row(g,t,b,22,81+i*102,332,None,'S19',ico='clock')
chip(g,'虚线表示未知，不是实际路线',22,400,'warning',332)
g=panel(s,915,711,497,221);txt(g,'首次阅读 ≠ 事后解释',22,21,450,21,'ink','Medium');txt(g,'后来揭露的身份、方法和配图不会回填到早期读者视图。',22, 74,451,16,'body');button(g,'切换解释方式',22,154,453,'secondary','S36')
# S23
s=screen('S23','编辑地图，不改写世界','地图结构编辑','布局、空间约束与故事事实分别处理；保存前先查看实际变化。',active='故事地图')
atlas(s,228,190,814,610,False);g=panel(s,1066,190,346,698);txt(g,'选中：白石城',22,22,301,20,'ink','Medium');chip(g,'地图工作稿 · 有修改',22,74,'warning',297);txt(g,'空间关系',22,135,301,13,'dim','Medium');txt(g,'位于北岸渡口西南侧\n与南门旧道相连\n距离与比例：未确定',22,178,296,16,'body');line(g,22,291,324,291);txt(g,'此次操作',22,322,302,17,'ink','Medium');txt(g,'只移动图元的示意位置。\n不会改变人物位置、历史旅程或正式设定。',22,370,301,15,'body');button(g,'预览地图差异',22,514,302,'primary','S25');button(g,'放弃这次布局',22,577,302,'secondary','S20');txt(g,'离开前保留本机草稿与服务端恢复入口。',22,642,299,12,'dim');g=panel(s,228,824,814,64);txt(g,'撤销   重做    ·    吸附已开启    ·    图元 42 / 200    ·    不按比例',22,19,770,13,'body')
# S24
s=screen('S24','到达之前，还缺什么条件？','地图智能 / 路线排演','排演是条件方案，不是已发生旅程。没有距离、通行规则或时间依据，就保留未知。',active='故事地图')
atlas(s,228,190,758,698,False,True);g=panel(s,1010,190,402,698);chip(g,'条件排演 · 未写入故事',22,22,'ai',356);txt(g,'白石城 → 回声井',22,78,354,24,'ink','Medium');txt(g,'已知条件',22,139,350,13,'dim','Medium');txt(g,'北岸渡口连接旧道。\n城门夜间关闭。',22,182,350,17,'body');txt(g,'尚未确定',22,282,350,13,'warning','Medium');txt(g,'渡口夜间是否通行？\n铜钥匙提供资格还是直接开门？\n距离与耗时没有依据。',22,323,354,17,'body');button(g,'比较两个可行设想',22,499,358,'primary','S09');button(g,'核对地理依据',22,563,358,'secondary','S19');txt(g,'不自动生成最短路线或到达时间。',22,635,357,12,'dim')
# S25
s=screen('S25','地图配图与校准','地图图像','原图、图元、校准与批准各有版本；调整显示尺寸不等于重新批准内容。',active='故事地图')
g=panel(s,228,190,820,698);landscape(g,22,22,776,463,False);txt(g,'白石城 · 地点图',22,514,744,24,'ink','Medium');txt(g,'源图未改变；本次调整显示区域。三个校准点保持同一坐标解释。',22,564,744,14,'body');button(g,'查看叠加预览',22,620,744,'primary','S20')
g=panel(s,1072,190,340,698);txt(g,'校准与批准',22,23,293,20,'ink','Medium');
for i,(t,b) in enumerate([('1  北岸渡口','图中位置已对应到图元。'),('2  南门旧道','校准点在同一张原图上。'),('3  白石城门','显示变体不改变原图身份。')]):row(g,t,b,22,83+i*113,296,None,None,ico='map')
chip(g,'读者可见性仍需独立批准',22,464,'warning',297);button(g,'保存视觉配置',22,531,297,'primary','S20');button(g,'生成另一张候选',22,592,297,'secondary','S46')
# S26
s=screen('S26','人物与物品的形象','形象图库','当前参考图与保留形象分开。旧图未被保留时，不声称能够回放。',active='世界资料')
for i,(who,k) in enumerate([('林舟','portrait'),('青竹','portrait'),('铜钥匙','key')]):
 g=panel(s,228+i*404,190,376,500)
 if k=='key':keyart(g,22,22,332,300)
 else:portrait(g,22,22,332,300,who,'#CAD9D0' if i==0 else '#D8D2DF')
 txt(g,who,22,346,332,22,'ink','Medium');chip(g,'当前形象参考',22,388,'accent');button(g,'查看保留形象',22,433,332,'secondary','S14')
g=panel(s,228,718,1184,170);txt(g,'上传与清理同样属于完整体验',24,20,1050,21,'ink','Medium');txt(g,'透明图保留透明通道；高清按需加载。上传失败保留原图，配额与删除按实际字节处理。',24,64,1090,15,'body');button(g,'上传形象',974,107,184,'primary','S46')
# S27
s=screen('S27','围绕这一段，继续讨论','项目助手','讨论保留任务位置、依据与决定。会话本身不是新的事实权威。')
g=panel(s,228,190,802,698);chip(g,'当前选段 · 第 12 章',22,23,'accent');txt(g,'你',22,83,754,12,'dim','Medium');txt(g,'我不想突然扩大悬念，只希望青竹更有自己的主意。',22,118,750,18,'ink');line(g,22,195,780,195);icon(g,'spark',22,224,22,'ai');txt(g,'写作伙伴',56,220,678,16,'ink','Medium');txt(g,'可以保留交钥匙的事件，把“接受保管”和“答应守密”拆开。她愿意帮忙，但不接受被动地承担全部后果。',22,269,753,18,'body');chip(g,'创作解释 · 不是事实断言',22,391,'ai');button(g,'预览这段修改',22,461,758,'primary','S10');rect(g,22,557,758,111,'bg',11);txt(g,'继续说说你的意图…',41,578,714,16,'dim');button(g,'发送',641,610,120,'primary','S09')
g=panel(s,1054,190,358,698);txt(g,'本次任务',22,24,312,20,'ink','Medium');txt(g,'意图：人物反应\n范围：当前选段\n保持：交钥匙与询问井底之人\n避免：新增长期秘密',22,91,312,16,'body');line(g,22,266,336,266);txt(g,'已经形成的决定',22,301,314,18,'ink','Medium');txt(g,'钥匙属于暂时保管。\n尚未采用新的正文候选。',22,350,312,16,'body');button(g,'查看任务历史',22,574,314,'secondary','S28')
# S28
s=screen('S28','任务完成到哪一步，一目了然','运行与恢复','执行结束、结果完整、检查通过和作者采用分别展示。只续跑未完成工作，不重置预算。',active='概览')
for i,(title,body,st,cta,target) in enumerate([('持续理解：第 1—14 章','可信批次已到第 12 章；第 13 章身份待确认。','等待决定','处理这一项','S05'),('本章独立审稿','当前稿的 4 个维度已覆盖 3 个；空间历史未完整核对。','部分完成','查看覆盖','S17'),('局部改写候选','候选已保存；未采用，不影响正文。','等待采用','预览差异','S10'),('白石城配图候选','图片任务暂停；不会自动重试可能重复计费的操作。','已暂停','核对后恢复','S46')]):
 g=panel(s,228,190+i*164,1184,140);txt(g,title,24,19,850,21,'ink','Medium');txt(g,body,24,67,860,14,'body');chip(g,st,911,21,'warning',247);button(g,cta,911, 74,247,'secondary',target)
# S29
s=screen('S29','让系统自动整理，但不替你作决定','模型与授权','用途、范围、预算和到期时间清楚可见；撤销后在途结果也不能继续发布。',active='概览')
g=panel(s,228,190,760,698);txt(g,'持续整理授权',24,24,704,22,'ink','Medium');
settings=[('阅读范围','本书已保存正文；默认不读取未来未授权章节。'),('允许自动执行','检索更新、派生理解、已授权的局部复核。'),('需要单独确认','正式设定采用、正文替换、对象合并、付费图片。'),('预算与期限','本轮最多 60 次模型请求；到期或用尽暂停。'),('模型协作','自动按任务选择单模型或最多 3 个成员；共享预算。')]
for i,(t,b) in enumerate(settings):row(g,t,b,24,87+i*102,711,None,'S47',ico='settings')
button(g,'保存此授权',24,615,712,'primary','S04')
g=panel(s,1012,190,400,698);txt(g,'当前模型连接',24,24,348,20,'ink','Medium');chip(g,'使用已验证的账户连接',24,78,'success',348);txt(g,'日常任务：轻量配置\n复杂问题：先申请升级\n没有第二个连接：不冒称异构协作',24,140,348,16,'body');button(g,'管理连接',24,290,352,'secondary','S47');line(g,24,383,376,383);txt(g,'安静工作',24,419,347,19,'ink','Medium');txt(g,'输入时不弹窗、不移动当前卡片。\n创意拓展只在你需要时展开。',24,469,350,16,'body');button(g,'暂停所有后台模型任务',24,592,352,'quiet','S35')
# S30
s=screen('S30','进入一个故事，而不是配置一套系统','私人故事 / 开场','作者作品与私人旅程隔离；旅程固定资料版本和阅读截止，不写回原作。',active='概览')
g=panel(s,228,190,748,698);landscape(g,22,22,704,256,True);txt(g,'白石城来信',24,306,698,28,'ink','Medium');txt(g,'我想成为…',24,367,690,13,'dim','Medium');rect(g,24,405,700,109,'bg',10);txt(g,'一个刚来到白石城的送信人。\n我只知道城门将在天黑后关闭。',42,429,665,18,'body');button(g,'以这个身份开始',24,610,700,'primary','S31')
g=panel(s,1000,190,412,698);txt(g,'故事从哪里开始',24,24,360,22,'ink','Medium');chip(g,'资料固定至第 8 章',24,86,'accent',364);txt(g,'你与角色不会默认知道后文身份。\n尚未消歧的关键信息会在开场前提示。',24,145,360,17,'body');line(g,24,280,388,280);txt(g,'你的私人分支',24,321,360,20,'ink','Medium');txt(g,'重新生成会新建分支，旧内容不覆盖。\n只有选中的故事继续进入后续上下文。',24,374,360,16,'body');button(g,'核对原作资料与截止点',24,567,364,'secondary','S36')
# S31
s=screen('S31','城门将关','私人故事 / 阅读',full=True);rect(s,0,0,1440,960,'#F3F0E9');landscape(s,0,0,1440,320,True);button(s,'← 私人旅程',32,23,169,'secondary','S30');chip(s,'原作截止第 8 章 · 私人分支',1003,32,'accent',404)
g=panel(s,253,237,934,660);txt(g,'城门将关',46,29,840,33,'ink','Regular',1.7,True);txt(g,'守卫抬起手，拦住了你。城墙后的最后一线光已经消失，钟楼上的影子拖过石板路。\n\n“明早再来。”他说。\n\n你摸到衣襟里的信。信封上没有收件人的名字，只有一道像井口一样的圆印。',46,114,842,22,'body','Regular',1.95,True);line(g,46,415,888,415);txt(g,'你准备怎么做？',46,447,840,16,'dim');rect(g,46,491,840,90,'bg',10);txt(g,'向守卫说明送信的缘由…',64,511,790,18,'body');button(g,'继续故事',686,591,200,'primary','S31');button(g,'查看分支',46,591,145,'quiet','S32');button(g,'重新生成',211,591,145,'quiet','S31')
# S32
s=screen('S32','保存与带走你的作品','项目与版本','导出正文、保留版本和私人旅程分别选择；不会把内部提示或密钥导出。',active='概览')
for i,(title,body,cta,target) in enumerate([('导出正文','只导出指定章节与已选择正文版本；未采用候选单独列出。','预览导出范围','S36'),('版本与恢复','回看保存历史，从旧版本继续写成新稿；不覆盖后来人工改动。','查看版本差异','S33'),('资料与地图','按已授权视图导出资料；公开分享需要另行完成安全发布链。','核对资料范围','S36')]):card(s,228+i*404,190,376,335,title,body,cta=cta,target=target)
g=panel(s,228,553,1184,335);txt(g,'项目生命周期',24,26,1110,22,'ink','Medium');txt(g,'归档只是停止日常显示；永久删除会清理原文、派生理解、索引、缓存和保留图片。',24,83,1100,17,'body');button(g,'归档本书',24,179,250,'secondary','S32');button(g,'永久删除…',24,249,250,'quiet','S48');txt(g,'危险操作只使用明确、独立的确认界面。',324,251,780,14,'dim')
# S33
s=screen('S33','两处修改相遇了，先保留双方','保存冲突 / 409','服务器版本已经改变。你的本地输入仍在，不会被刷新覆盖。')
for x,label,content,bg in [(228,'你的本地版本','林舟在门廊停下，先把钥匙交给青竹。\n这句话尚未保存到服务器。','warningSoft'),(832,'服务器较新版本','林舟回到渡口时，青竹已经离开。\n来自另一窗口的保存版本。','accentSoft')]:
 g=panel(s,x,190,580,414);chip(g,label,24,24,'warning' if x==228 else 'accent');rect(g,24,87,532,237,bg,12);txt(g,content,46,119,486,22,'ink','Regular',1.9,True);button(g,'复制这份内容',24,346,532,'secondary','S33')
g=panel(s,228,632,1184,256);txt(g,'选择如何继续',24,25,1120,22,'ink','Medium');txt(g,'另存你的版本最安全；手动合并后重新核对来源。任何选择都不静默删除另一份内容。',24,84,1120,16,'body');button(g,'另存我的版本',24,176,336,'primary','S06');button(g,'打开手动合并',380,176,336,'secondary','S10');button(g,'继续核对',736,176,420,'quiet','S33')
# S34
s=screen('S34','先写一句，世界会逐渐长出来','首次空态','不需要先建完人物、地图和大纲。系统从你已有的材料开始。',active='写作')
g=panel(s,228,190,1184,698);landscape(g,737,43,402,424,False);txt(g,'故事，可以从很小的地方开始。',40,47,650,29,'ink','Regular',1.75,True);txt(g,'写一个人，描述一个地方，\n或把现有正文带进来。',40,167,630,22,'body');rect(g,40,292,650,150,'bg',13);txt(g,'在这里写下你的第一段…',60,316,609,19,'dim','Regular',1.8,True);button(g,'开始写作',40,496,250,'primary','S06');button(g,'导入已有正文',310,496,260,'secondary','S02');txt(g,'还没有 Scene：不影响写作。\n还没有人物资料：不会假装已经了解你的角色。',40,578,1080,15,'dim')
# S35
s=screen('S35','已保存的内容仍然安全','模型任务暂停','本次处理尚未完整完成。系统不会把未检查内容显示成通过。',active='概览')
g=panel(s,228,190,1184,698);chip(g,'预算已到上限 · 未完成部分暂停',32,30,'warning',440);txt(g,'正文已保存，理解停在第 12 章。',32,99,1080,31,'ink','Medium');txt(g,'完成：来源保存、检索更新、前 12 章工作批次。\n未完成：第 13—14 章的增量理解与两条解释复核。\n不会执行：自动采用、重新生成付费图片。',32,189,1065,20,'body');line(g,32,365,1152,365);txt(g,'恢复时沿用原任务范围与已消费预算。\n更换模型或扩大范围会建立可追踪的新尝试，不伪装成原结果。',32,405,1070,18,'body');button(g,'核对预算后继续',32,585,360,'primary','S29');button(g,'先回去写作',412,585,350,'secondary','S06');button(g,'查看运行记录',782,585,369,'quiet','S28')
# S36
s=screen('S36','选择你正在看的世界','范围与视角','视角改变会重新请求服务端投影。旧作者资料、图片和标签先退出，不靠隐藏几个控件防剧透。',active='世界资料')
for i,(title,body,tag) in enumerate([('作者当前','使用当前有效来源；系统理解与正式资料依然分开。','工作视图'),('当时已知','固定读到某一章或 Scene；较晚形成的信息不会混入。','历史首次阅读'),('事后解释','允许根据后来的合法资料解释前文，明确标为回顾。','回顾性理解')]):card(s,228+i*404,190,376,330,title,body,tag,'accent')
g=panel(s,228,548,1184,340);txt(g,'当前选择：当时已知 / 第 12 章之后',24,24,1110,23,'ink','Medium');txt(g,'可提供：有据人物位置、已批准地图图元与允许的原文。\n不能提供：尚未批准的读者人物图、完整角色知识地图、公开分享。',24,97,1110,18,'body');chip(g,'不支持的视图不会回退到作者全量',24,211,'warning',590);button(g,'按这个范围打开',886,264,272,'primary','S22')
# S37–S41 mobile
s=screen('S37','移动写作','移动端',mobile=True);rect(s,0,46,390,66,'surface');icon(s,'back',18,65,22);txt(s,'第 12 章',58,64,206,19,'ink','Medium');chip(s,'已保存',293,65,'success',78);txt(s,'没有寄出的信',24,144,342,28,'ink','Regular',1.6,True);prose(s,24,216,342,True);rect(s,0,731,390,113,'surface');line(s,0,731,390,731);button(s,'继续写',20,753,223,'primary','S37');button(s,'1 个提醒',253,753,117,'secondary','S38');rect(s,145,827,100,4,'ink',2)
s=screen('S38','建议底部抽屉','移动端',mobile=True);rect(s,0,46,390,330,'bg');txt(s,'第 12 章 · 没有寄出的信',24,71,342,20,'ink','Medium');txt(s,'“先放在你这里。等北岸的信到了，\n我会回来取。”',24,129,342,20,'body','Regular',1.85,True);rect(s,0,46,390,287,'ink',opacity=.10);g=group(s,'Bottom sheet / single overlay',0,310,390,534,'surface',22);rect(g,169,11,52,4,'border',2);txt(g,'这句承诺，可以这样回应',22,44,346,24,'ink','Medium');chip(g,'与你的选段有关',22,93,'ai');txt(g,'让青竹接受保管，却不答应守密。\n不新增秘密，也不改变钥匙所有权。',22,147,346,17,'body');button(g,'看局部改写',22,260,346,'primary','S10');button(g,'展开其他方向',22,324,346,'secondary','S09');button(g,'收起，继续写',22,390,346,'quiet','S37');txt(g,'不会自动替换正文',22,465,346,12,'dim');rect(s,145,827,100,4,'ink',2)
s=screen('S39','移动地图','移动端',mobile=True);atlas(s,0,46,390,640,True);g=group(s,'Map mobile toolbar',12,58,366,58,'surface',12);icon(g,'back',15,17,22);txt(g,'白石城',54,14,218,20,'ink','Medium');icon(g,'layers',322,17,20);g['target']='S20';g=group(s,'Map bottom detail',0,579,390,265,'surface',22);rect(g,169,11,52,4,'border',2);txt(g,'门廊的回答',22,43,343,24,'ink','Medium');chip(g,'第 12 章 · 原文有据',22,93,'success');txt(g,'林舟、青竹 · 铜钥匙暂时保管',22,143,346,15,'body');button(g,'回到这一段正文',22,188,346,'primary','S37');rect(s,145,827,100,4,'ink',2)
s=screen('S40','移动审阅','移动端',mobile=True);txt(s,'需要你决定',22,65,347,26,'ink','Medium');txt(s,'同一问题只看一次，其他内容可以稍后。',22,112,347,13,'dim');g=card(s,18,161,354,424,'这把钥匙是保管还是赠予？','原文说“我会回来取”。\n系统据此保留保管关系，没有擅自改变所有权。','影响下一场','warning');button(g,'核对并选择',22,345,310,'primary','S05');g=panel(s,18,607,354,113);txt(g,'2 条过期检查已收起',20,17,309,18,'ink','Medium');txt(g,'来源重查完成后再提醒你。',20,58,310,13,'dim');button(s,'回去写作',18,750,354,'secondary','S37');rect(s,145,827,100,4,'ink',2)
s=screen('S41','移动私人故事','移动端',mobile=True);landscape(s,0,46,390,217,True);chip(s,'私人分支 · 截至原作第 8 章',18,62,'accent',354);g=group(s,'Reading card',12,219,366,557,'surface',16);txt(g,'城门将关',22,21,322,28,'ink','Regular',1.6,True);txt(g,'守卫抬起手，拦住了你。\n\n“明早再来。”他说。\n\n你摸到衣襟里的信。信封上没有名字，只有一道像井口一样的圆印。',22,88,322,19,'body','Regular',1.95,True);rect(g,20,367,326,88,'bg',10);txt(g,'我想向守卫说明…',35,389,295,17,'dim');button(g,'继续故事',20,480,326,'primary','S41');rect(s,145,827,100,4,'ink',2)
# S42 command modal
s=screen('S42','用一句话到达你想做的事','命令面板',full=True);rect(s,0,0,1440,960,'bg');txt(s,'白石城来信 / 写作',60,43,800,24,'ink','Medium');rect(s,0,0,1440,960,'ink',opacity=.13);g=panel(s,358,167,724,598);icon(g,'search',24,27,24,'accent');txt(g,'找人物、场景、原文，或说你想做什么',67,22,621,20,'ink');line(g,24,84,700,84)
for i,(t,b,target,ico) in enumerate([('继续第 12 章','回到上次保存的段落','S06','write'),('看看白石城','只读打开地图，不启动模型','S20','map'),('让青竹的回答更有主见','准备局部创意方向，不自动改正文','S09','spark'),('核对钥匙的归属','打开证据与待决定项','S05','check'),('管理自动整理预算','按项目调整持续授权','S29','settings')]):row(g,t,b,24,107+i*87,675,None,target,ico)
# S43
s=screen('S43','同名，不一定是同一个人','对象去重与融合','身份合并是领域操作。保留每次观察，只有确认身份相同后才迁移精确引用。',active='待我决定')
for x,title,body in [(228,'人物 A · 林舟','第 1 章的医生；与白石城相连。\n别名：林先生（已确认）。'),(832,'人物 B · 林舟','第 13 章的送信人自称林舟。\n可能是同名，也可能是假身份。')]:
 g=panel(s,x,190,580,365);portrait(g,24,24,128,176,'林舟');txt(g,title,176,28,379,23,'ink','Medium');txt(g,body,176,91,376,16,'body');button(g,'分别查看来源',24,290,532,'secondary','S19')
g=panel(s,228,583,1184,305);chip(g,'不能只凭名称自动合并',24,23,'warning',415);txt(g,'系统可归并相同身份，但必须保留相互矛盾的新观察。\n确认合并会迁移引用并保留审计；已有正式资料不会被低置信候选覆盖。',24,85,1110,19,'body');button(g,'保持两个身份',24,217,340,'primary','S13');button(g,'准备合并预览',388,217,340,'secondary','S10');button(g,'暂不判断',752,217,407,'quiet','S16')
# S44
s=screen('S44','理解可以进步，规则不能被绕过','本书理解 / 进阶','这是可选的解释与方法视图，不是日常作者必须维护的后台。',active='世界资料')
g=panel(s,228,190,760,698);txt(g,'最近一次理解修正',24,24,712,23,'ink','Medium');chip(g,'派生理解 · 非正式设定',24,83,'ai');txt(g,'旧解释：青竹接受了全部委托。\n新解释：她接受保管，但是否守密仍未决定。',24,150,710,21,'body');txt(g,'为什么改变',24,285,705,14,'dim','Medium');txt(g,'新增原文使原来的概括过宽。旧解释保留在历史里，当前任务不会再默认读取。',24,332,710,18,'body');button(g,'核对来源',24,568,712,'secondary','S19')
g=panel(s,1012,190,400,698);txt(g,'方法试验',24,25,350,21,'ink','Medium');txt(g,'尝试：先检查反证，再概括人物动机。\n状态：实验候选，尚未成为默认方法。',24,94,349,17,'body');chip(g,'没有收益证明，不显示成长分数',24,258,'warning',350);txt(g,'必须比较相同材料、工具和总预算。\n方法不能扩大权限或删除硬检查。',24,324,350,16,'body');button(g,'查看实际验证记录',24,566,352,'secondary','S28')
# S45
s=screen('S45','信息什么时候出现，比列出伏笔更重要','剧情线 / 信息推进','明确计划、自然出现的开放问题与读者已知分开；不把每个细节强行升级为伏笔。',active='故事结构')
g=panel(s,228,190,1184,698);txt(g,'沿章节看信息如何变化',24,24,1110,23,'ink','Medium')
chapters=['第 08 章','第 09 章','第 10 章','第 11 章','第 12 章','第 13 章'];
for i,ch in enumerate(chapters):txt(g,ch,205+i*148,95,140,13,'dim');line(g,220+i*148,140,220+i*148,527,'border',1)
for i,(label,starts,ends,color,note) in enumerate([('铜钥匙',0,4,'accent','暂时保管，不是赠予'),('北岸来信',1,5,'ai','何时抵达仍可调整'),('井底之人',2,5,'warning','开放问题，非已定揭示')]):
 yy=182+i*136;txt(g,label,24,yy-9,174,18,'ink','Medium');line(g,220+starts*148,yy,220+ends*148,yy,color,5);ellipse(g,213+starts*148,yy-7,14,14,color);chip(g,note,230+starts*148,yy+27,color,min(420,900-starts*148))
button(g,'查看当前 Scene 的信息边界',24,609,1136,'primary','S12')
# S46 image confirmation
s=screen('S46','图片生成前的确认','图片费用与范围',full=True);rect(s,0,0,1440,960,'bg');landscape(s,36,92,950,710,False);rect(s,0,0,1440,960,'ink',opacity=.15);g=panel(s,446,164,548,620);chip(g,'需要你确认的模型调用',26,26,'warning',496);txt(g,'生成 1 张白石城候选图',26,84,495,26,'ink','Medium');txt(g,'来源：已采用地图与已确认地点说明。\n生成结果先作为候选，不自动批准。\n本次不生成角色形象、不修改地理事实。',26,161,494,18,'body');txt(g,'费用与重复计费',26,310,493,17,'ink','Medium');txt(g,'显示实际供应商报价或“无法预估”；\n没有已核验报价时不编造金额。\n网络中断后先查回执，不直接再次扣费。',26,352,493,15,'body');button(g,'确认生成这 1 张',26,493,496,'primary','S28');button(g,'取消',26,550,496,'quiet','S25')
# S47
s=screen('S47','连接你的模型','账户设置','连接保存在账户下，由项目按用途引用。不会在页面、日志或导出中回显密钥。',active='概览')
g=panel(s,228,190,1184,698);txt(g,'日常创作连接',28,25,1100,23,'ink','Medium');
for i,(t,v) in enumerate([('连接名称','日常轻量模型'),('供应商与模型','从当前已支持清单选择'),('API Key','••••••••••••••••  已安全保存'),('验证状态','当前连接已验证；实际可用能力由探测与评测决定')]):
 txt(g,t,28,96+i*105,205,14,'dim','Medium');rect(g,255,84+i*105,895, 62,'bg',10);txt(g,v,275,101+i*105,850,16,'body')
button(g,'验证并保存连接',28,575,415,'primary','S29');button(g,'增加第二个连接',466,575,340,'secondary','S47');txt(g,'没有第二个真实连接时，只能称为独立回合或角色分工，不能称为异构模型。',28,646,1100,13,'dim')
# S48
s=screen('S48','危险操作单独确认','项目永久删除',full=True);rect(s,0,0,1440,960,'bg');txt(s,'白石城来信 / 项目设置',50,37,900,28,'ink','Medium');rect(s,0,0,1440,960,'ink',opacity=.15);g=panel(s,421,170,598,609);chip(g,'永久删除 · 不可撤销',28,28,'error',542);txt(g,'删除《白石城来信》？',28,91,540,28,'ink','Bold');txt(g,'将删除本项目的正文、历史版本、派生理解、\n检索索引、地图、保留形象与相关运行资料。\n归档不会执行这些删除。',28,171,540,18,'body');button(g,'先导出我的作品',28,321,542,'secondary','S32');txt(g,'输入作品名称以确认',28,399,540,13,'dim');rect(g,28,435,542, 58,'bg',10);txt(g,'白石城来信',45,449,510,17,'body');button(g,'取消，保留作品',28,528,284,'primary','S32');button(g,'永久删除',329,528,241,'danger','S32')

# Design system board inserted at start; primitive illustrations intentionally contain no external image.
ds=node('frame','DS00 · 设计系统与展开规则',0,0,1440,960,children=[],fill='surface',r=0,sid='DS00',title='设计系统与展开规则',category='设计规范',subtitle='所有界面共享语义、组件与恢复规则',mobile=False,full=True,notes=[])
txt(ds,'NOVELCRAFT / SYSTEM 04',44,34,1250,13,'accent','Medium');txt(ds,'让复杂发生在系统里，\n让创作留在作者手上。',44,88,1250,40,'ink','Bold');txt(ds,'中文排版  ·  纸色工作区  ·  深墨主动作  ·  有据、解释、候选、未知与过期分开',44,239,1310,16,'dim')
for i,k in enumerate(['bg','surface','ink','accent','ai','warning','error']):
 rect(ds,44+i*190,310,170,112,k,13,'border');txt(ds,k+'  '+P[k],44+i*190,438,170,12,'body')
for i,kind in enumerate(['primary','secondary','quiet','disabled','danger']):button(ds,['主要操作','次要操作','就地展开','暂不可用','危险操作'][i],44+i*259,509,230,kind)
for i,(label,k) in enumerate([('原文有据','success'),('系统理解','ai'),('创作选项','accent'),('尚未确定','warning'),('依据已变','error')]):chip(ds,label,44+i*259,588,k,230)
for i,(t,b) in enumerate([('第一层 · 当前要点','一个主动作、当前依据范围、关键未知。'),('第二层 · 就地展开','证据和可选方向进入同一抽屉，不叠弹窗。'),('第三层 · 任务工作区','多段差异、大规模审阅、地图编辑使用独立页面。')]):card(ds,44+i*454,659,428,229,t,b,cta=None)
SCREENS.insert(0,ds)

# Each SVG retains semantic groups and editable text nodes. Native Figma plugin uses the same graph.
def color(v):return P.get(v,v) if v else 'none'
def a(v):return html.escape(str(v),quote=True)
def svg_node(n):
 typ=n['type'];x=n.get('x',0);y=n.get('y',0);w=n.get('w',0);h=n.get('h',0)
 attrs=f'id="{a(n["id"])}" data-name="{a(n["name"])}"'
 if n.get('target'):attrs+=f' data-target="{a(n["target"])}" tabindex="0" role="button" aria-label="{a(n["name"])}"'
 op=f' opacity="{n["opacity"]}"' if n.get('opacity',1)!=1 else ''
 if typ=='frame':
  content=''
  if n.get('fill') or n.get('stroke'):content+=f'<rect width="{w}" height="{h}" rx="{n.get("r",0)}" fill="{color(n.get("fill"))}" stroke="{color(n.get("stroke"))}" stroke-width="1"/>'
  inner=''.join(svg_node(c) for c in n.get('children',[]))
  if n.get('clip'):inner=f'<defs><clipPath id="clip-{n["id"]}"><rect width="{w}" height="{h}" rx="{n.get("r",0)}"/></clipPath></defs><g clip-path="url(#clip-{n["id"]})">{inner}</g>'
  content+=inner
  return f'<g {attrs} transform="translate({x},{y})"{op}>{content}</g>'
 if typ=='rect':return f'<rect {attrs} x="{x}" y="{y}" width="{w}" height="{h}" rx="{n.get("r",0)}" fill="{color(n.get("fill"))}" stroke="{color(n.get("stroke"))}"{op}/>'
 if typ=='ellipse':return f'<ellipse {attrs} cx="{x+w/2}" cy="{y+h/2}" rx="{w/2}" ry="{h/2}" fill="{color(n.get("fill"))}" stroke="{color(n.get("stroke"))}" stroke-width="{n.get("sw",1)}"{op}/>'
 if typ=='path':
  dash=f' stroke-dasharray="{n["dash"]}"' if n.get('dash') else ''
  trans=f' transform="scale({n["scale"]})"' if n.get('scale') else ''
  return f'<path {attrs} d="{a(n["d"])}" fill="{color(n.get("fill"))}" stroke="{color(n.get("stroke"))}" stroke-width="{n.get("sw",1)}" stroke-linecap="round" stroke-linejoin="round"{dash}{trans}{op}/>'
 if typ=='text':
  font='Noto Serif SC,Noto Serif CJK SC,Songti SC,serif' if n['font']=='Noto Serif SC' else 'Noto Sans SC,Noto Sans CJK SC,PingFang SC,Microsoft YaHei,sans-serif'
  tx=x+w/2 if n.get('align')=='center' else x;anchor='middle' if n.get('align')=='center' else 'start'
  weight={'Regular':400,'Medium':500,'Bold':700,'SemiBold':600}.get(n['weight'],400)
  spans=''.join(f'<tspan x="{tx}" y="{y+n["size"]*1.1+i*n["lh"]}">{html.escape(t)}</tspan>' for i,t in enumerate(n['text'].split('\n')))
  return f'<text {attrs} font-family="{font}" font-size="{n["size"]}" font-weight="{weight}" fill="{color(n["color"])}" text-anchor="{anchor}">{spans}</text>'
 return ''

def svg(s):return f'<svg xmlns="http://www.w3.org/2000/svg" width="{s["w"]}" height="{s["h"]}" viewBox="0 0 {s["w"]} {s["h"]}" role="img" aria-label="{a(s["title"])}"><title>{a(s["title"])}</title>{svg_node(s)}</svg>'
for s in SCREENS:(ROOT/'screens'/f'{s["sid"]}.svg').write_text(svg(s),encoding='utf-8')
(ROOT/'design.json').write_text(json.dumps({'version':4,'palette':P,'screens':SCREENS},ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'screen-index.json').write_text(json.dumps([{'id':s['sid'],'title':s['title'],'category':s['category'],'width':s['w'],'height':s['h'],'notes':s['notes']} for s in SCREENS],ensure_ascii=False,indent=2),encoding='utf-8')
print('Created',len(SCREENS),'screens;',seq,'nodes')
