import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import numpy as np
from voice import Recorder, RATE, MAX_SECONDS, validate_model, transcribe


class VoiceTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
