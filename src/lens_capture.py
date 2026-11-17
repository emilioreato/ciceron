"""Capture desktop regions for the lens and dock, off the Qt thread."""
import gc
import threading
import time

from PySide6.QtGui import QImage
from windows_glass import BackdropCapture


capture_lock = threading.Lock()


class SharedLensCapture:
    def __init__(self, source):
        self.source = source
        self.request = self.latest = self.error = None
        self.closed = threading.Event()
        self.backend = None

    def submit(self, request):
        self.request = request
        self.source.wake.set()

    def close(self):
        self.closed.set()
        if self.source.lens is self:
            self.source.lens = None
        self.source.wake.set()


class DockBackdropCapture:
    """Capture the two glass surfaces with one desktop-duplication read."""
    def __init__(self):
        self.request = None
        self.latest = None
        self.backend = 'gdi'
        self.lens = None
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.factory = self.numpy = None
        self.thread = threading.Thread(target=self.run, name='Ciceron-Dock', daemon=True)
        self.thread.start()

    def submit(self, bounds):
        self.request = bounds
        self.wake.set()

    def close(self):
        self.closed.set()
        self.wake.set()

    def lens_reader(self):
        self.lens = SharedLensCapture(self)
        return self.lens

    def create_camera(self, x=0, y=0, name=None):
        from dxcam.core.device import Device
        from dxcam.core.output import Output
        from dxcam.dxcam import DXCamera
        for device, outputs in zip(self.factory.devices, self.factory.outputs):
            for output in outputs:
                rect = output.desc.DesktopCoordinates
                output_name = output.devicename.casefold()
                matches = output_name == name if name is not None else (
                    rect.left <= x < rect.right and rect.top <= y < rect.bottom)
                if matches:
                    camera = DXCamera(Output(output.output), Device(device.adapter), None,
                                      output_color='BGRA', processor_backend='numpy')
                    return camera, (rect.left, rect.top, rect.right, rect.bottom), output_name
        return None, None, None

    def capture_native(self, camera, output_rect, output_name, bounds, lens_request):
        areas = [area for area in bounds if area is not None]
        left, top, output_right, output_bottom = output_rect
        lens_area = None
        if lens_request is not None and len(lens_request[3]) == 1:
            name, region, target = lens_request[3][0]
            if name == output_name:
                lx, ly, lr, lb = region
                lens_area = (left + lx, top + ly, lr - lx, lb - ly)
                areas.append(lens_area)
        if not areas:
            return (), None
        x = min(area[0] for area in areas)
        y = min(area[1] for area in areas)
        right = max(left + width for left, _, width, _ in areas)
        bottom = max(top + height for _, top, _, height in areas)
        if x < left or y < top or right > output_right or bottom > output_bottom:
            return None, None
        source = camera.grab(region=(x-left, y-top, right-left, bottom-top),
                             copy=False, new_frame_only=False)
        if source is None:
            return (), None
        frames = []
        for area in bounds:
            if area is None:
                frames.append((None, None))
                continue
            sx, sy, width, height = area
            sx, sy = sx-x, sy-y
            pixels = source[sy:sy+height:2, sx:sx+width:2]
            rows, columns = pixels.shape[:2]
            frames.append((area, QImage(pixels.tobytes(), columns, rows, columns * 4, QImage.Format.Format_RGB32)))
        lens_frame = None
        if lens_area is not None:
            sx, sy, width, height = lens_area
            dst_x, dst_y, dst_w, dst_h = target
            size = lens_request[1]
            pixels = source[sy-y:sy-y+height, sx-x:sx-x+width]
            if (height, width) == (dst_h, dst_w):
                tile = self.numpy.zeros((size, size, 4), self.numpy.uint8)
                tile[dst_y:dst_y+dst_h, dst_x:dst_x+dst_w] = pixels
                tile[dst_y:dst_y+dst_h, dst_x:dst_x+dst_w, 3] = 255
                lens_frame = (lens_request[0], size, tile, time.perf_counter())
        return tuple(frames), lens_frame

    def run(self):
        sources = (BackdropCapture(), BackdropCapture())
        lens_gdi = BackdropCapture()
        camera = output_rect = output_name = None
        secondary = secondary_rect = secondary_name = None
        last_bounds = None
        retry = 0.0
        initialized = False
        try:
            try:
                import numpy
                self.numpy = numpy
                import comtypes
                import dxcam
                self.com = comtypes
                self.factory = getattr(dxcam, '__factory')
                self.com.CoInitialize()
                initialized = True
            except (ImportError, OSError, RuntimeError, AttributeError):
                pass
            while not self.closed.is_set():
                lens = self.lens
                lens_request = lens.request if lens is not None else None
                self.wake.wait(lens_request[2] if lens_request is not None else None)
                self.wake.clear()
                if self.closed.is_set():
                    break
                bounds = self.request or (None, None)
                dock_due = bounds is not last_bounds
                last_bounds = bounds
                lens = self.lens
                lens_request = lens.request if lens is not None else None
                frames, lens_frame = (), None
                if initialized and time.perf_counter() >= retry and (
                        dock_due or lens_request is not None) and bounds[0] is not None:
                    try:
                        x, y = bounds[0][:2]
                        if camera is None or not (output_rect[0] <= x < output_rect[2] and
                                                  output_rect[1] <= y < output_rect[3]):
                            if camera is not None:
                                camera.release()
                            if secondary is not None:
                                secondary.release()
                                secondary = secondary_name = None
                            camera, output_rect, output_name = self.create_camera(x, y)
                        if camera is not None:
                            frames, lens_frame = self.capture_native(camera, output_rect, output_name,
                                                                     bounds if dock_due else (None, None), lens_request)
                        if lens_frame is None and lens_request is not None and len(lens_request[3]) == 1:
                            name = lens_request[3][0][0]
                            if name != output_name:
                                try:
                                    if name != secondary_name:
                                        if secondary is not None:
                                            secondary.release()
                                            secondary = None
                                        secondary, secondary_rect, _ = self.create_camera(name=name)
                                        secondary_name = name
                                    if secondary is not None:
                                        _, lens_frame = self.capture_native(secondary, secondary_rect, name,
                                                                            (None, None), lens_request)
                                except (OSError, RuntimeError, ValueError, self.com.COMError):
                                    if secondary is not None:
                                        secondary.release()
                                        secondary = None
                                    secondary_name = name
                    except (ImportError, OSError, RuntimeError, ValueError, self.com.COMError):
                        if camera is not None:
                            camera.release()
                            camera = None
                        if retry == 0.0:
                            retry = time.perf_counter() + .35
                        else:
                            if secondary is not None:
                                secondary.release()
                                secondary = None
                            gc.collect()
                            self.com.CoUninitialize()
                            initialized = False
                if dock_due and frames:
                    self.latest, self.backend = frames, 'dxgi'
                elif dock_due and (frames is None or camera is None or self.latest is None or
                                   tuple(area for area, _ in self.latest) != bounds):
                    self.latest = tuple((rect, source.capture_reduced(rect)) if rect else (None, None)
                                        for rect, source in zip(bounds, sources))
                    self.backend = 'gdi'
                if lens_request is not None and not lens.closed.is_set() and lens.request is not None:
                    if lens_frame is not None:
                        lens.latest, lens.backend = lens_frame, 'dxgi'
                    elif self.numpy is not None and lens_request[4] is not None and (lens.latest is None or
                                                         time.perf_counter() - lens.latest[3] > .032):
                        origin, size, _, _, physical = lens_request
                        raw = lens_gdi.read_bgra(*physical, size, size, include_layered=True)
                        if raw is not None:
                            pixels = self.numpy.frombuffer(raw, dtype=self.numpy.uint8).reshape(size, size, 4).copy()
                            pixels[:, :, 3] = 255
                            lens.latest, lens.backend = (origin, size, pixels, time.perf_counter()), 'gdi'
        finally:
            if camera is not None:
                camera.release()
                camera = None
            if secondary is not None:
                secondary.release()
                secondary = None
            if initialized:
                # DXcam's recovery callbacks keep the camera in a reference cycle.
                gc.collect()
                self.com.CoUninitialize()
            for source in sources:
                source.close()
            lens_gdi.close()


class LensCapture:
    def __init__(self):
        self.request = None
        self.latest = None
        self.error = None
        self.backend = None
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.run, name='Ciceron-Captura', daemon=True)
        self.thread.start()

    def submit(self, request):
        self.request = request
        self.wake.set()

    def close(self):
        self.closed.set()
        self.wake.set()

    def run(self):
        with capture_lock:
            if not self.closed.is_set():
                self.capture()

    def capture(self):
        cameras = {}
        gdi = BackdropCapture()
        initialized = False
        try:
            import numpy as np
            try:
                import comtypes
                import dxcam
                comtypes.CoInitialize()
                initialized = True
                # DXcam filters adapters without outputs. Use the same ordering as create().
                outputs = {
                    output.devicename.casefold(): (device_idx, output_idx)
                    for device_idx, device in enumerate(getattr(dxcam, '__factory').outputs)
                    for output_idx, output in enumerate(device)
                }
            except (ImportError, OSError, RuntimeError, AttributeError):
                outputs = {}
            use_gdi = not outputs
            cached_tiles = {}
            last_blit = 0.0
            while not self.closed.is_set():
                request = self.request
                if request is None:
                    self.wake.wait()
                    self.wake.clear()
                    continue
                start = time.perf_counter()
                origin, size, interval, regions, physical = request
                changed = False
                for name, bounds, target in (() if use_gdi else regions):
                    try:
                        if name not in cameras:
                            device_idx, output_idx = outputs[name]
                            cameras[name] = dxcam.create(device_idx, output_idx, output_color='BGRA',
                                                         processor_backend='numpy', backend='dxgi')
                            self.backend = 'dxgi'
                        frame = cameras[name].grab(region=bounds)
                    except (OSError, RuntimeError, KeyError, ValueError, comtypes.COMError):
                        # On hybrid GPUs use a native blit. Graphics Capture
                        # would put a capture indicator around the monitor.
                        use_gdi = True
                        self.backend = 'gdi'
                        break
                    if frame is not None:
                        frame[:, :, 3] = 255
                        cached_tiles[name] = (bounds, frame)
                        changed = True
                if changed and not use_gdi:
                    pixels = np.zeros((size, size, 4), np.uint8)
                    for name, bounds, target in regions:
                        cached = cached_tiles.get(name)
                        if cached is None or cached[0] != bounds:
                            continue
                        frame = cached[1]
                        x, y, width, height = target
                        if frame.shape[:2] != (height, width):
                            # Different per-monitor DPI at a display seam.
                            rows = np.arange(height) * frame.shape[0] // height
                            cols = np.arange(width) * frame.shape[1] // width
                            frame = frame[rows[:, None], cols]
                        pixels[y:y + height, x:x + width] = frame
                    self.latest, self.backend = (origin, size, pixels, start), 'dxgi'
                elif physical is not None and start - last_blit >= 1 / 30 and (
                        self.latest is None or self.latest[0] != origin or start - self.latest[3] >= .12):
                    last_blit = start
                    raw = gdi.read_bgra(*physical, size, size, include_layered=True)
                    if raw is not None:
                        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(size, size, 4).copy()
                        pixels[:, :, 3] = 255
                        self.latest, self.backend = (origin, size, pixels, start), 'gdi'
                self.closed.wait(max(0, interval - (time.perf_counter() - start)))
        except Exception as error:
            self.error = str(error) or type(error).__name__
        finally:
            gdi.close()
            for camera in cameras.values():
                camera.release()
            if initialized:
                comtypes.CoUninitialize()
