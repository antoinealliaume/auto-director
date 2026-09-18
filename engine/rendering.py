# -*- coding: utf-8 -*-
import asyncio, re
from pathlib import Path
from edge_tts import Communicate
from .config import FFMPEG, FFMPEG_THREADS, RENDER_WIDTH as W, RENDER_HEIGHT as H, run
from .analysis import probe, black_ratio, freeze_ratio

def has_drawtext():
    try:return 'drawtext' in run([FFMPEG,'-hide_banner','-filters'],30,False).stdout
    except Exception:return False
DRAWTEXT=has_drawtext()

def safe_text(text):
    return str(text or '').replace('\n',' ').replace("'",' ').replace(':',' - ')[:120]

def video_filter(zoom,hook_file=None,caption_file=None):
    zw=max(W,int(round(W*float(zoom)/2)*2));zh=max(H,int(round(H*float(zoom)/2)*2))
    filters=[f'scale={W}:{H}:force_original_aspect_ratio=increase',f'crop={W}:{H}',f'scale={zw}:{zh}',f'crop={W}:{H}','fps=30','setsar=1']
    if DRAWTEXT and hook_file:
        filters.append(f"drawtext=textfile='{hook_file.as_posix()}':fontcolor=white:fontsize={max(32,int(W*.058))}:borderw=4:bordercolor=black:x=(w-text_w)/2:y={int(H*.075)}:box=1:boxcolor=black@0.36:boxborderw=14")
    if DRAWTEXT and caption_file:
        filters.append(f"drawtext=textfile='{caption_file.as_posix()}':fontcolor=white:fontsize={max(26,int(W*.042))}:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h*.76:box=1:boxcolor=black@0.30:boxborderw=11")
    return ','.join(filters)

def make_segment(src,out,start,duration,zoom,hook='',caption=''):
    total,has_audio,_=probe(src);start=min(max(0,float(start)),max(0,total-float(duration))) if total else max(0,float(start))
    hook_file=caption_file=None
    if hook:
        hook_file=out.with_suffix('.hook.txt');hook_file.write_text(safe_text(hook),encoding='utf-8')
    if caption:
        caption_file=out.with_suffix('.caption.txt');caption_file.write_text(safe_text(caption),encoding='utf-8')
    vf=video_filter(zoom,hook_file,caption_file);cmd=[FFMPEG,'-y','-ss',str(start),'-i',str(src)]
    base=['-t',str(duration),'-vf',vf]
    video_opts=['-c:v','libx264','-preset','veryfast','-crf','21','-threads',str(FFMPEG_THREADS),'-pix_fmt','yuv420p']
    if has_audio:
        cmd += base+['-map','0:v:0','-map','0:a:0']+video_opts+['-c:a','aac','-b:a','144k','-ar','44100','-ac','2','-shortest',str(out)]
    else:
        cmd += ['-f','lavfi','-t',str(duration),'-i','anullsrc=channel_layout=stereo:sample_rate=44100']+base+['-map','0:v:0','-map','1:a:0']+video_opts+['-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-shortest',str(out)]
    run(cmd,700)

def render_plan(work,plan,paths,out,captions=True,voiceover='auto'):
    segments=[]
    for i,s in enumerate(plan['segments']):
        seg=work/f'{out.stem}_s{i}.mp4'
        make_segment(paths[s['assetId']],seg,s['start'],s['duration'],s.get('zoom',1.03),plan['hook'] if captions and i==0 else '',s.get('caption','') if captions else '')
        segments.append(seg)
    listing=work/f'{out.stem}.txt';listing.write_text('\n'.join([f"file '{x.as_posix()}'" for x in segments]),encoding='utf-8')
    base=work/f'{out.stem}_base.mp4'
    run([FFMPEG,'-y','-f','concat','-safe','0','-i',str(listing),'-c:v','libx264','-preset','veryfast','-crf','21','-threads',str(FFMPEG_THREADS),'-c:a','aac','-b:a','144k','-movflags','+faststart',str(base)],1000)
    if voiceover!='off':
        voice=work/f'{out.stem}_voice.mp3'
        try:
            asyncio.run(Communicate(safe_text(plan['hook']),voice='fr-FR-DeniseNeural',rate='+10%').save(str(voice)))
            if voice.exists() and voice.stat().st_size:
                run([FFMPEG,'-y','-i',str(base),'-i',str(voice),'-filter_complex','[0:a]volume=.30[a0];[1:a]volume=1.08[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=1.5[a]','-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','144k','-movflags','+faststart',str(out)],700);return
        except Exception:pass
    out.write_bytes(base.read_bytes())

def critic(path,target,plan):
    duration,has_audio,res=probe(path);black=black_ratio(path,0,min(max(duration,1),22));freeze=freeze_ratio(path,duration)
    segs=plan.get('segments',[]);qualities=[float(x.get('momentScore',35)) for x in segs]
    avg=sum(qualities)/max(len(qualities),1);first=sum(qualities[:2])/max(min(2,len(qualities)),1);payoff=max(qualities[-2:] or [35])
    duration_fit=max(0,1-abs(duration-target)/max(target,1));diversity=len({x['assetId'] for x in segs})/max(1,min(4,len(segs)))
    visual=max(0,1-black*2.5-freeze*1.8);audio=1 if has_audio else .55
    score=100*(.20*first/100+.18*avg/100+.13*payoff/100+.12*duration_fit+.10*diversity+.17*visual+.10*audio)
    predicted=float(plan.get('predictedRetention',score));score=.72*score+.28*predicted
    diagnostics=[]
    if first<55:diagnostics.append('hook_visual_weak')
    if payoff<60:diagnostics.append('payoff_weak')
    if black>.06:diagnostics.append('black_frames')
    if freeze>.12:diagnostics.append('low_motion_output')
    if diversity<.5:diagnostics.append('low_source_diversity')
    if duration_fit<.8:diagnostics.append('duration_mismatch')
    return round(max(0,min(100,score)),1),{'duration':round(duration,2),'blackRatio':round(black,3),'freezeRatio':round(freeze,3),'resolution':res,'first3s':round(first,1),'momentQuality':round(avg,1),'payoff':round(payoff,1),'diversity':round(diversity,3),'diagnostics':diagnostics}
