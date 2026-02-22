# AI Camera - Camera-based print monitoring with AI vision analysis
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os, threading, time

CAPTURE_COMMANDS = {
    'fswebcam': 'fswebcam -r %s --no-banner -q %s',
    'ffmpeg': 'ffmpeg -y -f v4l2 -video_size %s -i %s -frames:v 1 %s',
    'libcamera-still': 'libcamera-still --width %d --height %d -o %s -t 1 -n',
    'wget': 'wget -q -O %s %s',
}

CHECK_TYPES = ['failure', 'first_layer', 'completion', 'general']


class CameraCapture:
    def __init__(self, config, reactor):
        self.reactor = reactor
        self.camera_device = config.get('camera_device', '/dev/video0')
        self.capture_command = config.get('capture_command', 'fswebcam')
        self.snapshot_url = config.get('snapshot_url', '')
        self.resolution = config.get('resolution', '1280x720')
        self.capture_dir = config.get('capture_dir', '/tmp/ai_camera')
        self._capture_count = 0
        if self.capture_command not in CAPTURE_COMMANDS:
            raise config.error(
                "Unknown capture command '%s'. Must be one of: %s"
                % (self.capture_command,
                   ', '.join(CAPTURE_COMMANDS.keys())))
    def capture(self):
        # Non-blocking image capture using ReactorCompletion
        completion = self.reactor.completion()
        def thread_func():
            try:
                image_path = self._do_capture()
                self.reactor.async_complete(completion,
                                            {'path': image_path})
            except Exception as e:
                self.reactor.async_complete(completion,
                                            {'error': str(e)})
        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()
        result = completion.wait(
            waketime=self.reactor.monotonic() + 30.0)
        if result is None:
            raise Exception("Camera capture timed out")
        if 'error' in result:
            raise Exception("Camera capture failed: %s" % (result['error'],))
        return result['path']
    def _do_capture(self):
        # Ensure capture directory exists
        if not os.path.isdir(self.capture_dir):
            os.makedirs(self.capture_dir)
        self._capture_count += 1
        filename = "capture_%d_%.0f.jpg" % (self._capture_count, time.time())
        filepath = os.path.join(self.capture_dir, filename)
        # Build capture command
        cmd = self._build_command(filepath)
        logging.info("ai_camera: capturing image: %s", cmd)
        ret = os.system(cmd)
        if ret != 0:
            raise Exception("Capture command failed with exit code %d" % (ret,))
        if not os.path.isfile(filepath):
            raise Exception("Capture produced no output file")
        return filepath
    def _build_command(self, filepath):
        if self.capture_command == 'fswebcam':
            return CAPTURE_COMMANDS['fswebcam'] % (self.resolution, filepath)
        elif self.capture_command == 'ffmpeg':
            return (CAPTURE_COMMANDS['ffmpeg']
                    % (self.resolution, self.camera_device, filepath))
        elif self.capture_command == 'libcamera-still':
            parts = self.resolution.split('x')
            width = int(parts[0])
            height = int(parts[1]) if len(parts) > 1 else 720
            return (CAPTURE_COMMANDS['libcamera-still']
                    % (width, height, filepath))
        elif self.capture_command == 'wget':
            return CAPTURE_COMMANDS['wget'] % (filepath, self.snapshot_url)
        raise Exception("Unknown capture command: %s"
                        % (self.capture_command,))


class PrintMonitor:
    def __init__(self, config, reactor, check_callback):
        self.reactor = reactor
        self.check_callback = check_callback
        self.check_interval = config.getfloat('check_interval', 60.0,
                                              above=0.)
        self.is_monitoring = False
        self.is_printing = False
        self.print_start_time = 0.
        self.first_layer_check_done = False
        self.enable_first_layer_check = config.getboolean(
            'enable_first_layer_check', True)
        self.first_layer_check_delay = config.getfloat(
            'first_layer_check_delay', 120.0, minval=0.)
        self.enable_completion_check = config.getboolean(
            'enable_completion_check', True)
        # Create timer (initially disabled)
        self._check_timer = reactor.register_timer(self._timer_event)
    def start(self, interval=None):
        if interval is not None:
            self.check_interval = interval
        self.is_monitoring = True
        self.first_layer_check_done = False
        if self.is_printing:
            self.reactor.update_timer(self._check_timer, self.reactor.NOW)
    def stop(self):
        self.is_monitoring = False
        self.reactor.update_timer(self._check_timer, self.reactor.NEVER)
    def handle_printing(self, print_time):
        self.is_printing = True
        self.print_start_time = self.reactor.monotonic()
        self.first_layer_check_done = False
        if self.is_monitoring:
            self.reactor.update_timer(self._check_timer, self.reactor.NOW)
    def handle_not_printing(self, print_time):
        was_printing = self.is_printing
        self.is_printing = False
        self.reactor.update_timer(self._check_timer, self.reactor.NEVER)
        # Do completion check if enabled
        if (was_printing and self.is_monitoring
                and self.enable_completion_check):
            self.reactor.register_callback(
                lambda e: self.check_callback('completion'))
    def _timer_event(self, eventtime):
        if not self.is_monitoring or not self.is_printing:
            return self.reactor.NEVER
        # Check for first layer
        elapsed = eventtime - self.print_start_time
        if (self.enable_first_layer_check
                and not self.first_layer_check_done
                and elapsed >= self.first_layer_check_delay):
            self.first_layer_check_done = True
            self.check_callback('first_layer')
            return eventtime + self.check_interval
        # Regular failure check
        self.check_callback('failure')
        return eventtime + self.check_interval


class AICamera:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        # Config
        self.failure_action = config.get('failure_action', 'pause')
        self.confidence_threshold = config.getfloat(
            'confidence_threshold', 0.7, minval=0., maxval=1.)
        if self.failure_action not in ('pause', 'alert', 'none'):
            raise config.error(
                "failure_action must be one of: pause, alert, none")
        # Camera and monitor
        self.camera = CameraCapture(config, self.reactor)
        self.monitor = PrintMonitor(config, self.reactor, self._do_check)
        # State
        self.last_check_time = 0.
        self.last_check_result = {}
        self.checks_performed = 0
        self.failures_detected = 0
        # Register events
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        self.printer.register_event_handler('idle_timeout:printing',
                                            self.monitor.handle_printing)
        self.printer.register_event_handler('idle_timeout:ready',
                                            self.monitor.handle_not_printing)
        self.printer.register_event_handler('idle_timeout:idle',
                                            self.monitor.handle_not_printing)
        # Register G-code commands
        self.gcode.register_command(
            'AI_CAMERA_CHECK', self.cmd_AI_CAMERA_CHECK,
            desc=self.cmd_AI_CAMERA_CHECK_help)
        self.gcode.register_command(
            'AI_CAMERA_WATCH', self.cmd_AI_CAMERA_WATCH,
            desc=self.cmd_AI_CAMERA_WATCH_help)
        self.gcode.register_command(
            'AI_CAMERA_STOP', self.cmd_AI_CAMERA_STOP,
            desc=self.cmd_AI_CAMERA_STOP_help)
        self.gcode.register_command(
            'AI_CAMERA_ANALYZE', self.cmd_AI_CAMERA_ANALYZE,
            desc=self.cmd_AI_CAMERA_ANALYZE_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_camera/status',
                                   self._handle_status_request)
        webhooks.register_endpoint('ai_camera/check',
                                   self._handle_check_request)
        webhooks.register_endpoint('ai_camera/watch',
                                   self._handle_watch_request)
        webhooks.register_endpoint('ai_camera/stop',
                                   self._handle_stop_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _do_check(self, check_type='failure'):
        if self.ai_backend is None:
            logging.warning("ai_camera: AI backend not available for check")
            return
        try:
            image_path = self.camera.capture()
            result = self._analyze_image(image_path, check_type)
            self._handle_result(result, check_type)
        except Exception as e:
            logging.warning("ai_camera: Check failed: %s", str(e))
    def _analyze_image(self, image_path, check_type='failure'):
        prompt_key = 'camera_%s' % (check_type,)
        prompt = self.prompt_manager.get_prompt(prompt_key)
        response = self.ai_backend.query(prompt, images=[image_path])
        result = self._parse_response(response)
        result['image_path'] = image_path
        result['check_type'] = check_type
        result['raw_response'] = response
        self.checks_performed += 1
        self.last_check_time = self.reactor.monotonic()
        self.last_check_result = result
        return result
    def _parse_response(self, response):
        result = {
            'confidence': 0.0,
            'status': 'UNCERTAIN',
            'findings': '',
            'recommendation': '',
        }
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('CONFIDENCE:'):
                try:
                    result['confidence'] = float(
                        line.split(':', 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.startswith('STATUS:'):
                result['status'] = line.split(':', 1)[1].strip()
            elif line.startswith('FINDINGS:'):
                result['findings'] = line.split(':', 1)[1].strip()
            elif line.startswith('RECOMMENDATION:'):
                result['recommendation'] = line.split(':', 1)[1].strip()
        return result
    def _handle_result(self, result, check_type):
        confidence = result.get('confidence', 0.0)
        status = result.get('status', 'UNCERTAIN')
        findings = result.get('findings', '')
        recommendation = result.get('recommendation', '')
        logging.info("ai_camera: %s check - Status: %s, Confidence: %.2f, "
                     "Findings: %s", check_type, status, confidence, findings)
        if status == 'FAILURE' and confidence >= self.confidence_threshold:
            self.failures_detected += 1
            msg = ("AI Camera detected print failure (%.0f%% confidence): %s"
                   % (confidence * 100, findings))
            self.gcode.respond_info(msg)
            if self.failure_action == 'pause':
                self._pause_print(msg)
            elif self.failure_action == 'alert':
                self._send_alert(result)
    def _pause_print(self, reason):
        try:
            pause_resume = self.printer.lookup_object('pause_resume', None)
            if pause_resume is not None:
                self.gcode.run_script_from_command('PAUSE')
                logging.info("ai_camera: Print paused due to: %s", reason)
            else:
                logging.warning("ai_camera: pause_resume not available, "
                                "cannot pause print")
        except self.printer.command_error as e:
            logging.warning("ai_camera: Failed to pause print: %s", str(e))
    def _send_alert(self, result):
        try:
            webhooks = self.printer.lookup_object('webhooks')
            webhooks.call_remote_method('ai_camera_alert',
                                        status=result.get('status', ''),
                                        confidence=result.get(
                                            'confidence', 0.0),
                                        findings=result.get('findings', ''),
                                        recommendation=result.get(
                                            'recommendation', ''))
        except self.printer.command_error as e:
            logging.warning("ai_camera: Failed to send alert: %s", str(e))
    def get_status(self, eventtime):
        return {
            'monitoring': self.monitor.is_monitoring,
            'printing': self.monitor.is_printing,
            'checks_performed': self.checks_performed,
            'failures_detected': self.failures_detected,
            'last_check_time': self.last_check_time,
            'last_check_result': self.last_check_result,
            'failure_action': self.failure_action,
            'confidence_threshold': self.confidence_threshold,
        }
    # G-code commands
    cmd_AI_CAMERA_CHECK_help = "Perform a single AI camera check"
    def cmd_AI_CAMERA_CHECK(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        check_type = gcmd.get('TYPE', 'failure')
        if check_type not in CHECK_TYPES:
            raise gcmd.error("Invalid check type '%s'. Must be one of: %s"
                             % (check_type, ', '.join(CHECK_TYPES)))
        self.gcode.respond_info("Capturing image and analyzing (%s)..."
                                % (check_type,))
        try:
            image_path = self.camera.capture()
            result = self._analyze_image(image_path, check_type)
            self.gcode.respond_info(
                "AI Camera Check Result:\n"
                "  Type: %s\n"
                "  Status: %s\n"
                "  Confidence: %.0f%%\n"
                "  Findings: %s\n"
                "  Recommendation: %s"
                % (check_type, result['status'],
                   result['confidence'] * 100,
                   result['findings'],
                   result['recommendation']))
        except Exception as e:
            raise gcmd.error("Camera check failed: %s" % (str(e),))
    cmd_AI_CAMERA_WATCH_help = "Start continuous AI camera monitoring"
    def cmd_AI_CAMERA_WATCH(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        interval = gcmd.get_float('INTERVAL', None)
        self.monitor.start(interval)
        actual_interval = self.monitor.check_interval
        self.gcode.respond_info(
            "AI camera monitoring started (interval: %.0fs)"
            % (actual_interval,))
    cmd_AI_CAMERA_STOP_help = "Stop continuous AI camera monitoring"
    def cmd_AI_CAMERA_STOP(self, gcmd):
        self.monitor.stop()
        self.gcode.respond_info("AI camera monitoring stopped")
    cmd_AI_CAMERA_ANALYZE_help = "Analyze an existing image file"
    def cmd_AI_CAMERA_ANALYZE(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        filepath = gcmd.get('FILE')
        check_type = gcmd.get('TYPE', 'general')
        if check_type not in CHECK_TYPES:
            raise gcmd.error("Invalid check type '%s'. Must be one of: %s"
                             % (check_type, ', '.join(CHECK_TYPES)))
        if not os.path.isfile(filepath):
            raise gcmd.error("File not found: %s" % (filepath,))
        self.gcode.respond_info("Analyzing image: %s" % (filepath,))
        try:
            result = self._analyze_image(filepath, check_type)
            self.gcode.respond_info(
                "AI Image Analysis:\n"
                "  Type: %s\n"
                "  Status: %s\n"
                "  Confidence: %.0f%%\n"
                "  Findings: %s\n"
                "  Recommendation: %s"
                % (check_type, result['status'],
                   result['confidence'] * 100,
                   result['findings'],
                   result['recommendation']))
        except Exception as e:
            raise gcmd.error("Image analysis failed: %s" % (str(e),))
    # Webhooks handlers
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))
    def _handle_check_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        check_type = web_request.get_str('type', 'failure')
        if check_type not in CHECK_TYPES:
            raise web_request.error("Invalid check type '%s'" % (check_type,))
        try:
            image_path = self.camera.capture()
            result = self._analyze_image(image_path, check_type)
            web_request.send(result)
        except Exception as e:
            raise web_request.error(str(e))
    def _handle_watch_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        interval = web_request.get_float('interval', None)
        self.monitor.start(interval)
        web_request.send({'monitoring': True,
                          'interval': self.monitor.check_interval})
    def _handle_stop_request(self, web_request):
        self.monitor.stop()
        web_request.send({'monitoring': False})

def load_config(config):
    return AICamera(config)
