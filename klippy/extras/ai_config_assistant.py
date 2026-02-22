# AI Config Assistant - AI-powered printer configuration analysis
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, re


class AIConfigAssistant:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_backend = None
        self.prompt_manager = None
        # Register ready handler to look up ai_backend
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register commands
        self.gcode.register_command(
            'AI_CONFIG_CHECK', self.cmd_AI_CONFIG_CHECK,
            desc=self.cmd_AI_CONFIG_CHECK_help)
        self.gcode.register_command(
            'AI_CONFIG_SUGGEST', self.cmd_AI_CONFIG_SUGGEST,
            desc=self.cmd_AI_CONFIG_SUGGEST_help)
        self.gcode.register_command(
            'AI_ASK', self.cmd_AI_ASK,
            desc=self.cmd_AI_ASK_help)
        self.gcode.register_command(
            'AI_CONFIG_FIX', self.cmd_AI_CONFIG_FIX,
            desc=self.cmd_AI_CONFIG_FIX_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_config_assistant/check',
                                   self._handle_check_request)
        webhooks.register_endpoint('ai_config_assistant/suggest',
                                   self._handle_suggest_request)
        webhooks.register_endpoint('ai_config_assistant/ask',
                                   self._handle_ask_request)
        webhooks.register_endpoint('ai_config_assistant/fix',
                                   self._handle_fix_request)
    def _handle_ready(self):
        self.ai_backend = self.printer.lookup_object('ai_backend')
        self.prompt_manager = self.ai_backend.get_prompt_manager()
    def _get_config_text(self, section=None):
        configfile = self.printer.lookup_object('configfile')
        config_status = configfile.get_status(self.reactor.monotonic())
        raw_config = config_status.get('config', {})
        lines = []
        for sec_name, sec_data in sorted(raw_config.items()):
            if section and sec_name.lower() != section.lower():
                continue
            lines.append('[%s]' % (sec_name,))
            if isinstance(sec_data, dict):
                for key, value in sorted(sec_data.items()):
                    lines.append('%s: %s' % (key, value))
            lines.append('')
        return '\n'.join(lines)
    def get_status(self, eventtime):
        return {
            'available': self.ai_backend is not None,
        }
    # G-code commands
    cmd_AI_CONFIG_CHECK_help = "Analyze printer config for issues"
    def cmd_AI_CONFIG_CHECK(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        section = gcmd.get('SECTION', None)
        config_text = self._get_config_text(section)
        if not config_text.strip():
            if section:
                raise gcmd.error("Section '%s' not found in config"
                                 % (section,))
            raise gcmd.error("No config data available")
        self.gcode.respond_info("Analyzing configuration...")
        prompt = self.prompt_manager.get_prompt('config_check', config_text)
        try:
            response = self.ai_backend.query(prompt)
            self.gcode.respond_info("Config Analysis:\n%s" % (response,))
        except self.printer.command_error as e:
            raise gcmd.error("Config check failed: %s" % (str(e),))
    cmd_AI_CONFIG_SUGGEST_help = "Get AI suggestions for config improvements"
    def cmd_AI_CONFIG_SUGGEST(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        focus = gcmd.get('FOCUS', 'general optimization')
        config_text = self._get_config_text()
        if not config_text.strip():
            raise gcmd.error("No config data available")
        self.gcode.respond_info("Generating suggestions for: %s..."
                                % (focus,))
        prompt = self.prompt_manager.get_prompt('config_suggest',
                                                focus, config_text)
        try:
            response = self.ai_backend.query(prompt)
            self.gcode.respond_info("Config Suggestions (%s):\n%s"
                                    % (focus, response))
        except self.printer.command_error as e:
            raise gcmd.error("Config suggest failed: %s" % (str(e),))
    cmd_AI_ASK_help = "Ask AI a question about your printer config"
    def cmd_AI_ASK(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        question = gcmd.get('QUESTION')
        config_text = self._get_config_text()
        if not config_text.strip():
            raise gcmd.error("No config data available")
        self.gcode.respond_info("Asking AI: %s" % (question,))
        prompt = self.prompt_manager.get_prompt('config_ask',
                                                question, config_text)
        try:
            response = self.ai_backend.query(prompt)
            self.gcode.respond_info("AI Answer:\n%s" % (response,))
        except self.printer.command_error as e:
            raise gcmd.error("AI ask failed: %s" % (str(e),))
    cmd_AI_CONFIG_FIX_help = "AI-proposed config fixes (staged for SAVE_CONFIG)"
    def cmd_AI_CONFIG_FIX(self, gcmd):
        if self.ai_backend is None:
            raise gcmd.error("AI backend not available")
        section = gcmd.get('SECTION', None)
        config_text = self._get_config_text(section)
        if not config_text.strip():
            if section:
                raise gcmd.error("Section '%s' not found in config"
                                 % (section,))
            raise gcmd.error("No config data available")
        self.gcode.respond_info("Analyzing configuration for fixes...")
        prompt = self.prompt_manager.get_prompt('config_fix', config_text)
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise gcmd.error("Config fix failed: %s" % (str(e),))
        changes, reason = self._parse_fix_response(response)
        if not changes:
            self.gcode.respond_info(
                "AI Config Fix: No changes proposed.\n%s" % (reason,))
            return
        self._apply_changes(changes)
        msg_lines = ["AI Config Fix — %d change(s) staged:" % (len(changes),)]
        for section_name, option, value in changes:
            msg_lines.append("  [%s] %s = %s" % (section_name, option, value))
        msg_lines.append("Reason: %s" % (reason,))
        msg_lines.append("Run SAVE_CONFIG to persist these changes.")
        self.gcode.respond_info('\n'.join(msg_lines))
    def _parse_fix_response(self, response):
        changes = []
        reason = ''
        change_re = re.compile(
            r'^CHANGE:\s*\[([^\]]+)\]\s*(\S+)\s*=\s*(.+)$')
        for line in response.split('\n'):
            line = line.strip()
            m = change_re.match(line)
            if m:
                changes.append((m.group(1).strip(), m.group(2).strip(),
                                m.group(3).strip()))
            elif line.upper().startswith('REASON:'):
                reason = line[len('REASON:'):].strip()
        return changes, reason
    def _apply_changes(self, changes):
        configfile = self.printer.lookup_object('configfile')
        for section_name, option, value in changes:
            configfile.set(section_name, option, value)
            logging.info("AI_CONFIG_FIX: staged [%s] %s = %s",
                         section_name, option, value)
    # Webhooks handlers
    def _handle_check_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        section = web_request.get_str('section', None)
        config_text = self._get_config_text(section)
        if not config_text.strip():
            raise web_request.error("No config data available")
        prompt = self.prompt_manager.get_prompt('config_check', config_text)
        try:
            response = self.ai_backend.query(prompt)
            web_request.send({'analysis': response})
        except self.printer.command_error as e:
            raise web_request.error(str(e))
    def _handle_suggest_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        focus = web_request.get_str('focus', 'general optimization')
        config_text = self._get_config_text()
        if not config_text.strip():
            raise web_request.error("No config data available")
        prompt = self.prompt_manager.get_prompt('config_suggest',
                                                focus, config_text)
        try:
            response = self.ai_backend.query(prompt)
            web_request.send({'suggestions': response})
        except self.printer.command_error as e:
            raise web_request.error(str(e))
    def _handle_ask_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        question = web_request.get_str('question')
        config_text = self._get_config_text()
        if not config_text.strip():
            raise web_request.error("No config data available")
        prompt = self.prompt_manager.get_prompt('config_ask',
                                                question, config_text)
        try:
            response = self.ai_backend.query(prompt)
            web_request.send({'answer': response})
        except self.printer.command_error as e:
            raise web_request.error(str(e))

    def _handle_fix_request(self, web_request):
        if self.ai_backend is None:
            raise web_request.error("AI backend not available")
        section = web_request.get_str('section', None)
        config_text = self._get_config_text(section)
        if not config_text.strip():
            raise web_request.error("No config data available")
        prompt = self.prompt_manager.get_prompt('config_fix', config_text)
        try:
            response = self.ai_backend.query(prompt)
        except self.printer.command_error as e:
            raise web_request.error(str(e))
        changes, reason = self._parse_fix_response(response)
        if not changes:
            web_request.send({'changes': [], 'reason': reason,
                              'applied': False})
            return
        self._apply_changes(changes)
        change_list = [{'section': s, 'option': o, 'value': v}
                       for s, o, v in changes]
        web_request.send({'changes': change_list, 'reason': reason,
                          'applied': True})

def load_config(config):
    return AIConfigAssistant(config)
