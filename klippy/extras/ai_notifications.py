# AI Notifications - Telegram/Discord notifications for print events
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os, threading

try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
except ImportError:
    from urllib2 import Request, urlopen, URLError, HTTPError

try:
    import json
except ImportError:
    import simplejson as json


class AINotifications:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.ai_camera = None
        # Notification targets
        self.telegram_token = config.get('telegram_bot_token', '')
        self.telegram_chat_id = config.get('telegram_chat_id', '')
        self.discord_webhook = config.get('discord_webhook_url', '')
        # Notification triggers
        self.notify_failure = config.getboolean('notify_on_failure', True)
        self.notify_completion = config.getboolean('notify_on_completion',
                                                    True)
        self.notify_first_layer = config.getboolean('notify_on_first_layer',
                                                     False)
        self.include_snapshot = config.getboolean('include_snapshot', True)
        # State
        self.notifications_sent = 0
        self.last_notification_time = 0.
        self.last_error = ''
        self._original_handle_result = None
        # Register events
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        # Register G-code commands
        self.gcode.register_command(
            'AI_NOTIFY_TEST', self.cmd_AI_NOTIFY_TEST,
            desc=self.cmd_AI_NOTIFY_TEST_help)
        self.gcode.register_command(
            'AI_NOTIFY', self.cmd_AI_NOTIFY,
            desc=self.cmd_AI_NOTIFY_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_notifications/status',
                                   self._handle_status_request)
        webhooks.register_endpoint('ai_notifications/send',
                                   self._handle_send_request)
    def _handle_ready(self):
        self.ai_camera = self.printer.lookup_object('ai_camera', None)
        # Hook into ai_camera failure detection
        if self.ai_camera is not None:
            self._original_handle_result = self.ai_camera._handle_result
            self.ai_camera._handle_result = self._wrapped_handle_result
    def _wrapped_handle_result(self, result, check_type):
        # Call original handler first
        if self._original_handle_result is not None:
            self._original_handle_result(result, check_type)
        # Check if we should notify
        status = result.get('status', '')
        confidence = result.get('confidence', 0.0)
        threshold = getattr(self.ai_camera, 'confidence_threshold', 0.7)
        if (check_type == 'failure' and self.notify_failure
                and status == 'FAILURE' and confidence >= threshold):
            self._send_notification('Print Failure Detected', result)
        elif check_type == 'completion' and self.notify_completion:
            self._send_notification('Print Complete', result)
        elif check_type == 'first_layer' and self.notify_first_layer:
            self._send_notification('First Layer Check', result)
    def _send_notification(self, title, result=None):
        if result is not None:
            message = (
                "%s\n"
                "Status: %s\n"
                "Confidence: %.0f%%\n"
                "Findings: %s\n"
                "Recommendation: %s"
                % (title, result.get('status', ''),
                   result.get('confidence', 0.0) * 100,
                   result.get('findings', ''),
                   result.get('recommendation', '')))
            image_path = result.get('image_path', '')
        else:
            message = title
            image_path = ''
        def thread_func():
            if self.telegram_token and self.telegram_chat_id:
                self._send_telegram(message, image_path)
            if self.discord_webhook:
                self._send_discord(message, image_path)
        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()
    def _send_telegram(self, message, image_path=''):
        base_url = 'https://api.telegram.org/bot%s' % self.telegram_token
        try:
            if (image_path and self.include_snapshot
                    and os.path.isfile(image_path)):
                boundary = '----KlipperBoundary'
                body = self._build_multipart(
                    boundary,
                    {'chat_id': self.telegram_chat_id,
                     'caption': message[:1024]},
                    {'photo': image_path})
                url = '%s/sendPhoto' % base_url
                req = Request(url, data=body)
                req.add_header(
                    'Content-Type',
                    'multipart/form-data; boundary=%s' % boundary)
            else:
                payload = json.dumps({
                    'chat_id': self.telegram_chat_id,
                    'text': message[:4096]})
                url = '%s/sendMessage' % base_url
                req = Request(url, data=payload.encode('utf-8'))
                req.add_header('Content-Type', 'application/json')
            urlopen(req, timeout=30)
            self.notifications_sent += 1
            self.last_notification_time = self.reactor.monotonic()
            logging.info("ai_notifications: Telegram message sent")
        except Exception as e:
            self.last_error = 'Telegram: %s' % str(e)
            logging.warning("ai_notifications: Telegram failed: %s", str(e))
    def _send_discord(self, message, image_path=''):
        try:
            if (image_path and self.include_snapshot
                    and os.path.isfile(image_path)):
                boundary = '----KlipperBoundary'
                payload_json = json.dumps({'content': message[:2000]})
                body = self._build_multipart(
                    boundary,
                    {'payload_json': payload_json},
                    {'file': image_path})
                req = Request(self.discord_webhook, data=body)
                req.add_header(
                    'Content-Type',
                    'multipart/form-data; boundary=%s' % boundary)
            else:
                payload = json.dumps({'content': message[:2000]})
                req = Request(self.discord_webhook,
                              data=payload.encode('utf-8'))
                req.add_header('Content-Type', 'application/json')
            urlopen(req, timeout=30)
            self.notifications_sent += 1
            self.last_notification_time = self.reactor.monotonic()
            logging.info("ai_notifications: Discord message sent")
        except Exception as e:
            self.last_error = 'Discord: %s' % str(e)
            logging.warning("ai_notifications: Discord failed: %s", str(e))
    def _build_multipart(self, boundary, fields, files):
        parts = []
        for name, value in fields.items():
            parts.append(('--%s' % boundary).encode('utf-8'))
            parts.append(
                ('Content-Disposition: form-data; name="%s"' % name)
                .encode('utf-8'))
            parts.append(b'')
            if isinstance(value, bytes):
                parts.append(value)
            else:
                parts.append(value.encode('utf-8'))
        for name, filepath in files.items():
            filename = os.path.basename(filepath)
            parts.append(('--%s' % boundary).encode('utf-8'))
            parts.append(
                ('Content-Disposition: form-data; name="%s"; '
                 'filename="%s"' % (name, filename)).encode('utf-8'))
            parts.append(b'Content-Type: image/jpeg')
            parts.append(b'')
            with open(filepath, 'rb') as f:
                parts.append(f.read())
        parts.append(('--%s--' % boundary).encode('utf-8'))
        return b'\r\n'.join(parts)
    def get_status(self, eventtime):
        return {
            'telegram_configured': bool(
                self.telegram_token and self.telegram_chat_id),
            'discord_configured': bool(self.discord_webhook),
            'notifications_sent': self.notifications_sent,
            'last_notification_time': self.last_notification_time,
            'last_error': self.last_error,
        }
    # G-code commands
    cmd_AI_NOTIFY_TEST_help = "Send a test notification"
    def cmd_AI_NOTIFY_TEST(self, gcmd):
        has_target = ((self.telegram_token and self.telegram_chat_id)
                      or self.discord_webhook)
        if not has_target:
            raise gcmd.error(
                "No notification targets configured. "
                "Set telegram_bot_token/telegram_chat_id or "
                "discord_webhook_url in [ai_notifications].")
        self.gcode.respond_info("Sending test notification...")
        self._send_notification("Klipper AI Test Notification - "
                                "Your notifications are working!")
        self.gcode.respond_info("Test notification sent.")
    cmd_AI_NOTIFY_help = "Send a custom notification"
    def cmd_AI_NOTIFY(self, gcmd):
        message = gcmd.get('MESSAGE', 'Klipper notification')
        self._send_notification(message)
        self.gcode.respond_info("Notification sent.")
    # Webhook handlers
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))
    def _handle_send_request(self, web_request):
        message = web_request.get_str('message', 'Klipper notification')
        self._send_notification(message)
        web_request.send({'sent': True})

def load_config(config):
    return AINotifications(config)
