# -*- coding: utf-8 -*-
import asyncio
import shutil
import textwrap
from pathlib import Path

from edge_tts import Communicate

from .config import FFMPEG, FFMPEG_THREADS, RENDER_CRF, RENDER_PRESET, RENDER_WIDTH as W, RENDER_HEIGHT as H, RENDER_FPS as FPS, run
from .analysis import probe, black_ratio, freeze_ratio
from .quality import cadence_metrics, sequence_quality


def _filter_catalog():
    try:return run([FFMPEG,'-hide_banner','-filters'],30,False).stdout or ''
    except Exception:return ''


FILTER_CATALOG=_filter_catalog()
def has_filter(name):return str(name) in FILTER_CATALOG
DRAWTEXT=has_filter('drawtext')
XFADE=has_filter('xfade') and has_filter('acrossfade')


def safe_text(text):return str(text or '').replace('\n',' ').replace("'",' ').replace(':',' - ')[:160]


def display_text(text,width=26,max_lines=2):
    clean=' '.join(str(text or '').replace("'",' ').replace(':',' - ').split()).strip()
    if not clean:return ''
    lines=textwrap.wrap(clean,width=max(12,int(width)),break_long_words=False,break_on_hyphens=False)[:max_lines]
    if not lines:return ''
    shown='\n'.join(lines);consumed=' '.join(lines)
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


def _accent(value):
    clean=''.join(c for c in str(value or 'FFFFFF').upper() if c in '0123456789ABCDEF')[:6]
    return clean if len(clean)==6 else 'FFFFFF'


def _grade_filters(name):
    name=str(name or 'clean')
    out=[]
    if has_filter('eq'):
        settings={
            'clean':'contrast=1.025:saturation=1.04:brightness=0.005',
            'punch':'contrast=1.085:saturation=1.14:brightness=0.012',
            'cinematic':'contrast=1.075:saturation=.92:brightness=-.006',
            'retro':'contrast=1.035:saturation=.86:brightness=.018',
            'glitch':'contrast=1.11:saturation=1.18:brightness=.006',
            'meme':'contrast=1.07:saturation=1.08:brightness=.01',
            'dreamy':'contrast=.96:saturation=.96:brightness=.022',
        }
        out.append('eq='+settings.get(name,settings['clean']))
    if name=='cinematic' and has_filter('vignette'):out.append('vignette=PI/7.5')
    elif name=='retro':
        if has_filter('colorbalance'):out.append('colorbalance=rs=.035:bs=-.025')
        if has_filter('noise'):out.append('noise=alls=2.2:allf=t+u')
    elif name=='glitch':
        if has_filter('rgbashift'):out.append('rgbashift=rh=2:bh=-2')
        elif has_filter('hue'):out.append('hue=h=2:s=1.04')
    elif name=='dreamy' and has_filter('gblur'):out.append('gblur=sigma=.32')
    elif name=='punch' and has_filter('unsharp'):out.append('unsharp=5:5:.28:5:5:0')
    return out


def _motion_crop(motion):
    motion=str(motion or 'static')
    if motion=='drift':
        return f"crop={W}:{H}:x='(iw-ow)/2+(iw-ow)*.20*sin(n/24)':y='(ih-oh)/2+(ih-oh)*.13*cos(n/31)'"
    if motion=='shake':
        return f"crop={W}:{H}:x='(iw-ow)/2+min((iw-ow)/2\,7)*sin(n*1.65)':y='(ih-oh)/2+min((ih-oh)/2\,5)*cos(n*1.37)'"
    if motion=='push':
        return f"crop={W}:{H}:x='(iw-ow)/2+(iw-ow)*.05*sin(n/34)':y='(ih-oh)/2'"
    return f'crop={W}:{H}'


def _hook_drawtext(path,style,accent):
    p=filter_path(path);c='0x'+_accent(accent);base=max(34,int(W*.060))
    common=f"textfile='{p}':line_spacing=8:x=(w-text_w)/2"
    if style=='cinema':return f"drawtext={common}:fontcolor=white:fontsize={max(30,int(base*.78))}:borderw=2:bordercolor=black@0.75:shadowx=2:shadowy=2:shadowcolor=black@0.6:y=h*.095"
    if style=='clean':return f"drawtext={common}:fontcolor=white:fontsize={max(30,int(base*.82))}:borderw=3:bordercolor=black@0.8:y=h*.09:box=1:boxcolor=black@0.28:boxborderw=12"
    if style=='retro':return f"drawtext={common}:fontcolor=black:fontsize={base}:borderw=1:bordercolor=black:y=h*.08:box=1:boxcolor={c}@0.90:boxborderw=13"
    if style=='neon':return f"drawtext={common}:fontcolor={c}:fontsize={base}:borderw=4:bordercolor=black:shadowx=3:shadowy=3:shadowcolor={c}@0.35:y=h*.075"
    if style=='meme':return f"drawtext={common}:fontcolor=white:fontsize={max(38,int(base*1.06))}:borderw=6:bordercolor=black:y=h*.06"
    if style=='soft':return f"drawtext={common}:fontcolor=white:fontsize={max(30,int(base*.80))}:borderw=2:bordercolor=black@0.55:y=h*.10:box=1:boxcolor=black@0.18:boxborderw=10"
    return f"drawtext={common}:fontcolor=white:fontsize={base}:borderw=5:bordercolor=black:x=(w-text_w)/2:y=h*.072:box=1:boxcolor=black@0.38:boxborderw=14"


def _caption_drawtext(path,style,accent):
    p=filter_path(path);c='0x'+_accent(accent);base=max(27,int(W*.043));common=f"textfile='{p}':line_spacing=7:x=(w-text_w)/2"
    if style=='highlight':return f"drawtext={common}:fontcolor=black:fontsize={base}:borderw=1:bordercolor=black:y=h*.735:box=1:boxcolor={c}@0.92:boxborderw=10"
    if style=='neon':return f"drawtext={common}:fontcolor={c}:fontsize={base}:borderw=4:bordercolor=black:shadowx=2:shadowy=2:shadowcolor={c}@0.3:y=h*.735"
    if style=='meme':return f"drawtext={common}:fontcolor=white:fontsize={max(30,int(base*1.08))}:borderw=5:bordercolor=black:y=h*.72"
    if style=='minimal':return f"drawtext={common}:fontcolor=white:fontsize={max(25,int(base*.92))}:borderw=2:bordercolor=black@0.75:y=h*.77"
    if style=='kinetic':return f"drawtext={common}:fontcolor={c}:fontsize={max(29,int(base*1.05))}:borderw=4:bordercolor=black:y=h*.735+8*sin(t*9):box=1:boxcolor=black@0.22:boxborderw=8"
    if style=='punch':return f"drawtext={common}:fontcolor=white:fontsize={max(29,int(base*1.04))}:borderw=4:bordercolor=black:y=h*.735:box=1:boxcolor={c}@0.30:boxborderw=10"
    return f"drawtext={common}:fontcolor=white:fontsize={base}:borderw=3:bordercolor=black:y=h*.75:box=1:boxcolor=black@0.32:boxborderw=10"


def video_filter(zoom,focus_x=.5,focus_y=.5,hook_file=None,caption_file=None,style=None,speed=1.0):
    style=style or {};fx=_focus(focus_x);fy=_focus(focus_y);speed=max(.85,min(1.25,float(speed or 1.0)))
    zw=max(W+2,int(round(W*max(1.005,float(zoom))/2)*2));zh=max(H+2,int(round(H*max(1.005,float(zoom))/2)*2))
    xexpr=f"max(0,min(iw-ow,iw*{fx:.4f}-ow/2))";yexpr=f"max(0,min(ih-oh,ih*{fy:.4f}-oh/2))"
    filters=[
        f'scale={W}:{H}:force_original_aspect_ratio=increase',
        f"crop={W}:{H}:x='{xexpr}':y='{yexpr}'",
        f'scale={zw}:{zh}',_motion_crop(style.get('motionEffect')),
    ]
    filters.extend(_grade_filters(style.get('colorGrade')))
    if style.get('flash') and has_filter('eq'):filters.append("eq=brightness=.075:enable='between(t,0,.055)'")
    if abs(speed-1)>0.005:filters.append(f'setpts=PTS/{speed:.5f}')
    filters.extend([f'fps={FPS}','setsar=1'])
    accent=style.get('accentColor','FFFFFF')
    if DRAWTEXT and hook_file:filters.append(_hook_drawtext(hook_file,style.get('hookVisualStyle','impact'),accent))
    if DRAWTEXT and caption_file:filters.append(_caption_drawtext(caption_file,style.get('captionStyle','subtitle'),accent))
    return ','.join(filters)


def _audio_filter(duration,speed=1.0):
    fade_out=max(0.0,float(duration)-.045);parts=['aresample=async=1:first_pts=0']
    speed=max(.85,min(1.25,float(speed or 1.0)))
    if abs(speed-1)>0.005:parts.append(f'atempo={speed:.5f}')
    parts.extend(['afade=t=in:st=0:d=0.018',f'afade=t=out:st={fade_out:.3f}:d=0.04'])
    return ','.join(parts)


def make_segment(src,out,start,duration,zoom,hook='',caption='',focus_x=.5,focus_y=.5,style=None):
    style=style or {};speed=max(.85,min(1.25,float(style.get('speed',1.0) or 1.0)));desired=max(.2,float(duration));total,has_audio,_=probe(src)
    start=max(0,float(start));input_duration=desired*speed
    if total:
        start=min(start,max(0,total-.2));available=max(.2,total-start);input_duration=min(input_duration,available)
    output_duration=input_duration/speed
    if output_duration<.2:raise RuntimeError('Segment vidéo trop court')
    hook_file=caption_file=None
    if hook:
        hook_file=out.with_suffix('.hook.txt');hook_file.write_text(display_text(hook,24,2),encoding='utf-8')
    if caption:
        caption_file=out.with_suffix('.caption.txt');caption_file.write_text(display_text(caption,30,2),encoding='utf-8')
    vf=video_filter(zoom,focus_x,focus_y,hook_file,caption_file,style,speed)
    cmd=[FFMPEG,'-y','-ss',str(start),'-t',f'{input_duration:.4f}','-i',str(src)]
    video_opts=['-c:v','libx264','-preset',RENDER_PRESET,'-crf',str(RENDER_CRF),'-threads',str(FFMPEG_THREADS),'-pix_fmt','yuv420p']
    af=_audio_filter(output_duration,speed)
    if has_audio:
        cmd += ['-vf',vf,'-map','0:v:0','-map','0:a:0']+video_opts+['-af',af,'-c:a','aac','-b:a','160k','-ar','44100','-ac','2','-shortest',str(out)]
    else:
        cmd += ['-f','lavfi','-t',f'{output_duration:.4f}','-i','anullsrc=channel_layout=stereo:sample_rate=44100','-vf',vf,'-map','0:v:0','-map','1:a:0']+video_opts+['-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-shortest',str(out)]
    run(cmd,700)


def _concat_segments(work,segments,out):
    listing=work/f'{out.stem}.concat.txt';listing.write_text('\n'.join([f"file '{x.as_posix()}'" for x in segments]),encoding='utf-8')
    run([FFMPEG,'-y','-f','concat','-safe','0','-i',str(listing),'-c:v','libx264','-preset',RENDER_PRESET,'-crf',str(RENDER_CRF),'-threads',str(FFMPEG_THREADS),'-c:a','aac','-b:a','160k','-movflags','+faststart',str(out)],1000)


def _safe_transition(name):
    allowed={'fade','dissolve','wipeleft','wiperight','slideleft','slideright','circleopen'}
    return name if name in allowed else 'fade'


def _assemble_xfade(segments,plan,out):
    if len(segments)<2 or not XFADE:raise RuntimeError('xfade unavailable')
    durations=[max(.25,float(probe(x)[0] or 0)) for x in segments]
    cmd=[FFMPEG,'-y']
    for x in segments:cmd+=['-i',str(x)]
    parts=[]
    for i in range(len(segments)):
        parts.append(f'[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[v{i}]')
        parts.append(f'[{i}:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[a{i}]')
    current=durations[0];vcur='v0';acur='a0';plan_segs=plan.get('segments') or []
    for i in range(len(segments)-1):
        spec=plan_segs[i] if i<len(plan_segs) else {};wanted=max(.025,min(.24,float(spec.get('transitionDuration',.08) or .08)))
        td=min(wanted,durations[i]/3,durations[i+1]/3,max(.025,current/3));name=_safe_transition(str(spec.get('transition') or 'fade'))
        offset=max(.001,current-td);vout=f'vx{i}';aout=f'ax{i}'
        parts.append(f'[{vcur}][v{i+1}]xfade=transition={name}:duration={td:.4f}:offset={offset:.4f}[{vout}]')
        parts.append(f'[{acur}][a{i+1}]acrossfade=d={td:.4f}:c1=tri:c2=tri[{aout}]')
        current=current+durations[i+1]-td;vcur=vout;acur=aout
    cmd+=['-filter_complex',';'.join(parts),'-map',f'[{vcur}]','-map',f'[{acur}]','-c:v','libx264','-preset',RENDER_PRESET,'-crf',str(RENDER_CRF),'-threads',str(FFMPEG_THREADS),'-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',str(out)]
    run(cmd,1200)


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
            s.get('focusX',.5),s.get('focusY',.5),s,
        );segments.append(seg)
    if not segments:raise RuntimeError('Le Director n’a produit aucun segment exploitable')
    base=work/f'{out.stem}_base.mp4'
    try:_assemble_xfade(segments,plan,base)
    except Exception as exc:
        print('Transition fallback concat:',type(exc).__name__,str(exc)[:180],flush=True);_concat_segments(work,segments,base)
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
        'sequenceQuality':round(sequence,3),'cadence':cadence,'diagnostics':diagnostics,'visualStyle':plan.get('visualStyle','auto'),
        'styleDiversity':round(float(plan.get('styleDiversity',0)),3),'transitions':max(0,len(segs)-1),'styledText':bool(DRAWTEXT),
    }
