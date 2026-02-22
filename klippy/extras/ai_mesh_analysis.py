# AI Mesh Analysis - Interpret bed mesh data with AI
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging


class AIMeshAnalysis:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.last_analysis = {}
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_MESH_ANALYZE', self.cmd_AI_MESH_ANALYZE,
            desc=self.cmd_AI_MESH_ANALYZE_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_mesh_analysis/analyze',
                                   self._handle_analyze_request)
        webhooks.register_endpoint('ai_mesh_analysis/status',
                                   self._handle_status_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _compute_mesh_stats(self, probed_matrix, mesh_params):
        all_z = []
        for row in probed_matrix:
            all_z.extend(row)
        if not all_z:
            return None
        min_z = min(all_z)
        max_z = max(all_z)
        mean_z = sum(all_z) / len(all_z)
        variance = sum((z - mean_z) ** 2 for z in all_z) / len(all_z)
        std_z = variance ** 0.5
        z_range = max_z - min_z
        rows = len(probed_matrix)
        cols = len(probed_matrix[0]) if rows > 0 else 0
        corners = {}
        if rows > 0 and cols > 0:
            corners['front_left'] = probed_matrix[0][0]
            corners['front_right'] = probed_matrix[0][-1]
            corners['back_left'] = probed_matrix[-1][0]
            corners['back_right'] = probed_matrix[-1][-1]
            corners['center'] = probed_matrix[rows // 2][cols // 2]
        return {
            'min_z': min_z,
            'max_z': max_z,
            'mean_z': mean_z,
            'std_z': std_z,
            'range': z_range,
            'corners': corners,
            'rows': rows,
            'cols': cols,
        }
    def _format_matrix(self, probed_matrix):
        lines = []
        for i, row in enumerate(probed_matrix):
            vals = '  '.join(['%7.4f' % z for z in row])
            lines.append('Row %d: %s' % (i, vals))
        return '\n'.join(lines)
    def _analyze_mesh(self, gcmd):
        bed_mesh = self.printer.lookup_object('bed_mesh', None)
        if bed_mesh is None:
            raise gcmd.error("bed_mesh not configured")
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        bm_status = bed_mesh.get_status(self.reactor.monotonic())
        profiles = bm_status.get('profiles', {})
        profile_name = bm_status.get('profile_name', '')
        if not profile_name or profile_name not in profiles:
            # Try 'default' profile
            if 'default' in profiles:
                profile_name = 'default'
            elif profiles:
                profile_name = list(profiles.keys())[0]
            else:
                raise gcmd.error(
                    "No bed mesh profile available. "
                    "Run BED_MESH_CALIBRATE first.")
        profile = profiles[profile_name]
        probed_matrix = profile.get('points', [])
        if not probed_matrix:
            raise gcmd.error("Bed mesh profile has no probe data")
        mesh_params = profile.get('mesh_params', {})
        mesh_min_x = mesh_params.get('min_x', 0.0)
        mesh_min_y = mesh_params.get('min_y', 0.0)
        mesh_max_x = mesh_params.get('max_x', 0.0)
        mesh_max_y = mesh_params.get('max_y', 0.0)
        stats = self._compute_mesh_stats(probed_matrix, mesh_params)
        if stats is None:
            raise gcmd.error("Could not compute mesh statistics")
        matrix_text = self._format_matrix(probed_matrix)
        c = stats['corners']
        prompt = self.prompt_manager.get_prompt(
            'mesh_analyze',
            mesh_min_x, mesh_min_y, mesh_max_x, mesh_max_y,
            stats['cols'], stats['rows'],
            stats['min_z'], stats['max_z'], stats['range'],
            stats['mean_z'], stats['std_z'],
            c.get('front_left', 0.0), c.get('front_right', 0.0),
            c.get('back_left', 0.0), c.get('back_right', 0.0),
            c.get('center', 0.0),
            matrix_text)
        self.gcode.respond_info("Analyzing bed mesh data...")
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise gcmd.error("AI analysis failed: %s" % str(e))
        result = self._parse_response(response)
        self.last_analysis = result
        self.gcode.respond_info(
            "AI Mesh Analysis:\n"
            "  Z Range: %.4f to %.4fmm (deviation: %.4fmm)\n"
            "  Corners: FL=%.4f FR=%.4f BL=%.4f BR=%.4f C=%.4f\n"
            "  Confidence: %.0f%%\n"
            "  Status: %s\n"
            "  Findings: %s\n"
            "  Recommendation: %s"
            % (stats['min_z'], stats['max_z'], stats['range'],
               c.get('front_left', 0.0), c.get('front_right', 0.0),
               c.get('back_left', 0.0), c.get('back_right', 0.0),
               c.get('center', 0.0),
               result['confidence'] * 100, result['status'],
               result['findings'], result['recommendation']))
        logging.info("ai_mesh_analysis: completed analysis, status=%s",
                     result['status'])
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
    def get_status(self, eventtime):
        return {
            'available': self.ai_backend is not None,
            'last_analysis': self.last_analysis,
        }
    # G-code commands
    cmd_AI_MESH_ANALYZE_help = "AI analyzes bed mesh probe data"
    def cmd_AI_MESH_ANALYZE(self, gcmd):
        self._analyze_mesh(gcmd)
    # Webhook handlers
    def _handle_analyze_request(self, web_request):
        try:
            # Create a minimal gcmd-like wrapper for error raising
            class WebGcmd:
                def error(self, msg):
                    raise web_request.error(msg)
            result = self._analyze_mesh(WebGcmd())
            web_request.send(result)
        except Exception as e:
            raise web_request.error(str(e))
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))

def load_config(config):
    return AIMeshAnalysis(config)
