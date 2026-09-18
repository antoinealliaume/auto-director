# -*- coding: utf-8 -*-
import asyncio
import shutil
import textwrap
from pathlib import Path

from edge_tts import Communicate

from .config import FFMPEG, FFMPEG_THREADS, RENDER_CRF, RENDER_PRESET, RENDER_WIDTH as W, RENDER_HEIGHT as H, RENDER_FPS as FPS, run
from .analysis import probe, black_ratio, freeze_ratio
from .quality import cadence_metrics, sequence_quality


def has_drawtext():
    try:return 'drawtext' in run([FFMPEG,'-hide_banner','-filters'],30,False).stdout
    except Exception:return False


DRAWTEXT=has_drawtext()


def safe_text(text):return str(text or '').replace('\n',' ').replace("'",' ').replace(':',' - ')[:160]


def display_text(text,width=26,max_lines=2):
    clean=' '.join(str(text or '').replace("'",' ').replace(':',' - ').split()).strip()
    if not clean:return ''
    lines=textwrap.wrap(clean,width=max(12,int(width)),break_long_words=False,break_on_hyphens=False)[:max_lines]
    if not lines:return ''
    shown='\n'.join(lines)
    consumed=' '.join(lines)
    if len(consumed)<len(clean)-2:
        last=lines[-1]
        if len(last)>3:lines[-1]=last.rstrip(' .,!?:;')+'…'
        shown='\n'.join(lines)
    return shown[:180]


def filter_path(path:Path):
    return path.as_posix().replace('\\','/').replace(':','\\:').replace("'","\\'").replace(',','\\,')


def _focus(value,default=.5):
    try:return max(.08,min(.92,float(value)))
    except Exception:return default


def video_filter(zoom,focus_x=.5,focus_y=.5,hook_file=None,caption_file=None):
    fx=_focus(focus_x);fy=_focus(focus_y);zw=max(W,int(round(W*float(zoom)/2)*2));zh=max(H,int(round(H*float(zoom)/2)*2))
    xexpr=f"max(0,min(iw-ow,iw*{fx:.4f}-ow/2))";yexpr=f"max(0,min(ih-oh,ih*{fy:.4f}-oh/2))"
    filters=[
        f'scale={W}:{H}:force_original_aspect_ratio=increase',
        f"crop={W}:{H}:x='{xexpr}':y='{yexpr}'",
        f'scale={zw}:{zh}',f'crop={W}:{H}',f'fps={FPS}','setsar=1',
    ]
    if DRAWTEXT and hook_file:
        filters.append(f"drawtext=textfile='{filter_path(hook_file)}':fontcolor=white:fontsize={max(32,int(W*.058))}:line_spacing=8:borderw=4:bordercolor=black:x=(w-text_w)/2:y={int(H*.075)}:box=1:boxcolor=black@0.42:boxborderw=14")
    if DRAWTEXT and caption_file:
        filters.append(f"drawtext=textfile='{filter_path(caption_file)}':fontcolor=white:fontsize={max(26,int(W*.042))}:line_spacing=7:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h*.74:box=1:boxcolor=black@0.34:boxborderw=11")
    return ','.join(filters)


def _audio_filter(duration):
    fade_out=max(0.0,float(duration)-.045)
    return f'aresample=async=1:first_pts=0,afade=t=in:st=0:d=0.018,afade=t=out:st={fade_out:.3f}:d=0.04'


def make_segment(src,out,start,duration,zoom,hook='',caption='',focus_x=.5,focus_y=.5):
    total,has_audio,_=probe(src)
    if total:
        available=max(.2,total-max(0,float(start)));duration=min(float(duration),available);start=min(max(0,float(start)),max(0,total-duration))
    else:start=max(0,float(start))
    if duration<.2:raise RuntimeError('Segment vidéo trop court')
    hook_file=caption_file=None
    if hook:
        hook_file=out.with_suffix('.hook.txt');hook_file.write_text(display_text(hook,24,2),encoding='utf-8')
    if caption:
        caption_file=out.with_suffix('.caption.txt');caption_file.write_text(display_text(caption,30,2),encoding='utf-8')
    vf=video_filter(zoom,focus_x,focus_y,hook_file,caption_file);cmd=[FFMPEG,'-y','-ss',str(start),'-i',str(src)]
    base=['-t',str(duration),'-vf',vf];video_opts=['-c:v','libx264','-preset',RENDER_PRESET,'-crf',str(RENDER_CRF),'-threads',str(FFMPEG_THREADS),'-pix_fmt','yuv420p']
    af=_audio_filter(duration)
    if has_audio:
        cmd += base+['-map','0:v:0','-map','0:a:0']+video_opts+['-af',af,'-c:a','aac','-b:a','160k','-ar','44100','-ac','2','-shortest',str(out)]
    else:
        cmd += ['-f','lavfi','-t',str(duration),'-i','anullsrc=channel_layout=stereo:sample_rate=44100']+base+['-map','0:v:0','-map','1:a:0']+video_opts+['-af',af,'-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-shortest',str(out)]
    run(cmd,700)


def should_voice(plan,mode):
    if mode=='on':return True
    if mode=='off':return False
    segs=plan.get('segments',[]);audio=[float(s.get('audioScore',0) or 0) for s in segs[:4]];avg=sum(audio)/max(1,len(audio))
    return avg<.28


def _normalize_audio(src,out):
    try:
        run([FFMPEG,'-y','-i',str(src),'-map','0:v:0','-map','0:a:0?','-c:v','copy','-af','loudnorm=I=-14:TP=-1.5:LRA=11','-c:a','aac','-b:a','160k','-movflags','+faststart',str(out)],700)
    except Exception as exc:
        print('Audio normalize fallback:',type(exc).__name__,str(exc)[:120],flush=True);shutil.copyfile(src,out)


def render_plan(work,plan,paths,out,captions=True,voiceover='auto'):
    segments=[]
    for i,s in enumerate(plan['segments']):
        seg=work/f'{out.stem}_s{i}.mp4'
        make_segment(
            paths[s['assetId']],seg,s['start'],s['duration'],s.get('zoom',1.03),
            plan['hook'] if captions and i==0 else '',s.get('caption','') if captions else '',
            s.get('focusX',.5),s.get('focusY',.5),
        );segments.append(seg)
    if not segments:raise RuntimeError('Le Director n’a produit aucun segment exploitable')
    listing=work/f'{out.stem}.txt';listing.write_text('\n'.join([f"file '{x.as_posix()}'" for x in segments]),encoding='utf-8')
    base=work/f'{out.stem}_base.mp4'
    run([FFMPEG,'-y','-f','concat','-safe','0','-i',str(listing),'-c:v','libx264','-preset',RENDER_PRESET,'-crf',str(RENDER_CRF),'-threads',str(FFMPEG_THREADS),'-c:a','aac','-b:a','160k','-movflags','+faststart',str(base)],1000)
    normalized_source=base
    if should_voice(plan,voiceover):
        voice=work/f'{out.stem}_voice.mp3';mixed=work/f'{out.stem}_mixed.mp4'
        try:
            asyncio.run(Communicate(safe_text(plan['hook']),voice='fr-FR-DeniseNeural',rate='+10%').save(str(voice)))
            if voice.exists() and voice.stat().st_size:
                run([FFMPEG,'-y','-i',str(base),'-i',str(voice),'-filter_complex','[0:a]volume=.34[a0];[1:a]volume=1.02[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=1.2[a]','-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','160k','-movflags','+faststart',str(mixed)],700);normalized_source=mixed
        except Exception as exc:print('TTS fallback:',type(exc).__name__,str(exc)[:120],flush=True)
    _normalize_audio(normalized_source,out)


def critic(path,target,plan):
    duration,has_audio,res=probe(path);black=black_ratio(path,0,min(max(duration,1),22));freeze=freeze_ratio(path,duration)
    segs=plan.get('segments',[]);qualities=[float(x.get('momentScore',35)) for x in segs]
    avg=sum(qualities)/max(len(qualities),1);first=sum(qualities[:2])/max(min(2,len(qualities)),1);payoff=max(qualities[-2:] or [35])
    duration_fit=max(0,1-abs(duration-target)/max(target,1));diversity=min(1.0,len({x['assetId'] for x in segs})/max(1,min(4,len(segs))))
    visual=max(0,1-black*2.5-freeze*1.8);audio=1 if has_audio else .55;sequence=sequence_quality(segs);cadence=cadence_metrics(segs)
    score=100*(.18*first/100+.16*avg/100+.12*payoff/100+.10*duration_fit+.08*diversity+.16*visual+.08*audio+.12*sequence)
    predicted=max(0,min(100,float(plan.get('predictedRetention',score))));score=.70*score+.30*predicted
    diagnostics=[]
    if first<55:diagnostics.append('hook_visual_weak')
    if payoff<60:diagnostics.append('payoff_weak')
    if black>.06:diagnostics.append('black_frames')
    if freeze>.12:diagnostics.append('low_motion_output')
    if diversity<.5:diagnostics.append('low_source_diversity')
    if duration_fit<.8:diagnostics.append('duration_mismatch')
    if sequence<.55:diagnostics.append('sequence_feels_automatic')
    if cadence['tooLong']>1:diagnostics.append('cuts_too_slow')
    return round(max(0,min(100,score)),1),{
        'duration':round(duration,2),'blackRatio':round(black,3),'freezeRatio':round(freeze,3),'resolution':res,'fps':FPS,
        'first3s':round(first,1),'momentQuality':round(avg,1),'payoff':round(payoff,1),'diversity':round(diversity,3),
        'sequenceQuality':round(sequence,3),'cadence':cadence,'diagnostics':diagnostics,
    }
