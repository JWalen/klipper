# AI Calibration Wizard - Full printer calibration with AI guidance
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

CALIBRATION_STEPS = [
    {
        'id': 'home',
        'name': 'Home All Axes',
        'gcode': 'G28',
        'config_section': None,
        'description': 'Home all axes to establish reference positions',
    },
    {
        'id': 'probe_z_offset',
        'name': 'Probe Z-Offset Calibration',
        'gcode': 'PROBE_CALIBRATE',
        'config_section': 'probe',
        'description': 'Calibrate the Z offset between the probe and nozzle',
    },
    {
        'id': 'screws_tilt',
        'name': 'Bed Screws Tilt Adjustment',
        'gcode': 'SCREWS_TILT_CALCULATE',
        'config_section': 'screws_tilt_adjust',
        'description': 'Calculate bed leveling screw adjustments',
    },
    {
        'id': 'z_tilt',
        'name': 'Z Tilt Adjustment',
        'gcode': 'Z_TILT_ADJUST',
        'config_section': 'z_tilt',
        'description': 'Adjust Z steppers to level the gantry',
    },
    {
        'id': 'quad_gantry_level',
        'name': 'Quad Gantry Level',
        'gcode': 'QUAD_GANTRY_LEVEL',
        'config_section': 'quad_gantry_level',
        'description': 'Level the gantry using four Z steppers',
    },
    {
        'id': 'delta_calibrate',
        'name': 'Delta Calibration',
        'gcode': 'DELTA_CALIBRATE',
        'config_section': 'delta_calibrate',
        'description': 'Calibrate delta printer kinematics',
    },
    {
        'id': 'bed_mesh',
        'name': 'Bed Mesh Calibration',
        'gcode': 'BED_MESH_CALIBRATE',
        'config_section': 'bed_mesh',
        'description': 'Create a bed mesh for automatic compensation',
    },
    {
        'id': 'pid_bed',
        'name': 'PID Calibrate Bed',
        'gcode': 'PID_CALIBRATE HEATER=heater_bed TARGET=60',
        'config_section': 'heater_bed',
        'description': 'Auto-tune PID parameters for the heated bed',
    },
    {
        'id': 'pid_extruder',
        'name': 'PID Calibrate Extruder',
        'gcode': 'PID_CALIBRATE HEATER=extruder TARGET=200',
        'config_section': 'extruder',
        'description': 'Auto-tune PID parameters for the extruder heater',
    },
    {
        'id': 'input_shaper',
        'name': 'Input Shaper Calibration',
        'gcode': 'SHAPER_CALIBRATE',
        'config_section': 'resonance_tester',
        'description': 'Calibrate input shaping to reduce ringing',
    },
    {
        'id': 'axis_twist',
        'name': 'Axis Twist Compensation',
        'gcode': 'AXIS_TWIST_COMPENSATION_CALIBRATE',
        'config_section': 'axis_twist_compensation',
        'description': 'Calibrate axis twist compensation',
    },
]


def verify_no_wizard(printer):
    gcode = printer.lookup_object('gcode')
    try:
        gcode.register_command('AI_CALIBRATE_NEXT', 'dummy')
    except printer.config_error:
        raise gcode.error(
            "A calibration wizard is already in progress. "
            "Use AI_CALIBRATE_ABORT to abort it.")
    gcode.register_command('AI_CALIBRATE_NEXT', None)


class CalibrationWizard:
    def __init__(self, printer, gcmd, ai_backend, prompt_manager,
                 available_steps, skip_ids, start_step_idx,
                 finalize_callback):
        self.printer = printer
        self.ai_backend = ai_backend
        self.prompt_manager = prompt_manager
        self.gcode = printer.lookup_object('gcode')
        self.steps = available_steps
        self.skip_ids = set(skip_ids)
        self.current_step_idx = start_step_idx
        self.finalize_callback = finalize_callback
        self.completed_steps = []
        self.skipped_steps = []
        self.step_results = {}
        self.is_active = True
        # Register temporary commands
        verify_no_wizard(printer)
        self.gcode.register_command(
            'AI_CALIBRATE_NEXT', self.cmd_AI_CALIBRATE_NEXT,
            desc=self.cmd_AI_CALIBRATE_NEXT_help)
        self.gcode.register_command(
            'AI_CALIBRATE_SKIP', self.cmd_AI_CALIBRATE_SKIP,
            desc=self.cmd_AI_CALIBRATE_SKIP_help)
        self.gcode.register_command(
            'AI_CALIBRATE_ABORT', self.cmd_AI_CALIBRATE_ABORT,
            desc=self.cmd_AI_CALIBRATE_ABORT_help)
        # Start first step
        self._start_current_step(gcmd)
    def _get_config_text(self):
        configfile = self.printer.lookup_object('configfile')
        reactor = self.printer.get_reactor()
        config_status = configfile.get_status(reactor.monotonic())
        raw_config = config_status.get('config', {})
        lines = []
        for sec_name, sec_data in sorted(raw_config.items()):
            lines.append('[%s]' % (sec_name,))
            if isinstance(sec_data, dict):
                for key, value in sorted(sec_data.items()):
                    lines.append('%s: %s' % (key, value))
            lines.append('')
        return '\n'.join(lines)
    def _start_current_step(self, gcmd):
        # Skip over steps that should be skipped
        while (self.current_step_idx < len(self.steps)
               and self.steps[self.current_step_idx]['id'] in self.skip_ids):
            step = self.steps[self.current_step_idx]
            self.skipped_steps.append(step['id'])
            self.gcode.respond_info("Skipping step: %s" % (step['name'],))
            self.current_step_idx += 1
        if self.current_step_idx >= len(self.steps):
            self._finalize(True)
            return
        step = self.steps[self.current_step_idx]
        self.gcode.respond_info(
            "\n===== Calibration Step %d/%d: %s =====\n"
            "Command: %s\n"
            "Description: %s"
            % (self.current_step_idx + 1, len(self.steps),
               step['name'], step['gcode'], step['description']))
        # Get AI guidance before step
        self._get_pre_step_guidance(step)
        self.gcode.respond_info(
            "\nReady to run: %s\n"
            "Use AI_CALIBRATE_NEXT to proceed, "
            "AI_CALIBRATE_SKIP to skip, or "
            "AI_CALIBRATE_ABORT to abort."
            % (step['gcode'],))
        # Save wizard state for resume
        self._save_state()
    def _get_pre_step_guidance(self, step):
        if self.ai_backend is None:
            return
        try:
            config_text = self._get_config_text()
            prompt = self.prompt_manager.get_prompt(
                'calibration_before',
                step['name'], step['gcode'], config_text)
            response = self.ai_backend.query(prompt)
            self.gcode.respond_info("AI Guidance:\n%s" % (response,))
        except Exception as e:
            logging.warning("ai_calibration_wizard: Failed to get "
                            "pre-step guidance: %s", str(e))
    def _get_post_step_guidance(self, step, result_text):
        if self.ai_backend is None:
            return
        try:
            prompt = self.prompt_manager.get_prompt(
                'calibration_after',
                step['name'], step['gcode'], result_text)
            response = self.ai_backend.query(prompt)
            self.gcode.respond_info("AI Analysis:\n%s" % (response,))
        except Exception as e:
            logging.warning("ai_calibration_wizard: Failed to get "
                            "post-step guidance: %s", str(e))
    def _save_state(self):
        configfile = self.printer.lookup_object('configfile')
        step_ids = ','.join([s['id'] for s in self.steps])
        completed = ','.join(self.completed_steps)
        skipped = ','.join(self.skipped_steps)
        current_id = ''
        if self.current_step_idx < len(self.steps):
            current_id = self.steps[self.current_step_idx]['id']
        configfile.set('ai_calibration_wizard', 'wizard_steps', step_ids)
        configfile.set('ai_calibration_wizard', 'wizard_completed', completed)
        configfile.set('ai_calibration_wizard', 'wizard_skipped', skipped)
        configfile.set('ai_calibration_wizard', 'wizard_current', current_id)
        configfile.set('ai_calibration_wizard', 'wizard_active', 'True')
    def _clear_state(self):
        configfile = self.printer.lookup_object('configfile')
        configfile.remove_section('ai_calibration_wizard')
    cmd_AI_CALIBRATE_NEXT_help = "Proceed to execute current calibration step"
    def cmd_AI_CALIBRATE_NEXT(self, gcmd):
        if self.current_step_idx >= len(self.steps):
            self._finalize(True)
            return
        step = self.steps[self.current_step_idx]
        self.gcode.respond_info("Running: %s" % (step['gcode'],))
        # Capture output for AI analysis
        output_lines = []
        capturing = [True]
        def output_handler(msg):
            if capturing[0]:
                output_lines.append(msg)
        self.gcode.register_output_handler(output_handler)
        try:
            self.gcode.run_script_from_command(step['gcode'])
            capturing[0] = False
            result_text = '\n'.join(output_lines)
            self.step_results[step['id']] = result_text
            self.completed_steps.append(step['id'])
            self.gcode.respond_info("Step completed: %s" % (step['name'],))
            # Get AI analysis of results
            self._get_post_step_guidance(step, result_text or '(no output)')
        except self.printer.command_error as e:
            capturing[0] = False
            result_text = "Error: %s" % (str(e),)
            self.step_results[step['id']] = result_text
            self.gcode.respond_info(
                "Step failed: %s\nError: %s\n"
                "Use AI_CALIBRATE_NEXT to retry, "
                "AI_CALIBRATE_SKIP to skip, or "
                "AI_CALIBRATE_ABORT to abort."
                % (step['name'], str(e)))
            return
        # Move to next step
        self.current_step_idx += 1
        self._start_current_step(gcmd)
    cmd_AI_CALIBRATE_SKIP_help = "Skip the current calibration step"
    def cmd_AI_CALIBRATE_SKIP(self, gcmd):
        if self.current_step_idx >= len(self.steps):
            self._finalize(True)
            return
        step = self.steps[self.current_step_idx]
        self.skipped_steps.append(step['id'])
        self.gcode.respond_info("Skipped step: %s" % (step['name'],))
        self.current_step_idx += 1
        self._start_current_step(gcmd)
    cmd_AI_CALIBRATE_ABORT_help = "Abort the calibration wizard"
    def cmd_AI_CALIBRATE_ABORT(self, gcmd):
        self.gcode.respond_info("Calibration wizard aborted.")
        self._finalize(False)
    def _finalize(self, success):
        self.is_active = False
        # Unregister temporary commands
        self.gcode.register_command('AI_CALIBRATE_NEXT', None)
        self.gcode.register_command('AI_CALIBRATE_SKIP', None)
        self.gcode.register_command('AI_CALIBRATE_ABORT', None)
        if success:
            self._clear_state()
            self.gcode.respond_info(
                "\n===== Calibration Wizard Complete =====\n"
                "Completed steps: %s\n"
                "Skipped steps: %s\n"
                "Use SAVE_CONFIG to save results."
                % (', '.join(self.completed_steps) or 'None',
                   ', '.join(self.skipped_steps) or 'None'))
        else:
            self._save_state()
        self.finalize_callback(success, self.completed_steps,
                               self.skipped_steps)
    def get_status(self):
        current_step = None
        if self.current_step_idx < len(self.steps):
            current_step = self.steps[self.current_step_idx]['id']
        return {
            'is_active': self.is_active,
            'current_step': current_step,
            'current_step_idx': self.current_step_idx,
            'total_steps': len(self.steps),
            'completed_steps': list(self.completed_steps),
            'skipped_steps': list(self.skipped_steps),
        }


class AICalibrationWizard:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.active_wizard = None
        # Check for saved state to offer resume
        self.saved_state = {
            'active': config.get('wizard_active', 'False'),
            'current': config.get('wizard_current', ''),
            'completed': config.get('wizard_completed', ''),
            'skipped': config.get('wizard_skipped', ''),
            'steps': config.get('wizard_steps', ''),
        }
        # Register events
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register permanent commands
        self.gcode.register_command(
            'AI_CALIBRATE_START', self.cmd_AI_CALIBRATE_START,
            desc=self.cmd_AI_CALIBRATE_START_help)
        self.gcode.register_command(
            'AI_CALIBRATE_STATUS', self.cmd_AI_CALIBRATE_STATUS,
            desc=self.cmd_AI_CALIBRATE_STATUS_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_calibration_wizard/start',
                                   self._handle_start_request)
        webhooks.register_endpoint('ai_calibration_wizard/next',
                                   self._handle_next_request)
        webhooks.register_endpoint('ai_calibration_wizard/skip',
                                   self._handle_skip_request)
        webhooks.register_endpoint('ai_calibration_wizard/status',
                                   self._handle_status_request)
        webhooks.register_endpoint('ai_calibration_wizard/abort',
                                   self._handle_abort_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
        # Check for interrupted wizard
        if self.saved_state['active'] == 'True':
            current = self.saved_state['current']
            completed = self.saved_state['completed']
            self.gcode.respond_info(
                "AI Calibration Wizard was interrupted.\n"
                "Current step: %s\n"
                "Completed: %s\n"
                "Use AI_CALIBRATE_START FROM_STEP=%s to resume."
                % (current or 'unknown',
                   completed or 'none',
                   current or 'home'))
    def _get_available_steps(self):
        configfile = self.printer.lookup_object('configfile')
        config_status = configfile.get_status(self.reactor.monotonic())
        raw_config = config_status.get('config', {})
        available = []
        for step in CALIBRATION_STEPS:
            section = step['config_section']
            if section is None or section in raw_config:
                available.append(dict(step))
        return available
    def _wizard_finalize(self, success, completed, skipped):
        self.active_wizard = None
        if success:
            logging.info("ai_calibration_wizard: Wizard completed. "
                         "Steps: %s, Skipped: %s",
                         ','.join(completed), ','.join(skipped))
        else:
            logging.info("ai_calibration_wizard: Wizard aborted. "
                         "Completed: %s, Skipped: %s",
                         ','.join(completed), ','.join(skipped))
    def get_status(self, eventtime):
        if self.active_wizard is not None:
            return self.active_wizard.get_status()
        return {
            'is_active': False,
            'current_step': None,
            'current_step_idx': 0,
            'total_steps': 0,
            'completed_steps': [],
            'skipped_steps': [],
            'has_saved_state': self.saved_state['active'] == 'True',
        }
    # G-code commands
    cmd_AI_CALIBRATE_START_help = "Start AI-guided calibration wizard"
    def cmd_AI_CALIBRATE_START(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        if self.active_wizard is not None:
            raise gcmd.error(
                "Calibration wizard already in progress. "
                "Use AI_CALIBRATE_ABORT to abort it first.")
        # Get available steps based on config
        available_steps = self._get_available_steps()
        if not available_steps:
            raise gcmd.error("No calibration steps available")
        # Parse FROM_STEP
        from_step = gcmd.get('FROM_STEP', None)
        start_idx = 0
        if from_step is not None:
            found = False
            for i, step in enumerate(available_steps):
                if step['id'] == from_step:
                    start_idx = i
                    found = True
                    break
            if not found:
                valid_ids = ', '.join([s['id'] for s in available_steps])
                raise gcmd.error(
                    "Unknown step '%s'. Valid steps: %s"
                    % (from_step, valid_ids))
        # Parse SKIP
        skip_str = gcmd.get('SKIP', '')
        skip_ids = [s.strip() for s in skip_str.split(',') if s.strip()]
        # Report plan
        self.gcode.respond_info(
            "\n===== AI Calibration Wizard =====\n"
            "Steps to perform:")
        for i, step in enumerate(available_steps):
            marker = '  '
            if i < start_idx:
                marker = '  (skip - before start) '
            elif step['id'] in skip_ids:
                marker = '  (skip - requested) '
            self.gcode.respond_info(
                "%s%d. %s [%s]" % (marker, i + 1, step['name'], step['id']))
        # Start wizard
        self.active_wizard = CalibrationWizard(
            self.printer, gcmd, self.ai_backend, self.prompt_manager,
            available_steps, skip_ids, start_idx,
            self._wizard_finalize)
    cmd_AI_CALIBRATE_STATUS_help = "Report calibration wizard status"
    def cmd_AI_CALIBRATE_STATUS(self, gcmd):
        status = self.get_status(self.reactor.monotonic())
        if not status['is_active']:
            if status.get('has_saved_state'):
                self.gcode.respond_info(
                    "No active wizard, but interrupted state exists.\n"
                    "Use AI_CALIBRATE_START FROM_STEP=<step> to resume.")
            else:
                self.gcode.respond_info(
                    "No calibration wizard active.\n"
                    "Use AI_CALIBRATE_START to begin.")
            return
        self.gcode.respond_info(
            "Calibration Wizard Status:\n"
            "  Active: %s\n"
            "  Current Step: %s (%d/%d)\n"
            "  Completed: %s\n"
            "  Skipped: %s"
            % (status['is_active'],
               status['current_step'] or 'done',
               status['current_step_idx'] + 1,
               status['total_steps'],
               ', '.join(status['completed_steps']) or 'None',
               ', '.join(status['skipped_steps']) or 'None'))
    # Webhooks handlers
    def _handle_start_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        if self.active_wizard is not None:
            raise web_request.error("Wizard already in progress")
        # Cannot fully start via webhooks (needs gcmd context),
        # run via gcode script
        from_step = web_request.get_str('from_step', '')
        skip = web_request.get_str('skip', '')
        cmd = 'AI_CALIBRATE_START'
        if from_step:
            cmd += ' FROM_STEP=%s' % (from_step,)
        if skip:
            cmd += ' SKIP=%s' % (skip,)
        self.gcode.run_script(cmd)
        web_request.send(self.get_status(self.reactor.monotonic()))
    def _handle_next_request(self, web_request):
        if self.active_wizard is None:
            raise web_request.error("No active wizard")
        self.gcode.run_script('AI_CALIBRATE_NEXT')
        web_request.send(self.get_status(self.reactor.monotonic()))
    def _handle_skip_request(self, web_request):
        if self.active_wizard is None:
            raise web_request.error("No active wizard")
        self.gcode.run_script('AI_CALIBRATE_SKIP')
        web_request.send(self.get_status(self.reactor.monotonic()))
    def _handle_status_request(self, web_request):
        web_request.send(self.get_status(self.reactor.monotonic()))
    def _handle_abort_request(self, web_request):
        if self.active_wizard is None:
            raise web_request.error("No active wizard")
        self.gcode.run_script('AI_CALIBRATE_ABORT')
        web_request.send(self.get_status(self.reactor.monotonic()))

def load_config(config):
    return AICalibrationWizard(config)
