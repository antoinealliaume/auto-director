import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from self_hosted_worker import transcription


class _FakeWhisperModel:
    def __init__(self):
        self.path=None
        self.kwargs=None

    def transcribe(self,path,**kwargs):
        self.path=path
        self.kwargs=kwargs
        word=SimpleNamespace(start=.2,end=.6,word=' hello',probability=.98)
        segment=SimpleNamespace(start=.1,end=.8,text='hello',words=[word])
        info=SimpleNamespace(language='en',language_probability=.99)
        return [segment],info


class WorkerTranscriptionTests(unittest.TestCase):
    def test_transcription_bounds_input_before_whisper(self):
        model=_FakeWhisperModel()
        calls=[]

        def fake_run(cmd,**kwargs):
            calls.append((cmd,kwargs))
            return SimpleNamespace(returncode=0,stdout='',stderr='')

        previous_model=transcription._model
        previous_failed=transcription._failed
        transcription._model=model
        transcription._failed=False
        try:
            with patch.object(transcription,'get_ffmpeg_exe',return_value='ffmpeg-test'), patch.object(transcription.subprocess,'run',side_effect=fake_run):
                result=transcription.transcribe_clip(Path('long-source.mp4'))
        finally:
            transcription._model=previous_model
            transcription._failed=previous_failed

        self.assertTrue(result['enabled'])
        self.assertEqual(len(calls),1)
        cmd,kwargs=calls[0]
        self.assertEqual(cmd[0],'ffmpeg-test')
        self.assertEqual(cmd[cmd.index('-t')+1],str(transcription.MAX_SECONDS))
        self.assertEqual(cmd[cmd.index('-ar')+1],'16000')
        self.assertEqual(cmd[cmd.index('-ac')+1],'1')
        self.assertEqual(kwargs['timeout'],transcription.MAX_SECONDS+60)
        self.assertNotEqual(model.path,'long-source.mp4')
        self.assertTrue(model.kwargs['vad_filter'])
        self.assertTrue(model.kwargs['word_timestamps'])
        self.assertFalse(Path(model.path).exists())


if __name__=='__main__':unittest.main()
