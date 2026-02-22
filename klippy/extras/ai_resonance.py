# AI Resonance - ADXL resonance analysis and belt tension check
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os, re


class AIResonance:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.csv_dir = config.get('csv_dir', '/tmp')
        self.last_analysis = {}
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_RESONANCE_TEST', self.cmd_AI_RESONANCE_TEST,
            desc=self.cmd_AI_RESONANCE_TEST_help)
        self.gcode.register_command(
            'AI_BELT_CHECK', self.cmd_AI_BELT_CHECK,
            desc=self.cmd_AI_BELT_CHECK_help)
        self.gcode.register_command(
            'AI_RESONANCE_ANALYZE', self.cmd_AI_RESONANCE_ANALYZE,
            desc=self.cmd_AI_RESONANCE_ANALYZE_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_resonance/test',
                                   self._handle_test_request)
        webhooks.register_endpoint('ai_resonance/belt_check',
                                   self._handle_belt_request)
        webhooks.register_endpoint('ai_resonance/status',
                                   self._handle_status_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _find_newest_csv(self, axis):
        pattern = re.compile(r'resonances_%s_.*\.csv' % axis)
        newest = None
        newest_time = 0
        try:
            for fname in os.listdir(self.csv_dir):
                if pattern.match(fname):
                    fpath = os.path.join(self.csv_dir, fname)
                    mtime = os.path.getmtime(fpath)
                    if mtime > newest_time:
                        newest_time = mtime
                        newest = fpath
        except OSError:
            pass
        return newest
    def _parse_csv(self, csv_path):
        header = ''
        rows = []
        with open(csv_path, 'r') as f:
            header = f.readline().strip()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                try:
                    row = [float(p.strip()) for p in parts]
                    rows.append(row)
                except ValueError:
                    continue
        return header, rows
    def _summarize_data(self, header, rows):
        if not rows:
            return "No data available"
        freqs = [r[0] for r in rows]
        # Use last column as PSD sum (or second column if only 2)
        psd_col = -1
        psd = [r[psd_col] for r in rows]
        peak_mag = max(psd)
        peak_idx = psd.index(peak_mag)
        peak_freq = freqs[peak_idx]
        # Find significant peaks (>20% of max)
        threshold = peak_mag * 0.2
        peaks = []
        for i in range(1, len(psd) - 1):
            if psd[i] > threshold and psd[i] > psd[i - 1] and \
                    psd[i] > psd[i + 1]:
                peaks.append((freqs[i], psd[i]))
        summary = (
            "Primary peak: %.1f Hz (magnitude: %.3e)\n"
            "Significant peaks: %s\n"
            "Frequency range: %.1f - %.1f Hz\n"
            "Data points: %d"
            % (peak_freq, peak_mag,
               ', '.join(['%.1f Hz (%.3e)' % (f, m)
                          for f, m in peaks[:5]]),
               min(freqs), max(freqs), len(freqs)))
        return summary
    def _get_data_sample(self, rows, max_rows=20):
        sample = rows[:max_rows]
        lines = []
        for row in sample:
            lines.append(', '.join(['%.4f' % v for v in row]))
        return '\n'.join(lines)
    def _get_shaper_status(self, axis):
        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is None:
            return 'none', '0'
        status = input_shaper.get_status(self.reactor.monotonic())
        shaper_type = status.get('shaper_type_' + axis, 'none')
        shaper_freq = status.get('shaper_freq_' + axis, '0')
        return str(shaper_type), str(shaper_freq)
    def _analyze_resonance(self, gcmd, axis, csv_path):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        header, rows = self._parse_csv(csv_path)
        if not rows:
            raise gcmd.error("No data in CSV file: %s" % csv_path)
        summary = self._summarize_data(header, rows)
        data_sample = self._get_data_sample(rows)
        shaper_type, shaper_freq = self._get_shaper_status(axis)
        prompt = self.prompt_manager.get_prompt(
            'resonance_analyze', axis, shaper_type, shaper_freq,
            summary, header, data_sample, axis, axis)
        self.gcode.respond_info(
            "Analyzing %s-axis resonance data..." % axis)
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise gcmd.error("AI analysis failed: %s" % str(e))
        result = self._parse_response(response)
        self.last_analysis = result
        self.gcode.respond_info(
            "AI Resonance Analysis (%s-axis):\n"
            "  Current: %s @ %s Hz\n"
            "  Data: %s\n"
            "  Confidence: %.0f%%\n"
            "  Status: %s\n"
            "  Findings: %s\n"
            "  Recommendation: %s"
            % (axis, shaper_type, shaper_freq, summary.split('\n')[0],
               result['confidence'] * 100, result['status'],
               result['findings'], result['recommendation']))
        if result['changes']:
            self._propose_fixes(gcmd, result['changes'])
        return result
    def _propose_fixes(self, gcmd, changes):
        configfile = self.printer.lookup_object('configfile')
        applied = []
        for section, option, value in changes:
            configfile.set(section, option, value)
            logging.info("ai_resonance: staged [%s] %s = %s",
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
            'available': self.ai_backend is not None,
            'resonance_tester_available': (
                self.printer.lookup_object('resonance_tester', None)
                is not None),
            'last_analysis': self.last_analysis,
        }
    # G-code commands
    cmd_AI_RESONANCE_TEST_help = "Run resonance test with AI analysis"
    def cmd_AI_RESONANCE_TEST(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        res_tester = self.printer.lookup_object('resonance_tester', None)
        if res_tester is None:
            raise gcmd.error(
                "resonance_tester not configured. "
                "Add [resonance_tester] and an accelerometer to use this.")
        axis = gcmd.get('AXIS', 'x').lower()
        if axis not in ('x', 'y'):
            raise gcmd.error("AXIS must be 'x' or 'y'")
        self.gcode.respond_info(
            "Running %s-axis resonance test..." % axis)
        self.gcode.run_script_from_command(
            'TEST_RESONANCES AXIS=%s OUTPUT=resonances' % axis)
        csv_path = self._find_newest_csv(axis)
        if csv_path is None:
            raise gcmd.error("No resonance CSV found in %s" % self.csv_dir)
        self._analyze_resonance(gcmd, axis, csv_path)
    cmd_AI_BELT_CHECK_help = "AI checks belt tension via resonance"
    def cmd_AI_BELT_CHECK(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        res_tester = self.printer.lookup_object('resonance_tester', None)
        if res_tester is None:
            raise gcmd.error(
                "resonance_tester not configured. "
                "Add [resonance_tester] and an accelerometer to use this.")
        self.gcode.respond_info("Running X-axis resonance test...")
        self.gcode.run_script_from_command(
            'TEST_RESONANCES AXIS=x OUTPUT=resonances')
        x_csv = self._find_newest_csv('x')
        self.gcode.respond_info("Running Y-axis resonance test...")
        self.gcode.run_script_from_command(
            'TEST_RESONANCES AXIS=y OUTPUT=resonances')
        y_csv = self._find_newest_csv('y')
        if x_csv is None or y_csv is None:
            raise gcmd.error("Could not find resonance CSV files")
        x_header, x_rows = self._parse_csv(x_csv)
        y_header, y_rows = self._parse_csv(y_csv)
        x_summary = self._summarize_data(x_header, x_rows)
        y_summary = self._summarize_data(y_header, y_rows)
        prompt = self.prompt_manager.get_prompt('belt_check',
                                                 x_summary, y_summary)
        self.gcode.respond_info("Analyzing belt tension...")
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise gcmd.error("AI analysis failed: %s" % str(e))
        result = self._parse_response(response)
        self.last_analysis = result
        self.gcode.respond_info(
            "AI Belt Check:\n"
            "  X: %s\n"
            "  Y: %s\n"
            "  Confidence: %.0f%%\n"
            "  Status: %s\n"
            "  Findings: %s\n"
            "  Recommendation: %s"
            % (x_summary.split('\n')[0], y_summary.split('\n')[0],
               result['confidence'] * 100, result['status'],
               result['findings'], result['recommendation']))
    cmd_AI_RESONANCE_ANALYZE_help = "Analyze an existing resonance CSV"
    def cmd_AI_RESONANCE_ANALYZE(self, gcmd):
        csv_path = gcmd.get('FILE')
        if not os.path.isfile(csv_path):
            raise gcmd.error("File not found: %s" % csv_path)
        axis = gcmd.get('AXIS', 'x').lower()
        self._analyze_resonance(gcmd, axis, csv_path)
    # Webhook handlers
    def _handle_test_request(self, web_request):
        axis = web_request.get_str('axis', 'x').lower()
        if axis not in ('x', 'y'):
            raise web_request.error("axis must be 'x' or 'y'")
        try:
            self.gcode.run_script_from_command(
                'TEST_RESONANCES AXIS=%s OUTPUT=resonances' % axis)
            csv_path = self._find_newest_csv(axis)
            if csv_path is None:
                raise web_request.error("No CSV found")
            class WebGcmd:
                def error(self, msg):
                    raise Exception(msg)
            result = self._analyze_resonance(WebGcmd(), axis, csv_path)
            web_request.send(result)
        except Exception as e:
            raise web_request.error(str(e))
    def _handle_belt_request(self, web_request):
        try:
            class WebGcmd:
                def error(self, msg):
                    raise Exception(msg)
            self.cmd_AI_BELT_CHECK(WebGcmd())
            web_request.send(self.last_analysis)
        except Exception as e:
            raise web_request.error(str(e))
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))

def load_config(config):
    return AIResonance(config)
