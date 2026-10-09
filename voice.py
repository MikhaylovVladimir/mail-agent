"""Offline dictation. Audio is held in RAM; models are never downloaded."""
from pathlib import Path
import threading

RATE = 16000
MAX_SECONDS = 120


def cached_model():
    root = Path.home() / '.cache/huggingface/hub/models--Systran--faster-whisper-tiny/snapshots'
    for path in sorted(root.glob('*')):
        if all((path / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')):
            return str(path)
    return ''


def validate_model(folder):
    path = Path(folder).expanduser()
    if not folder or not all((path / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')):
        raise ValueError('Выберите локальную папку модели faster-whisper (model.bin, config.json, tokenizer.json).')
    return str(path.resolve())


class Recorder:
    def __init__(self):
        self.data = bytearray()
        self.lock = threading.Lock()
        self.full = threading.Event()
        self.error = None
        self.stream = None

    def callback(self, data, frames, time, status):
        with self.lock:
            if status:
                self.error = str(status)
            remaining = RATE * MAX_SECONDS * 2 - len(self.data)
            self.data.extend(bytes(data)[:remaining])
            if len(self.data) >= RATE * MAX_SECONDS * 2:
                self.full.set()

    def start(self):
        import sounddevice as sd
        try:
            self.stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype='int16', callback=self.callback)
            self.stream.start()
        except Exception:
            self.cancel()
            raise

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
            finally:
                self.stream.close()
                self.stream = None

    def cancel(self):
        try:
            self.close()
        finally:
            self.data.clear()

    def stop(self):
        import numpy as np
        try:
            self.close()
            if self.error:
                raise ValueError('Ошибка записи микрофона: ' + self.error)
            return np.frombuffer(bytes(self.data), dtype=np.int16).astype(np.float32) / 32768
        finally:
            self.data.clear()


def transcribe(audio, folder):
    import numpy as np
    model_path = validate_model(folder)
    if len(audio) < RATE // 3 or not np.isfinite(audio).all() or np.sqrt(np.mean(audio ** 2)) < 0.001:
        raise ValueError('Речь не записана. Проверьте микрофон и повторите диктовку.')
    from faster_whisper import WhisperModel
    model = WhisperModel(model_path, device='cpu', compute_type='int8', cpu_threads=2, local_files_only=True)
    segments, _ = model.transcribe(audio, language='ru', beam_size=5, vad_filter=True)
    text = ' '.join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise ValueError('Не удалось распознать речь. Повторите диктовку.')
    return text
