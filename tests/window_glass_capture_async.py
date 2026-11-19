"""Check that desktop pixels for Liquid Glass are read off the Qt thread."""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lens_capture import WindowBackdropCapture


caller_thread = threading.get_ident()
capture_started = threading.Event()
release_capture = threading.Event()
capture_threads = []
captured_bounds = (10, 20, 4, 3)


class SlowCapture:
    def capture_region(self, bounds):
        capture_threads.append(threading.get_ident())
        capture_started.set()
        assert release_capture.wait(2), 'La solicitud de captura no se liberó.'
        return QImage(bounds[2], bounds[3], QImage.Format.Format_ARGB32)

    def close(self):
        pass


with patch('lens_capture.client_bounds', return_value=captured_bounds), \
        patch('lens_capture.BackdropCapture', SlowCapture):
    worker = WindowBackdropCapture()
    worker.submit(123)
    assert capture_started.wait(1), 'El worker no empezó a capturar.'
    assert worker.latest is None
    assert capture_threads == [worker.thread.ident] and capture_threads[0] != caller_thread
    release_capture.set()
    deadline = time.monotonic() + 1
    while worker.latest is None and time.monotonic() < deadline:
        time.sleep(.005)
    assert worker.latest is not None
    hwnd, bounds, frame = worker.latest
    assert hwnd == 123 and bounds == captured_bounds and not frame.isNull()
    worker.close()
    worker.thread.join(1)
    assert not worker.thread.is_alive()

print('Liquid Glass: captura de ventana fuera del hilo de interfaz verificada.')
