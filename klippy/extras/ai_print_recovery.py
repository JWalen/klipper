# AI Print Recovery - Smart failure recovery with AI guidance
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, re


class AIPrintRecovery:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.ai_camera = None
        # Config
        self.enabled = config.getboolean('enabled', True)
        self.max_retries = config.getint('max_retries', 2, minval=0)
        self.purge_amount = config.getfloat('purge_amount', 30.0, above=0.)
        self.z_hop = config.getfloat('z_hop', 5.0, above=0.)
        # State
        self.retry_count = 0
        self.is_recovering = False
        self.last_recovery_result = {}
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_RECOVER', self.cmd_AI_RECOVER,
            desc=self.cmd_AI_RECOVER_help)
        self.gcode.register_command(
            'AI_RECOVERY_ENABLE', self.cmd_AI_RECOVERY_ENABLE,
            desc=self.cmd_AI_RECOVERY_ENABLE_help)
        self.gcode.register_command(
            'AI_RECOVERY_DISABLE', self.cmd_AI_RECOVERY_DISABLE,
            desc=self.cmd_AI_RECOVERY_DISABLE_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_print_recovery/status',
                                   self._handle_status_request)
        webhooks.register_endpoint('ai_print_recovery/recover',
                                   self._handle_recover_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
        self.ai_camera = self.printer.lookup_object('ai_camera', None)
    def _assess_failure(self, gcmd):
        if self.ai_camera is None:
            raise gcmd.error("AI camera not configured")
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        # Capture image
        self.gcode.respond_info("Capturing image for failure assessment...")
        try:
            image_path = self.ai_camera.camera.capture()
        except Exception as e:
            raise gcmd.error("Camera capture failed: %s" % str(e))
        # Get print context
        print_stats = self.printer.lookup_object('print_stats', None)
        filename = 'unknown'
        layer = 'unknown'
        if print_stats is not None:
            ps_status = print_stats.get_status(self.reactor.monotonic())
            filename = ps_status.get('filename', 'unknown')
            info = ps_status.get('info', {})
            current_layer = info.get('current_layer')
            if current_layer is not None:
                layer = str(current_layer)
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        z_pos = pos[2]
        # Get last camera findings
        last_result = getattr(self.ai_camera, 'last_check_result', {})
        failure_type = last_result.get('findings', 'unknown failure')
        prompt = self.prompt_manager.get_prompt(
            'recovery_assess', filename, layer, z_pos, failure_type)
        self.gcode.respond_info("Assessing failure with AI...")
        try:
            response = self.ai_backend.query(prompt, images=[image_path])
        except self.printer.command_error as e:
            raise gcmd.error("AI assessment failed: %s" % str(e))
        return self._parse_assessment(response)
    def _parse_assessment(self, response):
        result = {
            'recoverable': False,
            'failure_type': 'unknown',
            'failed_layer': 'UNKNOWN',
            'recommendation': '',
        }
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('RECOVERABLE:'):
                val = line.split(':', 1)[1].strip().upper()
                result['recoverable'] = val == 'YES'
            elif line.startswith('FAILURE_TYPE:'):
                result['failure_type'] = line.split(':', 1)[1].strip()
            elif line.startswith('FAILED_LAYER:'):
                result['failed_layer'] = line.split(':', 1)[1].strip()
            elif line.startswith('RECOMMENDATION:'):
                result['recommendation'] = line.split(':', 1)[1].strip()
        return result
    def _attempt_recovery(self, gcmd):
        self.gcode.respond_info("Attempting print recovery...")
        self.is_recovering = True
        try:
            # Lift, purge, retract
            recovery_gcode = [
                'G91',
                'G1 Z%.1f F600' % self.z_hop,
                'G1 X10 F3000',
                'G92 E0',
                'G1 E%.1f F300' % self.purge_amount,
                'G92 E0',
                'G1 E-2.0 F3600',
                'G1 X-10 F3000',
                'G1 Z%.1f F600' % (-self.z_hop),
                'G90',
            ]
            for line in recovery_gcode:
                self.gcode.run_script_from_command(line)
            # Resume print
            self.gcode.run_script_from_command('RESUME')
            self.retry_count += 1
            self.gcode.respond_info(
                "Recovery attempt %d complete. Print resumed."
                % self.retry_count)
            # Schedule verification check
            if self.ai_camera is not None:
                self.reactor.register_callback(
                    lambda e: self._verify_recovery())
        finally:
            self.is_recovering = False
    def _verify_recovery(self):
        # Wait 60 seconds then check
        self.reactor.pause(self.reactor.monotonic() + 60.0)
        if self.ai_camera is None or self.ai_backend is None:
            return
        try:
            image_path = self.ai_camera.camera.capture()
            prompt = self.prompt_manager.get_prompt('recovery_verify')
            response = self.ai_backend.query(prompt, images=[image_path])
            result = self._parse_verify(response)
            self.last_recovery_result = result
            if result.get('status') == 'FAILURE':
                self.gcode.respond_info(
                    "Recovery verification: Print still failing. "
                    "Findings: %s" % result.get('findings', ''))
            else:
                self.gcode.respond_info(
                    "Recovery verification: %s. %s"
                    % (result.get('status', 'OK'),
                       result.get('findings', '')))
        except Exception as e:
            logging.warning("ai_print_recovery: verify failed: %s", str(e))
    def _parse_verify(self, response):
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
            'enabled': self.enabled,
            'is_recovering': self.is_recovering,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'last_recovery_result': self.last_recovery_result,
        }
    # G-code commands
    cmd_AI_RECOVER_help = "Attempt AI-guided print recovery"
    def cmd_AI_RECOVER(self, gcmd):
        if not self.enabled:
            raise gcmd.error("AI recovery is disabled. "
                             "Run AI_RECOVERY_ENABLE first.")
        if self.is_recovering:
            raise gcmd.error("Recovery already in progress")
        # Check if print is paused
        pause_resume = self.printer.lookup_object('pause_resume', None)
        if pause_resume is None:
            raise gcmd.error("pause_resume not configured")
        pr_status = pause_resume.get_status(self.reactor.monotonic())
        if not pr_status.get('is_paused', False):
            raise gcmd.error("Print is not paused. "
                             "Pause the print first or let AI camera "
                             "detect a failure.")
        if self.retry_count >= self.max_retries:
            raise gcmd.error(
                "Maximum recovery attempts (%d) reached. "
                "Cancel and restart the print." % self.max_retries)
        # Assess failure
        assessment = self._assess_failure(gcmd)
        self.gcode.respond_info(
            "AI Assessment:\n"
            "  Recoverable: %s\n"
            "  Failure type: %s\n"
            "  Failed layer: %s\n"
            "  Recommendation: %s"
            % ('Yes' if assessment['recoverable'] else 'No',
               assessment['failure_type'],
               assessment['failed_layer'],
               assessment['recommendation']))
        if not assessment['recoverable']:
            self.gcode.respond_info(
                "AI determined this failure is not recoverable. "
                "Consider cancelling the print.")
            return
        self._attempt_recovery(gcmd)
    cmd_AI_RECOVERY_ENABLE_help = "Enable AI print recovery"
    def cmd_AI_RECOVERY_ENABLE(self, gcmd):
        self.enabled = True
        self.retry_count = 0
        self.gcode.respond_info("AI print recovery enabled.")
    cmd_AI_RECOVERY_DISABLE_help = "Disable AI print recovery"
    def cmd_AI_RECOVERY_DISABLE(self, gcmd):
        self.enabled = False
        self.gcode.respond_info("AI print recovery disabled.")
    # Webhook handlers
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))
    def _handle_recover_request(self, web_request):
        if not self.enabled:
            raise web_request.error("AI recovery is disabled")
        try:
            self.gcode.run_script_from_command('AI_RECOVER')
            web_request.send({'status': 'recovery_attempted',
                              'retry_count': self.retry_count})
        except self.printer.command_error as e:
            raise web_request.error(str(e))

def load_config(config):
    return AIPrintRecovery(config)
