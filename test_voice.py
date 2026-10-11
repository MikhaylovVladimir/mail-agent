import tempfile
import os
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import numpy as np
from voice import Recorder, RATE, MAX_SECONDS, validate_model, transcribe, cached_model


class VoiceTests(unittest.TestCase):
    def test_nonfinite_and_quiet_audio_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('model.bin', 'config.json', 'tokenizer.json'):
                (Path(folder)/name).touch()
            for audio in (np.full(RATE, np.nan), np.full(RATE, np.inf), np.full(RATE, .0001)):
                with self.subTest(audio=audio[0]), self.assertRaises(ValueError):
                    transcribe(audio, folder)

    def test_recorded_pcm_normalization_and_stream_release(self):
        recorder = Recorder()
        recorder.stream = unittest.mock.Mock()
        stream = recorder.stream
        recorder.callback(np.array([-32768, 0, 16384], dtype=np.int16).tobytes(),3,None,None)
        np.testing.assert_array_equal(recorder.stop(), [-1,0,.5])
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        self.assertIsNone(recorder.stream)

    def test_separate_dictation_clears_previous_letter(self):
        from app import App
        app = App.__new__(App)
        app.prompt = Mock()
        app.recipient = Mock()
        app.subject = Mock()
        app.body = Mock()
        app.clear_attachments = Mock()
        App.apply_dictation(app, 'Напиши тестовому пользователю: отчёт готов')
        app.prompt.delete.assert_called_once_with('1.0', 'end')
        app.prompt.insert.assert_called_once_with('1.0', 'Напиши тестовому пользователю: отчёт готов')
        app.recipient.set.assert_called_once_with('')
        app.subject.set.assert_called_once_with('')
        app.body.delete.assert_called_once_with('1.0', 'end')
        app.clear_attachments.assert_called_once_with()

    def test_missing_model_no_download(self):
        with self.assertRaises(ValueError):
            validate_model('')

    def test_cancel_erases_audio(self):
        recorder = Recorder()
        recorder.callback(b'\x01\x00' * 20, 20, None, None)
        recorder.cancel()
        self.assertEqual(recorder.data, b'')

    def test_bounded_recording(self):
        recorder = Recorder()
        recorder.callback(b'\x01\x00' * (RATE * MAX_SECONDS + 10), 0, None, None)
        self.assertTrue(recorder.full.is_set())
        self.assertEqual(len(recorder.stop()), RATE * MAX_SECONDS)
        self.assertEqual(recorder.data, b'')

    def test_overflow_rejected(self):
        recorder = Recorder()
        recorder.callback(b'\x01\x00', 1, None, 'overflow')
        with self.assertRaisesRegex(ValueError, 'overflow'):
            recorder.stop()
        self.assertFalse(recorder.data)

    def test_silence_and_local_recognition(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('model.bin', 'config.json', 'tokenizer.json'):
                (Path(folder) / name).touch()
            with patch('faster_whisper.WhisperModel') as model:
                with self.assertRaises(ValueError):
                    transcribe(np.zeros(RATE), folder)
                model.assert_not_called()
                model.return_value.transcribe.return_value = (iter([SimpleNamespace(text=' Отчёт готов. ')]), None)
                self.assertEqual(transcribe(np.ones(RATE, dtype=np.float32) * .1, folder), 'Отчёт готов.')
                self.assertEqual(model.call_args.kwargs, dict(device='cpu', compute_type='int8', cpu_threads=2, local_files_only=True))
                options = model.return_value.transcribe.call_args.kwargs
                self.assertEqual(options['language'], 'ru')
                self.assertEqual(options['temperature'], 0)
                self.assertFalse(options['condition_on_previous_text'])
                model.return_value.transcribe.return_value = (iter([]), None)
                with self.assertRaisesRegex(ValueError, 'распознать'):
                    transcribe(np.ones(RATE, dtype=np.float32)*.1, folder)


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(os.environ.get('MAIL_AGENT_LIVE_TESTS') == '1' and os.name == 'nt', 'Offline voice integration is opt-in on Windows')
class VoiceIntegrationTests(unittest.TestCase):
    def test_russian_synthetic_speech_with_local_model(self):
        from faster_whisper.audio import decode_audio
        model = cached_model()
        if not model:
            self.skipTest('No local voice model available')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'speech.wav'
            script = "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.SelectVoice('Microsoft Irina Desktop'); $s.SetOutputToWaveFile('" + str(path) + "'); $s.Speak('Напиши начальнику письмо. Отчёт готов.'); $s.Dispose()"
            subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script], check=True, capture_output=True, timeout=30)
            text = transcribe(decode_audio(str(path), sampling_rate=RATE), model).casefold().replace('ё','е')
            for word in ('начальнику','письмо','отчет','готов'):
                self.assertIn(word,text)
