# AI Print History - Log and analyze print/calibration history
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os, time

try:
    import json
except ImportError:
    import simplejson as json


class AIPrintHistory:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.history_file = os.path.expanduser(
            config.get('history_file',
                        '~/printer_data/config/print_history.json'))
        self.max_entries = config.getint('max_entries', 500, minval=10)
        self.auto_log = config.getboolean('auto_log', True)
        self.history = []
        self._load_history()
        self._was_printing = False
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Listen for print state changes
        self.printer.register_event_handler('idle_timeout:printing',
                                            self._handle_printing)
        self.printer.register_event_handler('idle_timeout:ready',
                                            self._handle_print_end)
        self.printer.register_event_handler('idle_timeout:idle',
                                            self._handle_print_end)
        # Register G-code commands
        self.gcode.register_command(
            'AI_HISTORY_SHOW', self.cmd_AI_HISTORY_SHOW,
            desc=self.cmd_AI_HISTORY_SHOW_help)
        self.gcode.register_command(
            'AI_HISTORY_TREND', self.cmd_AI_HISTORY_TREND,
            desc=self.cmd_AI_HISTORY_TREND_help)
        self.gcode.register_command(
            'AI_HISTORY_ADD', self.cmd_AI_HISTORY_ADD,
            desc=self.cmd_AI_HISTORY_ADD_help)
        self.gcode.register_command(
            'AI_HISTORY_CLEAR', self.cmd_AI_HISTORY_CLEAR,
            desc=self.cmd_AI_HISTORY_CLEAR_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_print_history/list',
                                   self._handle_list_request)
        webhooks.register_endpoint('ai_print_history/trend',
                                   self._handle_trend_request)
        webhooks.register_endpoint('ai_print_history/status',
                                   self._handle_status_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _load_history(self):
        if os.path.isfile(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.history = data.get('entries', [])
                logging.info("ai_print_history: loaded %d entries",
                             len(self.history))
            except Exception as e:
                logging.warning("ai_print_history: failed to load: %s",
                                str(e))
                self.history = []
    def _save_history(self):
        if len(self.history) > self.max_entries:
            self.history = self.history[-self.max_entries:]
        try:
            dir_path = os.path.dirname(self.history_file)
            if dir_path and not os.path.isdir(dir_path):
                os.makedirs(dir_path)
            with open(self.history_file, 'w') as f:
                json.dump({'entries': self.history}, f, indent=2)
        except Exception as e:
            logging.warning("ai_print_history: failed to save: %s", str(e))
    def _add_entry(self, entry):
        entry['timestamp'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        self.history.append(entry)
        self._save_history()
        logging.info("ai_print_history: added %s entry", entry.get('type'))
    def _handle_printing(self, print_time):
        self._was_printing = True
    def _handle_print_end(self, print_time):
        if not self._was_printing or not self.auto_log:
            return
        self._was_printing = False
        print_stats = self.printer.lookup_object('print_stats', None)
        if print_stats is None:
            return
        status = print_stats.get_status(self.reactor.monotonic())
        state = status.get('state', 'unknown')
        if state in ('complete', 'cancelled', 'error'):
            self._add_entry({
                'type': 'print_%s' % state,
                'filename': status.get('filename', ''),
                'duration': status.get('total_duration', 0.0),
                'print_duration': status.get('print_duration', 0.0),
                'filament_used': status.get('filament_used', 0.0),
                'result': state,
            })
    def _format_history(self, entries):
        lines = []
        for entry in reversed(entries):
            ts = entry.get('timestamp', 'unknown')
            etype = entry.get('type', 'unknown')
            if etype.startswith('print_'):
                lines.append(
                    "%s [%s] %s — %.0fs, %.1fmm filament"
                    % (ts, etype, entry.get('filename', ''),
                       entry.get('duration', 0.0),
                       entry.get('filament_used', 0.0)))
            elif etype == 'calibration_test':
                lines.append(
                    "%s [%s] %s — %s (%.0f%% confidence)"
                    % (ts, etype, entry.get('test_type', ''),
                       entry.get('ai_status', ''),
                       entry.get('ai_confidence', 0.0) * 100))
            elif etype == 'config_change':
                lines.append(
                    "%s [%s] [%s] %s = %s (from %s)"
                    % (ts, etype, entry.get('section', ''),
                       entry.get('option', ''),
                       entry.get('new_value', ''),
                       entry.get('source', '')))
            else:
                notes = entry.get('notes', '')
                lines.append("%s [%s] %s" % (ts, etype, notes))
        return '\n'.join(lines)
    def get_status(self, eventtime):
        return {
            'entry_count': len(self.history),
            'max_entries': self.max_entries,
            'auto_log': self.auto_log,
            'available': self.ai_backend is not None,
        }
    # G-code commands
    cmd_AI_HISTORY_SHOW_help = "Show recent print and calibration history"
    def cmd_AI_HISTORY_SHOW(self, gcmd):
        count = gcmd.get_int('COUNT', 10)
        type_filter = gcmd.get('TYPE', 'all')
        entries = self.history
        if type_filter != 'all':
            entries = [e for e in entries if e.get('type', '') == type_filter]
        entries = entries[-count:]
        if not entries:
            self.gcode.respond_info("No history entries found.")
            return
        text = self._format_history(entries)
        self.gcode.respond_info("Print History (%d entries):\n%s"
                                % (len(entries), text))
    cmd_AI_HISTORY_TREND_help = "AI analyzes calibration trends"
    def cmd_AI_HISTORY_TREND(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        count = gcmd.get_int('COUNT', 50)
        entries = self.history[-count:]
        if not entries:
            raise gcmd.error("No history entries to analyze")
        history_text = self._format_history(entries)
        prompt = self.prompt_manager.get_prompt('history_trend',
                                                 history_text)
        self.gcode.respond_info("Analyzing %d history entries..." % len(entries))
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise gcmd.error("AI analysis failed: %s" % str(e))
        result = self._parse_response(response)
        self.gcode.respond_info(
            "AI Trend Analysis:\n"
            "  Confidence: %.0f%%\n"
            "  Status: %s\n"
            "  Findings: %s\n"
            "  Recommendation: %s"
            % (result['confidence'] * 100, result['status'],
               result['findings'], result['recommendation']))
    cmd_AI_HISTORY_ADD_help = "Add a manual note to print history"
    def cmd_AI_HISTORY_ADD(self, gcmd):
        entry_type = gcmd.get('TYPE', 'note')
        notes = gcmd.get('NOTES', '')
        self._add_entry({'type': entry_type, 'notes': notes})
        self.gcode.respond_info("Added history entry: [%s] %s"
                                % (entry_type, notes))
    cmd_AI_HISTORY_CLEAR_help = "Clear all print history"
    def cmd_AI_HISTORY_CLEAR(self, gcmd):
        count = len(self.history)
        self.history = []
        self._save_history()
        self.gcode.respond_info("Cleared %d history entries." % count)
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
    # Webhook handlers
    def _handle_list_request(self, web_request):
        count = web_request.get_int('count', 50)
        entries = self.history[-count:]
        web_request.send({'entries': entries, 'total': len(self.history)})
    def _handle_trend_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        count = web_request.get_int('count', 50)
        entries = self.history[-count:]
        if not entries:
            raise web_request.error("No history entries to analyze")
        history_text = self._format_history(entries)
        prompt = self.prompt_manager.get_prompt('history_trend',
                                                 history_text)
        try:
            response = self.ai_backend.query(prompt)
            result = self._parse_response(response)
            web_request.send(result)
        except self.printer.command_error as e:
            raise web_request.error(str(e))
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))

def load_config(config):
    return AIPrintHistory(config)
