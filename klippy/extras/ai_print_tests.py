# AI Print Tests - Generate and run calibration test prints
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math, re


class AIPrintTests:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.ai_camera = None
        self.running = False
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_TEST_FIRST_LAYER', self.cmd_AI_TEST_FIRST_LAYER,
            desc=self.cmd_AI_TEST_FIRST_LAYER_help)
        self.gcode.register_command(
            'AI_TEST_FLOW', self.cmd_AI_TEST_FLOW,
            desc=self.cmd_AI_TEST_FLOW_help)
        self.gcode.register_command(
            'AI_TEST_PA', self.cmd_AI_TEST_PA,
            desc=self.cmd_AI_TEST_PA_help)
        self.gcode.register_command(
            'AI_TEST_SPEED', self.cmd_AI_TEST_SPEED,
            desc=self.cmd_AI_TEST_SPEED_help)
        self.gcode.register_command(
            'AI_TEST_TEMP', self.cmd_AI_TEST_TEMP,
            desc=self.cmd_AI_TEST_TEMP_help)
        self.gcode.register_command(
            'AI_TEST_RETRACTION', self.cmd_AI_TEST_RETRACTION,
            desc=self.cmd_AI_TEST_RETRACTION_help)
        self.gcode.register_command(
            'AI_TEST_BRIDGING', self.cmd_AI_TEST_BRIDGING,
            desc=self.cmd_AI_TEST_BRIDGING_help)
        self.gcode.register_command(
            'AI_TEST_OVERHANG', self.cmd_AI_TEST_OVERHANG,
            desc=self.cmd_AI_TEST_OVERHANG_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_print_tests/status',
                                   self._handle_status_request)
        webhooks.register_endpoint('ai_print_tests/run',
                                   self._handle_run_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
        self.ai_camera = self.printer.lookup_object('ai_camera', None)
    def _get_printer_params(self):
        toolhead = self.printer.lookup_object('toolhead')
        kin_status = toolhead.get_kinematics().get_status(
            self.reactor.monotonic())
        x_max = kin_status['axis_maximum'][0]
        y_max = kin_status['axis_maximum'][1]
        extruder = self.printer.lookup_object('extruder')
        nozzle_dia = extruder.nozzle_diameter
        # filament_diameter is not stored; derive from filament_area
        filament_dia = 2.0 * math.sqrt(extruder.filament_area / math.pi)
        return {
            'x_max': x_max,
            'y_max': y_max,
            'nozzle_dia': nozzle_dia,
            'filament_dia': filament_dia,
        }
    def _calc_extrusion(self, length, width, height, filament_dia):
        # Volume-based E calculation
        cross_section = width * height
        volume = cross_section * length
        filament_area = math.pi * (filament_dia / 2.0) ** 2
        return 1.05 * volume / filament_area
    def _generate_preamble(self, bed_temp, extruder_temp, params):
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        x_max = params['x_max']
        primer_width = 0.75 * nozzle_dia
        primer_height = 0.70 * nozzle_dia
        prime_length = x_max - 40.0
        prime_e = self._calc_extrusion(prime_length, primer_width,
                                       primer_height, filament_dia)
        lines = [
            '; AI Print Test - Preamble',
            'G21 ; metric',
            'G90 ; absolute positioning',
            'M82 ; absolute extrusion',
            'M140 S%d ; heat bed' % bed_temp,
            'M104 S175 ; preheat extruder',
            'M190 S%d ; wait for bed' % bed_temp,
            'G28 ; home all',
            'M109 S%d ; wait for extruder' % extruder_temp,
            '; Prime line',
            'G92 E0',
            'G1 X20.0 Y3.0 Z%.3f F6000' % primer_height,
            'G1 X%.1f Y3.0 E%.4f F2000' % (x_max - 20.0, prime_e),
            'G92 E0',
            'G1 Z2.0 F600',
        ]
        return lines
    def _generate_first_layer_test(self, params):
        x_max = params['x_max']
        y_max = params['y_max']
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        margin = 30.0
        spacing = 10.0
        x_start = margin
        x_end = x_max - margin
        y_start = margin
        y_end = y_max - margin
        line_length = x_end - x_start
        lines = ['; First Layer Test - zigzag lines at %.2fmm height'
                 % layer_height]
        e_total = 0.0
        lines.append('G92 E0')
        lines.append('G1 Z%.3f F600' % layer_height)
        y = y_start
        forward = True
        while y <= y_end:
            e_seg = self._calc_extrusion(line_length, line_width,
                                         layer_height, filament_dia)
            if forward:
                lines.append('G1 X%.1f Y%.1f F3000' % (x_start, y))
                e_total += e_seg
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (x_end, y, e_total))
            else:
                lines.append('G1 X%.1f Y%.1f F3000' % (x_end, y))
                e_total += e_seg
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (x_start, y, e_total))
            forward = not forward
            y += spacing
        return lines
    def _generate_flow_test(self, params, start, end, steps):
        x_max = params['x_max']
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        margin = 30.0
        line_length = x_max - 2 * margin
        group_spacing = 15.0
        line_spacing = 3.0
        lines_per_group = 5
        lines = ['; Flow Test - groups at varying extrusion multipliers']
        e_total = 0.0
        lines.append('G92 E0')
        lines.append('G1 Z%.3f F600' % layer_height)
        for i in range(steps):
            if steps > 1:
                flow = start + (end - start) * i / (steps - 1)
            else:
                flow = start
            y_base = margin + i * group_spacing
            lines.append('; Flow %.0f%%' % (flow * 100))
            for j in range(lines_per_group):
                y = y_base + j * line_spacing
                e_seg = self._calc_extrusion(line_length, line_width,
                                             layer_height, filament_dia)
                e_seg *= flow
                lines.append('G1 X%.1f Y%.1f F3000' % (margin, y))
                e_total += e_seg
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (margin + line_length, y, e_total))
        return lines
    def _generate_pa_test(self, params, start, end, steps):
        x_max = params['x_max']
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        margin = 30.0
        line_spacing = 5.0
        total_length = x_max - 2 * margin
        slow_length = total_length * 0.2
        fast_length = total_length * 0.6
        slow_speed = 1200  # 20mm/s F value
        fast_speed = 6000  # 100mm/s F value
        lines = ['; PA Test - slow-fast-slow lines at varying PA values']
        e_total = 0.0
        lines.append('G92 E0')
        lines.append('G1 Z%.3f F600' % layer_height)
        for i in range(steps):
            if steps > 1:
                pa_val = start + (end - start) * i / (steps - 1)
            else:
                pa_val = start
            y = margin + i * line_spacing
            lines.append('; PA %.4f' % pa_val)
            lines.append('SET_PRESSURE_ADVANCE ADVANCE=%.4f' % pa_val)
            x = margin
            # Slow segment
            lines.append('G1 X%.1f Y%.1f F3000' % (x, y))
            e_seg = self._calc_extrusion(slow_length, line_width,
                                         layer_height, filament_dia)
            e_total += e_seg
            x += slow_length
            lines.append('G1 X%.1f Y%.1f E%.4f F%d'
                         % (x, y, e_total, slow_speed))
            # Fast segment
            e_seg = self._calc_extrusion(fast_length, line_width,
                                         layer_height, filament_dia)
            e_total += e_seg
            x += fast_length
            lines.append('G1 X%.1f Y%.1f E%.4f F%d'
                         % (x, y, e_total, fast_speed))
            # Slow segment
            e_seg = self._calc_extrusion(slow_length, line_width,
                                         layer_height, filament_dia)
            e_total += e_seg
            x += slow_length
            lines.append('G1 X%.1f Y%.1f E%.4f F%d'
                         % (x, y, e_total, slow_speed))
        # Restore PA to 0
        lines.append('SET_PRESSURE_ADVANCE ADVANCE=0')
        return lines
    def _generate_speed_test(self, params, start, end, steps):
        x_max = params['x_max']
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        margin = 30.0
        line_length = x_max - 2 * margin
        line_spacing = 5.0
        lines = ['; Speed Test - lines at increasing print speeds']
        e_total = 0.0
        lines.append('G92 E0')
        lines.append('G1 Z%.3f F600' % layer_height)
        for i in range(steps):
            if steps > 1:
                speed = start + (end - start) * i / (steps - 1)
            else:
                speed = start
            f_val = speed * 60  # mm/s to mm/min
            y = margin + i * line_spacing
            e_seg = self._calc_extrusion(line_length, line_width,
                                         layer_height, filament_dia)
            lines.append('; Speed %.0f mm/s' % speed)
            lines.append('G1 X%.1f Y%.1f F3000' % (margin, y))
            e_total += e_seg
            lines.append('G1 X%.1f Y%.1f E%.4f F%d'
                         % (margin + line_length, y, e_total, int(f_val)))
        return lines
    def _generate_temp_tower(self, params, start_temp, end_temp, step):
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        layers_per_section = 5
        box_size = 20.0
        x_center = params['x_max'] / 2.0
        y_center = params['y_max'] / 2.0
        x0 = x_center - box_size / 2.0
        y0 = y_center - box_size / 2.0
        x1 = x0 + box_size
        y1 = y0 + box_size
        temps = list(range(start_temp, end_temp + 1, step))
        lines = ['; Temperature Tower Test - %d to %d°C in %d°C steps'
                 % (start_temp, end_temp, step)]
        e_total = 0.0
        lines.append('G92 E0')
        z = 0.0
        side_e = self._calc_extrusion(box_size, line_width,
                                       layer_height, filament_dia)
        for temp_idx, temp in enumerate(temps):
            lines.append('; Section %d: %d°C' % (temp_idx + 1, temp))
            lines.append('M104 S%d' % temp)
            if temp_idx == 0:
                lines.append('M109 S%d' % temp)
            for layer in range(layers_per_section):
                z += layer_height
                lines.append('G1 Z%.3f F600' % z)
                lines.append('G1 X%.1f Y%.1f F3000' % (x0, y0))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500' % (x1, y0, e_total))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500' % (x1, y1, e_total))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500' % (x0, y1, e_total))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500' % (x0, y0, e_total))
        return lines
    def _generate_retraction_test(self, params, start, end, steps):
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        column_size = 10.0
        column_spacing = 15.0
        column_layers = 36  # ~10mm tall
        margin = 30.0
        lines = ['; Retraction Test - columns with varying retraction lengths']
        e_total = 0.0
        lines.append('G92 E0')
        side_e = self._calc_extrusion(column_size, line_width,
                                       layer_height, filament_dia)
        for layer in range(column_layers):
            z = (layer + 1) * layer_height
            lines.append('G1 Z%.3f F600' % z)
            for i in range(steps):
                if steps > 1:
                    retract_len = start + (end - start) * i / (steps - 1)
                else:
                    retract_len = start
                if layer == 0:
                    lines.append('; Column %d: retract %.2fmm'
                                 % (i + 1, retract_len))
                lines.append('SET_RETRACTION RETRACT_LENGTH=%.3f'
                             % retract_len)
                x_base = margin + i * column_spacing
                y_base = margin
                lines.append('G1 X%.1f Y%.1f F3000' % (x_base, y_base))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (x_base + column_size, y_base, e_total))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (x_base + column_size,
                                y_base + column_size, e_total))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (x_base, y_base + column_size, e_total))
                e_total += side_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (x_base, y_base, e_total))
        lines.append('SET_RETRACTION RETRACT_LENGTH=0.9')
        return lines
    def _generate_bridging_test(self, params, spans):
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        pillar_size = 10.0
        pillar_layers = 18  # ~5mm tall
        bridge_lines = 5
        margin = 30.0
        y_spacing = 25.0
        lines = ['; Bridging Test - bridges at increasing spans']
        e_total = 0.0
        lines.append('G92 E0')
        side_e = self._calc_extrusion(pillar_size, line_width,
                                       layer_height, filament_dia)
        # Phase 1: Build support pillars
        for layer in range(pillar_layers):
            z = (layer + 1) * layer_height
            lines.append('G1 Z%.3f F600' % z)
            for s_idx, span in enumerate(spans):
                y_base = margin + s_idx * y_spacing
                for pillar_x in [margin, margin + pillar_size + span]:
                    px0 = pillar_x
                    py0 = y_base
                    px1 = pillar_x + pillar_size
                    py1 = y_base + pillar_size
                    lines.append('G1 X%.1f Y%.1f F3000' % (px0, py0))
                    e_total += side_e
                    lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                                 % (px1, py0, e_total))
                    e_total += side_e
                    lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                                 % (px1, py1, e_total))
                    e_total += side_e
                    lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                                 % (px0, py1, e_total))
                    e_total += side_e
                    lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                                 % (px0, py0, e_total))
        # Phase 2: Bridge lines
        z = (pillar_layers + 1) * layer_height
        lines.append('G1 Z%.3f F600' % z)
        for s_idx, span in enumerate(spans):
            y_base = margin + s_idx * y_spacing
            bridge_start = margin + pillar_size
            bridge_end = margin + pillar_size + span
            lines.append('; Bridge span %.0fmm' % span)
            for j in range(bridge_lines):
                y = y_base + 2.0 + j * (pillar_size - 4.0) / max(
                    bridge_lines - 1, 1)
                e_seg = self._calc_extrusion(span, line_width,
                                             layer_height, filament_dia)
                lines.append('G1 X%.1f Y%.1f F3000' % (bridge_start, y))
                e_total += e_seg
                lines.append('G1 X%.1f Y%.1f E%.4f F1200'
                             % (bridge_end, y, e_total))
        return lines
    def _generate_overhang_test(self, params, angles):
        nozzle_dia = params['nozzle_dia']
        filament_dia = params['filament_dia']
        layer_height = 0.28
        line_width = nozzle_dia * 1.2
        total_layers = 50  # ~14mm
        base_layers = 10
        section_width = 20.0
        margin = 40.0
        lines = ['; Overhang Test - walls at increasing overhang angles']
        e_total = 0.0
        lines.append('G92 E0')
        seg_e = self._calc_extrusion(section_width, line_width,
                                      layer_height, filament_dia)
        for layer in range(total_layers):
            z = (layer + 1) * layer_height
            lines.append('G1 Z%.3f F600' % z)
            for a_idx, angle_deg in enumerate(angles):
                y_base = margin + a_idx * section_width
                wall_x = margin
                if layer >= base_layers:
                    angle_rad = math.radians(angle_deg)
                    overhang_layers = layer - base_layers
                    x_offset = overhang_layers * layer_height / math.tan(
                        angle_rad)
                    wall_x = margin - x_offset
                if layer == base_layers:
                    lines.append('; Overhang %d°' % angle_deg)
                # Overhang wall
                lines.append('G1 X%.1f Y%.1f F3000' % (wall_x, y_base))
                e_total += seg_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (wall_x, y_base + section_width, e_total))
                # Reference wall (vertical)
                lines.append('G1 X%.1f Y%.1f F3000' % (margin, y_base))
                e_total += seg_e
                lines.append('G1 X%.1f Y%.1f E%.4f F1500'
                             % (margin, y_base + section_width, e_total))
        return lines
    def _generate_epilogue(self):
        return [
            '; Epilogue',
            'G92 E0',
            'G1 E-2.0 F3600 ; retract',
            'G91',
            'G1 Z10 F600 ; lift',
            'G90',
            'TURN_OFF_HEATERS',
            'M107 ; fan off',
            'M84 ; motors off',
        ]
    def _run_test(self, gcmd, test_type, gcode_lines, analyze, test_info):
        if self.running:
            raise gcmd.error("A test is already in progress")
        self.running = True
        try:
            gcode_text = '\n'.join(gcode_lines)
            logging.info("ai_print_tests: Running %s test (%d lines)",
                         test_type, len(gcode_lines))
            self.gcode.respond_info("Starting %s calibration test..." %
                                    test_type)
            self.gcode.run_script_from_command(gcode_text)
            self.gcode.respond_info("%s test complete." % test_type)
            if analyze:
                self._analyze_test(gcmd, test_type, test_info)
        finally:
            self.running = False
    def _analyze_test(self, gcmd, test_type, test_info):
        if self.ai_camera is None:
            self.gcode.respond_info(
                "AI camera not configured — skipping analysis. "
                "Add [ai_camera] to your config to enable.")
            return
        if self.ai_backend is None:
            self.gcode.respond_info(
                "AI backend not available — skipping analysis.")
            return
        self.gcode.respond_info("Capturing image for analysis...")
        try:
            image_path = self.ai_camera.camera.capture()
        except Exception as e:
            self.gcode.respond_info(
                "Camera capture failed: %s — skipping analysis." % str(e))
            return
        prompt_key = 'test_%s' % test_type
        try:
            prompt = self.prompt_manager.get_prompt(prompt_key,
                                                    *test_info)
        except (ValueError, TypeError) as e:
            self.gcode.respond_info(
                "Prompt error: %s — skipping analysis." % str(e))
            return
        self.gcode.respond_info("Analyzing %s test results..." % test_type)
        try:
            response = self.ai_backend.query(prompt, images=[image_path])
        except self.printer.command_error as e:
            self.gcode.respond_info("AI analysis failed: %s" % str(e))
            return
        result = self._parse_response(response)
        self.gcode.respond_info(
            "AI Test Analysis:\n"
            "  Confidence: %.0f%%\n"
            "  Status: %s\n"
            "  Findings: %s\n"
            "  Recommendation: %s"
            % (result['confidence'] * 100, result['status'],
               result['findings'], result['recommendation']))
        if result['changes']:
            self._propose_fixes(gcmd, result['changes'])
    def _propose_fixes(self, gcmd, changes):
        configfile = self.printer.lookup_object('configfile')
        applied = []
        for section, option, value in changes:
            configfile.set(section, option, value)
            logging.info("ai_print_tests: staged [%s] %s = %s",
                         section, option, value)
            applied.append("  [%s] %s = %s" % (section, option, value))
        self.gcode.respond_info(
            "AI proposed %d config change(s):\n%s\n"
            "Run SAVE_CONFIG to persist."
            % (len(applied), '\n'.join(applied)))
    def _parse_response(self, response):
        result = {
            'confidence': 0.0,
            'status': 'UNCERTAIN',
            'findings': '',
            'recommendation': '',
            'changes': [],
        }
        change_re = re.compile(
            r'^CHANGE:\s*\[([^\]]+)\]\s*(\S+)\s*=\s*(.+)$')
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
            else:
                m = change_re.match(line)
                if m:
                    result['changes'].append(
                        (m.group(1).strip(), m.group(2).strip(),
                         m.group(3).strip()))
        return result
    def get_status(self, eventtime):
        return {
            'running': self.running,
            'available': self.ai_backend is not None,
            'camera_available': self.ai_camera is not None,
        }
    # G-code commands
    cmd_AI_TEST_FIRST_LAYER_help = "Print first layer calibration test"
    def cmd_AI_TEST_FIRST_LAYER(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        params = self._get_printer_params()
        probe = self.printer.lookup_object('probe', None)
        z_offset = '%.3f' % probe.get_offsets()[2] if probe else 'unknown'
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_first_layer_test(params)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'first_layer', gcode_lines, analyze,
                       (z_offset,))
    cmd_AI_TEST_FLOW_help = "Print flow/extrusion calibration test"
    def cmd_AI_TEST_FLOW(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        start = gcmd.get_float('START', 0.9)
        end = gcmd.get_float('END', 1.1)
        steps = gcmd.get_int('STEPS', 5)
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_flow_test(params, start, end, steps)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'flow', gcode_lines, analyze,
                       ('%.0f' % (start * 100), '%.0f' % (end * 100),
                        str(steps)))
    cmd_AI_TEST_PA_help = "Print pressure advance calibration test"
    def cmd_AI_TEST_PA(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        start = gcmd.get_float('START', 0.0)
        end = gcmd.get_float('END', 0.1)
        steps = gcmd.get_int('STEPS', 10)
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_pa_test(params, start, end, steps)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'pa', gcode_lines, analyze,
                       (str(start), str(end), str(steps)))
    cmd_AI_TEST_SPEED_help = "Print speed calibration test"
    def cmd_AI_TEST_SPEED(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        start = gcmd.get_float('START', 50.)
        end = gcmd.get_float('END', 200.)
        steps = gcmd.get_int('STEPS', 6)
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_speed_test(params, start, end, steps)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'speed', gcode_lines, analyze,
                       (str(int(start)), str(int(end)), str(steps)))
    cmd_AI_TEST_TEMP_help = "Print temperature tower calibration test"
    def cmd_AI_TEST_TEMP(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        start_temp = gcmd.get_int('START_TEMP', 190)
        end_temp = gcmd.get_int('END_TEMP', 230)
        step = gcmd.get_int('STEP', 5)
        analyze = gcmd.get_int('ANALYZE', 0)
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, start_temp, params)
                       + self._generate_temp_tower(params, start_temp,
                                                   end_temp, step)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'temp_tower', gcode_lines, analyze,
                       (str(start_temp), str(end_temp), str(step)))
    cmd_AI_TEST_RETRACTION_help = "Print retraction calibration test"
    def cmd_AI_TEST_RETRACTION(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        start = gcmd.get_float('START', 0.2)
        end = gcmd.get_float('END', 2.0)
        steps = gcmd.get_int('STEPS', 5)
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_retraction_test(params, start,
                                                        end, steps)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'retraction', gcode_lines, analyze,
                       (str(start), str(end), str(steps)))
    cmd_AI_TEST_BRIDGING_help = "Print bridging calibration test"
    def cmd_AI_TEST_BRIDGING(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        spans_str = gcmd.get('SPANS', '20,40,60,80')
        spans = [float(s.strip()) for s in spans_str.split(',')]
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_bridging_test(params, spans)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'bridging', gcode_lines, analyze,
                       (spans_str,))
    cmd_AI_TEST_OVERHANG_help = "Print overhang calibration test"
    def cmd_AI_TEST_OVERHANG(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bed_temp = gcmd.get_int('BED_TEMP', 60)
        extruder_temp = gcmd.get_int('EXTRUDER_TEMP', 200)
        analyze = gcmd.get_int('ANALYZE', 0)
        angles_str = gcmd.get('ANGLES', '15,30,45,60,75')
        angles = [int(a.strip()) for a in angles_str.split(',')]
        params = self._get_printer_params()
        gcode_lines = (self._generate_preamble(bed_temp, extruder_temp, params)
                       + self._generate_overhang_test(params, angles)
                       + self._generate_epilogue())
        self._run_test(gcmd, 'overhang', gcode_lines, analyze,
                       (angles_str,))
    # Webhook handlers
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))
    def _handle_run_request(self, web_request):
        test_type = web_request.get_str('type')
        valid_types = ('first_layer', 'flow', 'pa', 'speed',
                       'temp', 'retraction', 'bridging', 'overhang')
        if test_type not in valid_types:
            raise web_request.error(
                "Invalid test type '%s'. Must be one of: %s"
                % (test_type, ', '.join(valid_types)))
        if self.running:
            raise web_request.error("A test is already in progress")
        # Build params from web request
        bed_temp = web_request.get_int('bed_temp', 60)
        extruder_temp = web_request.get_int('extruder_temp', 200)
        analyze = web_request.get_int('analyze', 0)
        # Build the G-code command string and run via gcode
        cmd_parts = ['AI_TEST_%s' % test_type.upper(),
                     'BED_TEMP=%d' % bed_temp,
                     'ANALYZE=%d' % analyze]
        if test_type != 'temp':
            cmd_parts.append('EXTRUDER_TEMP=%d' % extruder_temp)
        if test_type in ('flow', 'pa', 'speed', 'retraction'):
            start = web_request.get_float('start', None)
            end = web_request.get_float('end', None)
            steps = web_request.get_int('steps', None)
            if start is not None:
                cmd_parts.append('START=%.4f' % start)
            if end is not None:
                cmd_parts.append('END=%.4f' % end)
            if steps is not None:
                cmd_parts.append('STEPS=%d' % steps)
        if test_type == 'temp':
            start_temp = web_request.get_int('start_temp', None)
            end_temp = web_request.get_int('end_temp', None)
            step = web_request.get_int('step', None)
            if start_temp is not None:
                cmd_parts.append('START_TEMP=%d' % start_temp)
            if end_temp is not None:
                cmd_parts.append('END_TEMP=%d' % end_temp)
            if step is not None:
                cmd_parts.append('STEP=%d' % step)
        if test_type == 'bridging':
            spans = web_request.get_str('spans', None)
            if spans is not None:
                cmd_parts.append('SPANS=%s' % spans)
        if test_type == 'overhang':
            angles = web_request.get_str('angles', None)
            if angles is not None:
                cmd_parts.append('ANGLES=%s' % angles)
        cmd = ' '.join(cmd_parts)
        try:
            self.gcode.run_script_from_command(cmd)
            web_request.send({'status': 'complete', 'test_type': test_type})
        except self.printer.command_error as e:
            raise web_request.error(str(e))

def load_config(config):
    return AIPrintTests(config)
