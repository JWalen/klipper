# AI Filament Profiles - Per-filament settings with AI suggestions
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os

try:
    import json
except ImportError:
    import simplejson as json


class AIFilamentProfiles:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        self.profiles_file = os.path.expanduser(
            config.get('profiles_file',
                        '~/printer_data/config/filament_profiles.json'))
        self.active_profile_name = config.get('active_profile', '')
        self.profiles = {}
        self._load_profiles()
        # Register ready handler
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_FILAMENT_SET', self.cmd_AI_FILAMENT_SET,
            desc=self.cmd_AI_FILAMENT_SET_help)
        self.gcode.register_command(
            'AI_FILAMENT_LOAD', self.cmd_AI_FILAMENT_LOAD,
            desc=self.cmd_AI_FILAMENT_LOAD_help)
        self.gcode.register_command(
            'AI_FILAMENT_SAVE', self.cmd_AI_FILAMENT_SAVE,
            desc=self.cmd_AI_FILAMENT_SAVE_help)
        self.gcode.register_command(
            'AI_FILAMENT_LIST', self.cmd_AI_FILAMENT_LIST,
            desc=self.cmd_AI_FILAMENT_LIST_help)
        self.gcode.register_command(
            'AI_FILAMENT_SUGGEST', self.cmd_AI_FILAMENT_SUGGEST,
            desc=self.cmd_AI_FILAMENT_SUGGEST_help)
        self.gcode.register_command(
            'AI_FILAMENT_DELETE', self.cmd_AI_FILAMENT_DELETE,
            desc=self.cmd_AI_FILAMENT_DELETE_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_filament_profiles/list',
                                   self._handle_list_request)
        webhooks.register_endpoint('ai_filament_profiles/get',
                                   self._handle_get_request)
        webhooks.register_endpoint('ai_filament_profiles/set',
                                   self._handle_set_request)
        webhooks.register_endpoint('ai_filament_profiles/suggest',
                                   self._handle_suggest_request)
        webhooks.register_endpoint('ai_filament_profiles/status',
                                   self._handle_status_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _load_profiles(self):
        if os.path.isfile(self.profiles_file):
            try:
                with open(self.profiles_file, 'r') as f:
                    self.profiles = json.load(f)
                logging.info("ai_filament_profiles: loaded %d profiles",
                             len(self.profiles))
            except Exception as e:
                logging.warning("ai_filament_profiles: failed to load "
                                "profiles: %s", str(e))
                self.profiles = {}
    def _save_profiles(self):
        try:
            dir_path = os.path.dirname(self.profiles_file)
            if dir_path and not os.path.isdir(dir_path):
                os.makedirs(dir_path)
            with open(self.profiles_file, 'w') as f:
                json.dump(self.profiles, f, indent=2)
            logging.info("ai_filament_profiles: saved %d profiles",
                         len(self.profiles))
        except Exception as e:
            logging.warning("ai_filament_profiles: failed to save "
                            "profiles: %s", str(e))
    def _get_config_text(self):
        configfile = self.printer.lookup_object('configfile')
        config = configfile.get_status(self.reactor.monotonic())
        raw = config.get('config', {})
        lines = []
        for section in sorted(raw.keys()):
            if section in ('extruder', 'heater_bed', 'firmware_retraction',
                           'printer', 'fan'):
                lines.append('[%s]' % section)
                for key, val in sorted(raw[section].items()):
                    lines.append('%s: %s' % (key, val))
                lines.append('')
        return '\n'.join(lines)
    def get_status(self, eventtime):
        return {
            'active_profile': self.active_profile_name,
            'profile_count': len(self.profiles),
            'profiles': list(self.profiles.keys()),
            'available': self.ai_backend is not None,
        }
    # G-code commands
    cmd_AI_FILAMENT_SET_help = "Create or update a filament profile"
    def cmd_AI_FILAMENT_SET(self, gcmd):
        name = gcmd.get('NAME')
        profile = self.profiles.get(name, {})
        profile['type'] = gcmd.get('TYPE', profile.get('type', ''))
        profile['brand'] = gcmd.get('BRAND', profile.get('brand', ''))
        profile['extruder_temp'] = gcmd.get_int(
            'EXTRUDER_TEMP', profile.get('extruder_temp', 200))
        profile['bed_temp'] = gcmd.get_int(
            'BED_TEMP', profile.get('bed_temp', 60))
        profile['pressure_advance'] = gcmd.get_float(
            'PA', profile.get('pressure_advance', 0.0))
        profile['retract_length'] = gcmd.get_float(
            'RETRACT', profile.get('retract_length', 0.9))
        profile['retract_speed'] = gcmd.get_float(
            'RETRACT_SPEED', profile.get('retract_speed', 35.0))
        profile['max_speed'] = gcmd.get_float(
            'MAX_SPEED', profile.get('max_speed', 150.0))
        profile['fan_speed'] = gcmd.get_int(
            'FAN_SPEED', profile.get('fan_speed', 100))
        profile['notes'] = gcmd.get('NOTES', profile.get('notes', ''))
        self.profiles[name] = profile
        self._save_profiles()
        logging.info("ai_filament_profiles: saved profile '%s'", name)
        self.gcode.respond_info("Filament profile '%s' saved." % name)
    cmd_AI_FILAMENT_LOAD_help = "Load a filament profile and apply settings"
    def cmd_AI_FILAMENT_LOAD(self, gcmd):
        name = gcmd.get('NAME')
        if name not in self.profiles:
            raise gcmd.error("Profile '%s' not found" % name)
        profile = self.profiles[name]
        self.active_profile_name = name
        # Apply pressure advance
        pa = profile.get('pressure_advance', 0.0)
        self.gcode.run_script_from_command(
            'SET_PRESSURE_ADVANCE ADVANCE=%.4f' % pa)
        # Apply retraction settings
        retract = profile.get('retract_length', 0.9)
        retract_speed = profile.get('retract_speed', 35.0)
        try:
            self.gcode.run_script_from_command(
                'SET_RETRACTION RETRACT_LENGTH=%.3f RETRACT_SPEED=%.1f'
                % (retract, retract_speed))
        except self.printer.command_error:
            pass  # firmware_retraction may not be configured
        logging.info("ai_filament_profiles: loaded profile '%s'", name)
        self.gcode.respond_info(
            "Loaded filament profile '%s':\n"
            "  Type: %s, Brand: %s\n"
            "  Temps: E=%d°C B=%d°C\n"
            "  PA: %.4f, Retract: %.2fmm @ %.0fmm/s\n"
            "  Max Speed: %.0fmm/s, Fan: %d%%"
            % (name, profile.get('type', ''), profile.get('brand', ''),
               profile.get('extruder_temp', 200),
               profile.get('bed_temp', 60), pa, retract, retract_speed,
               profile.get('max_speed', 150),
               profile.get('fan_speed', 100)))
    cmd_AI_FILAMENT_SAVE_help = "Save current settings as a filament profile"
    def cmd_AI_FILAMENT_SAVE(self, gcmd):
        name = gcmd.get('NAME')
        # Read current live settings
        extruder = self.printer.lookup_object('extruder')
        pa = extruder.get_status(self.reactor.monotonic()).get(
            'pressure_advance', 0.0)
        profile = self.profiles.get(name, {})
        profile['pressure_advance'] = pa
        profile['type'] = gcmd.get('TYPE', profile.get('type', ''))
        profile['brand'] = gcmd.get('BRAND', profile.get('brand', ''))
        # Try to get retraction settings
        fw_retract = self.printer.lookup_object('firmware_retraction', None)
        if fw_retract is not None:
            fr_status = fw_retract.get_status(self.reactor.monotonic())
            profile['retract_length'] = fr_status.get('retract_length', 0.9)
            profile['retract_speed'] = fr_status.get('retract_speed', 35.0)
        # Get heater targets
        heater_bed = self.printer.lookup_object('heater_bed', None)
        if heater_bed is not None:
            bed_status = heater_bed.get_status(self.reactor.monotonic())
            target = bed_status.get('target', 0.0)
            if target > 0:
                profile['bed_temp'] = int(target)
        ext_status = extruder.get_status(self.reactor.monotonic())
        ext_target = ext_status.get('target', 0.0)
        if ext_target > 0:
            profile['extruder_temp'] = int(ext_target)
        self.profiles[name] = profile
        self._save_profiles()
        self.gcode.respond_info(
            "Saved current settings as profile '%s' (PA=%.4f)"
            % (name, pa))
    cmd_AI_FILAMENT_LIST_help = "List all filament profiles"
    def cmd_AI_FILAMENT_LIST(self, gcmd):
        if not self.profiles:
            self.gcode.respond_info("No filament profiles saved.")
            return
        lines = ["Filament Profiles (%d):" % len(self.profiles)]
        for name, profile in sorted(self.profiles.items()):
            active = " [ACTIVE]" if name == self.active_profile_name else ""
            lines.append(
                "  %s%s: %s %s, E=%d°C B=%d°C, PA=%.4f"
                % (name, active,
                   profile.get('type', ''), profile.get('brand', ''),
                   profile.get('extruder_temp', 0),
                   profile.get('bed_temp', 0),
                   profile.get('pressure_advance', 0.0)))
        self.gcode.respond_info('\n'.join(lines))
    cmd_AI_FILAMENT_SUGGEST_help = "AI suggests settings for a filament"
    def cmd_AI_FILAMENT_SUGGEST(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        filament_type = gcmd.get('TYPE', 'PLA')
        brand = gcmd.get('BRAND', 'Generic')
        extruder = self.printer.lookup_object('extruder')
        nozzle_dia = extruder.nozzle_diameter
        config_text = self._get_config_text()
        prompt = self.prompt_manager.get_prompt(
            'filament_suggest', filament_type, brand,
            '%.1f' % nozzle_dia, config_text)
        self.gcode.respond_info(
            "Asking AI for %s %s settings..." % (brand, filament_type))
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise gcmd.error("AI query failed: %s" % str(e))
        result = self._parse_suggest_response(response)
        lines = ["AI Suggested Settings for %s %s:" % (brand, filament_type)]
        for key, val in sorted(result.items()):
            if key != 'recommendation':
                lines.append("  %s: %s" % (key, val))
        if result.get('recommendation'):
            lines.append("  Notes: %s" % result['recommendation'])
        self.gcode.respond_info('\n'.join(lines))
    cmd_AI_FILAMENT_DELETE_help = "Delete a filament profile"
    def cmd_AI_FILAMENT_DELETE(self, gcmd):
        name = gcmd.get('NAME')
        if name not in self.profiles:
            raise gcmd.error("Profile '%s' not found" % name)
        del self.profiles[name]
        self._save_profiles()
        if self.active_profile_name == name:
            self.active_profile_name = ''
        self.gcode.respond_info("Deleted filament profile '%s'" % name)
    def _parse_suggest_response(self, response):
        result = {}
        for line in response.split('\n'):
            line = line.strip()
            for key in ('CONFIDENCE', 'EXTRUDER_TEMP', 'BED_TEMP',
                        'PRESSURE_ADVANCE', 'RETRACT_LENGTH',
                        'RETRACT_SPEED', 'MAX_SPEED', 'FAN_SPEED',
                        'RECOMMENDATION'):
                if line.startswith(key + ':'):
                    result[key.lower()] = line.split(':', 1)[1].strip()
                    break
        return result
    # Webhook handlers
    def _handle_list_request(self, web_request):
        web_request.send({'profiles': self.profiles,
                          'active': self.active_profile_name})
    def _handle_get_request(self, web_request):
        name = web_request.get_str('name')
        if name not in self.profiles:
            raise web_request.error("Profile '%s' not found" % name)
        web_request.send(self.profiles[name])
    def _handle_set_request(self, web_request):
        name = web_request.get_str('name')
        profile = {}
        for key in ('type', 'brand', 'extruder_temp', 'bed_temp',
                     'pressure_advance', 'retract_length', 'retract_speed',
                     'max_speed', 'fan_speed', 'notes'):
            val = web_request.get_str(key, None)
            if val is not None:
                profile[key] = val
        self.profiles[name] = profile
        self._save_profiles()
        web_request.send({'saved': name})
    def _handle_suggest_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        filament_type = web_request.get_str('type', 'PLA')
        brand = web_request.get_str('brand', 'Generic')
        extruder = self.printer.lookup_object('extruder')
        nozzle_dia = extruder.nozzle_diameter
        config_text = self._get_config_text()
        prompt = self.prompt_manager.get_prompt(
            'filament_suggest', filament_type, brand,
            '%.1f' % nozzle_dia, config_text)
        try:
            response = self.ai_backend.query(prompt)
            result = self._parse_suggest_response(response)
            web_request.send(result)
        except self.printer.command_error as e:
            raise web_request.error(str(e))
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))

def load_config(config):
    return AIFilamentProfiles(config)
