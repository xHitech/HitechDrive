#!/usr/bin/env python3
"""Generate illustrative promotional media from fictional data. Requires Pillow (dev only)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'docs/assets'
# Generic system font; no personal paths or system information enter the images.
FONT='/usr/share/fonts/TTF/DejaVuSans.ttf'
BOLD='/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'

def font(size,bold=False):
    try:return ImageFont.truetype(BOLD if bold else FONT,size)
    except OSError:return ImageFont.load_default(size=size)

def draw_preview(dark=False,step=0):
    bg,panel,soft,border,ink,muted=('#14101F','#20192D','#2A203C','#3B2E50','#F4EEFF','#B8A9CE') if dark else ('#FBFAFF','#FFFFFF','#F1EBFC','#E9E7EF','#251A38','#81748F')
    accent='#A78BFA' if dark else '#6D28D9'
    im=Image.new('RGB',(1440,1000),bg);d=ImageDraw.Draw(im)
    def text(x,y,s,size=18,color=ink,bold=False):d.text((x,y),s,font=font(size,bold),fill=color)
    def rect(box,fill=panel,radius=16,outline=border):d.rounded_rectangle(box,radius,fill=fill,outline=outline,width=1)
    def bar(x,y,w,p):
        d.rounded_rectangle((x,y,x+w,y+8),4,fill=soft)
        d.rounded_rectangle((x,y,x+w*min(1,p),y+8),4,fill=accent)
    d.rectangle((0,0,240,1000),fill=panel);d.line((240,0,240,1000),fill=border)
    for i,h in enumerate([16,25,34]):d.rounded_rectangle((27+i*10,52-h,33+i*10,56),3,fill=accent)
    text(70,25,'hitechdrive',23,bold=True);text(28,82,'YOUR LIBRARY. AT HOME.',10,muted,True)
    text(28,155,'WORKSPACE',11,muted,True)
    for i,label in enumerate(['Overview','Performance','Issues','Activity','Maintenance','Settings']):
        y=188+i*53
        if i==0:rect((17,y-7,224,y+34),soft,9,soft)
        text(34,y,label,16,accent if i==0 else muted,i==0)
    text(28,842,'LOCAL STORAGE',11,muted,True);text(28,872,'/mnt/media',16)
    text(28,937,'A HITECH STUDIO PROJECT',10,accent,True)
    d.line((240,76,1440,76),fill=border)
    text(278,28,'Workspace / Overview',14,muted)
    rect((1195,21,1398,56),soft,18,soft);text(1212,29,'Sample account connected',12,accent)
    text(282,113,'YOUR FILES. UNDER YOUR CONTROL.',11,accent,True)
    text(280,143,'Everything in its place.',38,bold=True)
    text(282,199,'A real local copy of your Google Drive, on Linux.',17,muted)
    for i,(label,val,note) in enumerate([('Library size','240 GiB','Known-size files'),('Saved locally','168 GiB','Includes partial downloads'),('Left to download','72 GiB','Pending data'),('Estimated time','30 min','Varies with transfer speed')]):
        x=280+i*282;rect((x,255,x+264,382));text(x+20,278,label,14,muted);text(x+20,308,val,29,bold=True);text(x+20,353,note,10,muted)
    rect((280,406,1390,605));text(302,427,'SYNCING',11,accent,True);text(302,453,'Copying to your local library',23,bold=True)
    rect((1230,435,1365,478),soft,10,soft);text(1252,446,'Pause sync',14,accent,True)
    text(302,507,'Entire library',14,bold=True);text(1115,507,'168 / 240 GiB · 70%',13,muted)
    bar(302,541,1065,.7);text(302,568,'2,400 files in your library',12,muted);text(1050,568,'Read-only cloud access',12,muted)
    rect((280,627,1045,939));text(302,648,'TRANSFERS',11,accent,True);text(302,673,'On the way to your disk',23,bold=True);text(862,681,'3 active',13,accent)
    text(302,715,'42 MiB/s total · sample data',12,muted)
    for i,(name,size,base) in enumerate([('Animation / Short film.mp4','2 GiB',.64),('Music / Instrumental.flac','160 MiB',.38),('Books / Illustrated book.cbz','800 MiB',.22)]):
        y=751+i*57;p=min(.96,base+step*.022)
        text(302,y,name,13,bold=True);text(901,y,f'{p*100:.0f}%',12,muted);bar(302,y+25,663,p)
    rect((1065,627,1390,939));text(1088,648,'AT YOUR PACE',11,accent,True);text(1088,678,'Quick settings',23,bold=True)
    text(1088,727,'Parallel downloads',13,muted);rect((1088,751,1367,791),soft,8);text(1102,761,'3 files at a time',14)
    text(1088,816,'Maximum speed · MiB/s',13,muted);rect((1088,841,1367,881),soft,8);text(1102,851,'0 · Unlimited',14)
    text(283,970,'ILLUSTRATIVE PREVIEW · Fictional names and metrics · UI is currently in Portuguese',12,muted)
    return im

def social():
    im=Image.new('RGB',(1280,640),'#FBFAFF');d=ImageDraw.Draw(im)
    d.rounded_rectangle((870,-100,1400,720),180,fill='#F1EBFC')
    d.rounded_rectangle((960,100,1350,520),90,outline='#CDBAFA',width=3)
    for i,h in enumerate([60,100,140]):d.rounded_rectangle((1000+i*42,390-h,1026+i*42,400),12,fill='#6D28D9')
    d.text((75,65),'A HITECH STUDIO PROJECT',font=font(17,True),fill='#6D28D9')
    d.text((70,140),'HitechDrive',font=font(88,True),fill='#251A38')
    d.text((75,270),'Your Google Drive.',font=font(43,True),fill='#251A38')
    d.text((75,328),'A real copy on Linux.',font=font(43,True),fill='#251A38')
    d.text((77,439),'Visual dashboard. Resumable downloads.',font=font(23),fill='#81748F')
    d.text((77,479),'Your storage. Your pace.',font=font(23),fill='#81748F')
    d.text((77,570),'github.com/xHitech/HitechDrive',font=font(20,True),fill='#5B21B6')
    return im

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for dark,name in [(False,'preview-light.png'),(True,'preview-dark.png')]:
        draw_preview(dark).save(OUT/name,optimize=True)
    frames=[draw_preview(step=i).resize((960,667),Image.Resampling.LANCZOS) for i in range(9)]
    frames += [draw_preview(dark=True,step=i).resize((960,667),Image.Resampling.LANCZOS) for i in range(9)]
    frames[0].save(OUT/'preview.gif',save_all=True,append_images=frames[1:],duration=350,loop=0,optimize=True)
    social().save(OUT/'social-preview.png',optimize=True)
    print('Generated illustrative previews and social card with fictional data.')

if __name__=='__main__': main()
