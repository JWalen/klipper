# AI Timelapse - Post-print timelapse frame analysis
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os

try:
    import glob as glob_module
except ImportError:
    glob_module = None


class AITimelapse:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.frames_dir = config.get('frames_dir', '/tmp/timelapse')
        self.max_frames = config.getint('max_frames_to_analyze', 20,
                                         minval=1, maxval=50)
        self.last_analysis = {}
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_TIMELAPSE_ANALYZE', self.cmd_AI_TIMELAPSE_ANALYZE,
            desc=self.cmd_AI_TIMELAPSE_ANALYZE_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_timelapse/analyze',
                                   self._handle_analyze_request)
        webhooks.register_endpoint('ai_timelapse/status',
                                   self._handle_status_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _collect_frames(self, path, max_frames):
        files = []
        for ext in ('*.jpg', '*.jpeg', '*.png'):
            if glob_module is not None:
                files.extend(glob_module.glob(os.path.join(path, ext)))
            else:
                # Fallback without glob
                for f in os.listdir(path):
                    if f.lower().endswith(ext[1:]):
                        files.append(os.path.join(path, f))
        files.sort()
        if not files:
            return []
        if len(files) > max_frames:
            step = len(files) / float(max_frames)
            files = [files[int(i * step)] for i in range(max_frames)]
        return files
    def _analyze_frames(self, gcmd, frames):
        total = len(frames)
        frame_findings = []
        for i, frame_path in enumerate(frames):
            prompt = self.prompt_manager.get_prompt(
                'timelapse_frame', str(i + 1), str(total))
            self.gcode.respond_info(
                "Analyzing frame %d/%d..." % (i + 1, total))
            try:
                response = self.ai_backend.query(prompt,
                                                  images=[frame_path])
                result = self._parse_response(response)
                frame_findings.append(
                    "Frame %d: [%s] %s"
                    % (i + 1, result['status'], result['findings']))
            except self.printer.command_error as e:
                frame_findings.append(
                    "Frame %d: [ERROR] %s" % (i + 1, str(e)))
        # Summary analysis
        findings_text = '\n'.join(frame_findings)
        summary_prompt = self.prompt_manager.get_prompt(
            'timelapse_summary', str(total), findings_text)
        self.gcode.respond_info("Generating timelapse summary...")
        try:
            summary_response = self.ai_backend.query(summary_prompt)
            summary = self._parse_response(summary_response)
        except self.printer.command_error as e:
            summary = {
                'confidence': 0.0,
                'status': 'ERROR',
                'findings': 'Summary failed: %s' % str(e),
                'recommendation': '',
            }
        return summary, frame_findings
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
    def get_status(self, eventtime):
        return {
            'available': self.ai_backend is not None,
            'last_analysis': self.last_analysis,
        }
    # G-code commands
    cmd_AI_TIMELAPSE_ANALYZE_help = "AI analyzes timelapse frames"
    def cmd_AI_TIMELAPSE_ANALYZE(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        path = gcmd.get('PATH', self.frames_dir)
        max_frames = gcmd.get_int('MAX_FRAMES', self.max_frames)
        if not os.path.isdir(path):
            raise gcmd.error("Directory not found: %s" % path)
        frames = self._collect_frames(path, max_frames)
        if not frames:
            raise gcmd.error("No image files found in %s" % path)
        self.gcode.respond_info(
            "Analyzing %d timelapse frames from %s..." % (len(frames), path))
        summary, frame_findings = self._analyze_frames(gcmd, frames)
        self.last_analysis = summary
        self.gcode.respond_info(
            "AI Timelapse Analysis (%d frames):\n"
            "  Confidence: %.0f%%\n"
            "  Status: %s\n"
            "  Findings: %s\n"
            "  Recommendation: %s"
            % (len(frames), summary['confidence'] * 100,
               summary['status'], summary['findings'],
               summary['recommendation']))
    # Webhook handlers
    def _handle_analyze_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        path = web_request.get_str('path', self.frames_dir)
        max_frames = web_request.get_int('max_frames', self.max_frames)
        if not os.path.isdir(path):
            raise web_request.error("Directory not found: %s" % path)
        frames = self._collect_frames(path, max_frames)
        if not frames:
            raise web_request.error("No image files found in %s" % path)
        try:
            class WebGcmd:
                def error(self, msg):
                    raise Exception(msg)
            summary, findings = self._analyze_frames(WebGcmd(), frames)
            summary['frame_findings'] = findings
            web_request.send(summary)
        except Exception as e:
            raise web_request.error(str(e))
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))

def load_config(config):
    return AITimelapse(config)
