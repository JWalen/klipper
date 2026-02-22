# AI Backend - Pluggable AI provider for Klipper
#
# Copyright (C) 2025  Klipper Contributors
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, threading, time, base64, os

try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
except ImportError:
    from urllib2 import Request, urlopen, URLError, HTTPError

try:
    import json
except ImportError:
    import simplejson as json

PROMPT_TEMPLATES = {
    'config_check': (
        "You are a Klipper 3D printer firmware expert. Analyze the following "
        "Klipper printer configuration for issues, safety concerns, and "
        "potential problems. Focus on:\n"
        "- Unsafe settings that could damage the printer\n"
        "- Common misconfiguration mistakes\n"
        "- Missing recommended settings\n"
        "- Values that are out of normal range\n\n"
        "Configuration:\n%s"
    ),
    'config_suggest': (
        "You are a Klipper 3D printer firmware expert. Review the following "
        "Klipper printer configuration and suggest improvements. Focus on: "
        "%s\n\nConfiguration:\n%s"
    ),
    'config_ask': (
        "You are a Klipper 3D printer firmware expert. Answer the following "
        "question about the printer configuration below.\n\n"
        "Question: %s\n\nConfiguration:\n%s"
    ),
    'camera_failure': (
        "You are a 3D printing quality expert analyzing a print in progress. "
        "Examine this image for print failures including: spaghetti/stringing, "
        "layer shifting, warping/lifting, under-extrusion, blob formation, "
        "or detachment from the bed.\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description>\n"
        "RECOMMENDATION: <action>"
    ),
    'camera_first_layer': (
        "You are a 3D printing quality expert. Analyze this image of a first "
        "layer being printed. Check for: proper bed adhesion, consistent "
        "extrusion width, correct z-offset (too high/low), and any defects.\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description>\n"
        "RECOMMENDATION: <action>"
    ),
    'camera_completion': (
        "You are a 3D printing quality expert. Analyze this image of a "
        "completed 3D print. Check for: overall quality, surface finish, "
        "any visible defects, layer consistency, and structural integrity.\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description>\n"
        "RECOMMENDATION: <action>"
    ),
    'camera_general': (
        "You are a 3D printing quality expert. Analyze this image of a "
        "3D printer and describe what you see, including the state of the "
        "print, any issues, and general observations.\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description>\n"
        "RECOMMENDATION: <action>"
    ),
    'config_fix': (
        "You are a Klipper 3D printer firmware expert. Analyze the following "
        "Klipper printer configuration and propose specific fixes for any "
        "issues, safety concerns, or misconfigurations you find.\n\n"
        "You MUST return each proposed change on its own line in this exact "
        "format:\n"
        "CHANGE: [section_name] option_name = value\n\n"
        "After all CHANGE lines, add a single REASON line explaining why "
        "these changes were made:\n"
        "REASON: explanation\n\n"
        "If no changes are needed, respond with:\n"
        "REASON: No issues found, configuration looks correct.\n\n"
        "Only propose changes you are confident about. Do not propose "
        "changes that are merely stylistic preferences.\n\n"
        "Configuration:\n%s"
    ),
    'calibration_before': (
        "You are a Klipper 3D printer calibration expert. The user is about "
        "to run the calibration step: %s\n"
        "Command: %s\n\n"
        "Briefly explain:\n"
        "1. What this calibration step does\n"
        "2. What to watch for during calibration\n"
        "3. What a good result looks like\n\n"
        "Printer configuration:\n%s"
    ),
    'calibration_after': (
        "You are a Klipper 3D printer calibration expert. The user just "
        "completed the calibration step: %s\n"
        "Command: %s\n\n"
        "The output/result was:\n%s\n\n"
        "Interpret these results. Are they good? Should the step be re-run? "
        "Any concerns?"
    ),
    'test_first_layer': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "first layer calibration test — a grid of zigzag lines printed at "
        "0.28mm layer height.\n\n"
        "The printer's current probe z_offset is %s mm.\n\n"
        "Look for:\n"
        "- Lines too squished (z too low) or too rounded/not adhering (z too "
        "high)\n"
        "- Consistent width across the entire bed\n"
        "- Gaps between lines indicating poor adhesion\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description>\n"
        "RECOMMENDATION: <action>\n"
        "CHANGE: [probe] z_offset = <value>  (only if adjustment needed)"
    ),
    'test_flow': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "flow calibration test. Groups of 5 lines were printed at extrusion "
        "multipliers from %s%% to %s%% in %s steps.\n\n"
        "Look for:\n"
        "- Which group has the most consistent, smooth lines\n"
        "- Over-extrusion signs: lines bulging, ridges between lines\n"
        "- Under-extrusion signs: gaps, thin/transparent lines\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of best flow group and issues seen>\n"
        "RECOMMENDATION: <action>\n"
        "CHANGE: [extruder] rotation_distance = <value>  "
        "(only if adjustment needed)"
    ),
    'test_pa': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "pressure advance calibration test. Lines were printed with "
        "slow-fast-slow speed transitions at PA values from %s to %s in "
        "%s steps.\n\n"
        "Look for:\n"
        "- Which line has the smoothest corners at speed transitions\n"
        "- Bulging at corners (PA too low)\n"
        "- Gaps/thinning at corners (PA too high)\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of best PA line>\n"
        "RECOMMENDATION: <action>\n"
        "CHANGE: [extruder] pressure_advance = <value>  "
        "(only if adjustment needed)"
    ),
    'test_speed': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "speed calibration test. Lines were printed at speeds from %s to "
        "%s mm/s in %s steps.\n\n"
        "Look for:\n"
        "- At which speed lines start showing defects\n"
        "- Layer shifting or ringing at higher speeds\n"
        "- Under-extrusion at higher speeds\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of maximum safe speed>\n"
        "RECOMMENDATION: <recommended max speed>"
    ),
    'test_temp_tower': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "temperature tower test. Sections were printed at temperatures from "
        "%s to %s°C in %s°C steps (bottom to top).\n\n"
        "Look for:\n"
        "- Which section has the best surface quality and layer adhesion\n"
        "- Signs of too-hot: stringing, blobbing, glossy/warped surfaces\n"
        "- Signs of too-cold: poor layer adhesion, rough matte finish, "
        "delamination\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of optimal temperature section>\n"
        "RECOMMENDATION: <recommended temperature>"
    ),
    'test_retraction': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "retraction test. Columns were printed with retraction lengths from "
        "%s to %smm in %s steps (left to right).\n\n"
        "Look for:\n"
        "- Stringing/wisps between columns (retraction too short)\n"
        "- Clean travel moves (good retraction)\n"
        "- Blobbing or under-extrusion after retraction (too long)\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of optimal retraction column>\n"
        "RECOMMENDATION: <action>\n"
        "CHANGE: [firmware_retraction] retract_length = <value>  "
        "(only if adjustment needed)"
    ),
    'test_bridging': (
        "You are a 3D printing calibration expert. Analyze this image of a "
        "bridging test. Bridges were printed at spans of %smm.\n\n"
        "Look for:\n"
        "- Sag/drooping at longer spans\n"
        "- Clean straight bridge lines at shorter spans\n"
        "- At which span the bridge quality becomes unacceptable\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of bridge quality per span>\n"
        "RECOMMENDATION: <maximum recommended bridge span and settings>"
    ),
    'test_overhang': (
        "You are a 3D printing calibration expert. Analyze this image of an "
        "overhang test. Angled walls were printed at %s degree overhangs.\n\n"
        "Look for:\n"
        "- Curling or drooping at steep angles\n"
        "- Clean surface finish at shallow angles\n"
        "- At which angle quality degrades significantly\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of quality per angle>\n"
        "RECOMMENDATION: <maximum safe overhang angle and suggestions>"
    ),
    'recovery_assess': (
        "You are a 3D printing recovery expert. A print failure was detected. "
        "Analyze this image and the print context to determine if recovery "
        "is possible.\n\n"
        "Print info: File=%s, Layer=%s, Z=%.2fmm\n"
        "Failure detected: %s\n\n"
        "Determine:\n"
        "1. Is this failure recoverable by resuming from a safe layer?\n"
        "2. What type of failure is it?\n"
        "3. What layer should we resume from?\n\n"
        "Respond in this exact format:\n"
        "RECOVERABLE: <YES|NO>\n"
        "FAILURE_TYPE: <spaghetti|layer_shift|adhesion|warping|"
        "underextrusion|other>\n"
        "FAILED_LAYER: <layer number or UNKNOWN>\n"
        "RECOMMENDATION: <specific recovery action>"
    ),
    'recovery_verify': (
        "You are a 3D printing expert. A recovery was just attempted on a "
        "print that had failed. Examine this image to verify if the print "
        "has resumed successfully.\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description>\n"
        "RECOMMENDATION: <action>"
    ),
    'timelapse_frame': (
        "You are a 3D printing quality expert. Analyze this timelapse frame "
        "(frame %s of %s) from a 3D print. Look for any quality issues, "
        "defects, or problems starting to appear.\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <description of what you see>"
    ),
    'timelapse_summary': (
        "You are a 3D printing quality expert. You analyzed %s timelapse "
        "frames from a print. Here are the per-frame findings:\n\n%s\n\n"
        "Based on these observations:\n"
        "1. When did issues first appear (which frame)?\n"
        "2. What was the root cause?\n"
        "3. How could this be prevented?\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|FAILURE|UNCERTAIN>\n"
        "FINDINGS: <timeline of when issues appeared>\n"
        "RECOMMENDATION: <prevention suggestions>"
    ),
    'filament_suggest': (
        "You are a 3D printing filament expert. Suggest optimal settings for "
        "the following filament on a Klipper-based printer:\n\n"
        "Filament type: %s\n"
        "Brand: %s\n"
        "Nozzle diameter: %smm\n"
        "Current printer config:\n%s\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "EXTRUDER_TEMP: <value>\n"
        "BED_TEMP: <value>\n"
        "PRESSURE_ADVANCE: <value>\n"
        "RETRACT_LENGTH: <value>\n"
        "RETRACT_SPEED: <value>\n"
        "MAX_SPEED: <value>\n"
        "FAN_SPEED: <value>\n"
        "RECOMMENDATION: <notes>"
    ),
    'mesh_analyze': (
        "You are a 3D printer bed mesh expert. Analyze the following bed mesh "
        "probe data and provide diagnostic recommendations.\n\n"
        "Mesh bounds: (%.1f, %.1f) to (%.1f, %.1f) mm\n"
        "Grid size: %dx%d\n"
        "Z range: %.4f to %.4fmm (total deviation: %.4fmm)\n"
        "Mean Z: %.4fmm, Std Dev: %.4fmm\n\n"
        "Corner values:\n"
        "  Front-left: %.4fmm  Front-right: %.4fmm\n"
        "  Back-left: %.4fmm   Back-right: %.4fmm\n"
        "  Center: %.4fmm\n\n"
        "Full probe matrix (front to back):\n%s\n\n"
        "Based on this data:\n"
        "1. Is the bed level acceptable or does it need adjustment?\n"
        "2. Which corners need adjustment and in which direction?\n"
        "3. Is there any warping pattern (bowl, twist, saddle)?\n"
        "4. Any other mechanical issues suggested by the data?\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|NEEDS_ADJUSTMENT|WARPED>\n"
        "FINDINGS: <detailed description of mesh shape and issues>\n"
        "RECOMMENDATION: <specific adjustments to make>"
    ),
    'history_trend': (
        "You are a 3D printer maintenance expert. Analyze the following "
        "printer history log and identify trends, drift, or recurring "
        "issues.\n\n"
        "History entries (most recent first):\n%s\n\n"
        "Analyze:\n"
        "1. Is calibration drifting over time?\n"
        "2. Are print failures increasing?\n"
        "3. Any patterns suggesting mechanical wear or degradation?\n"
        "4. Maintenance recommendations?\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|DRIFT_DETECTED|MAINTENANCE_NEEDED>\n"
        "FINDINGS: <description of trends>\n"
        "RECOMMENDATION: <suggested actions>"
    ),
    'resonance_analyze': (
        "You are a 3D printer input shaper expert. Analyze the following "
        "resonance test data for the %s axis and recommend input shaper "
        "settings.\n\n"
        "Current settings: shaper_type=%s, shaper_freq=%s Hz\n\n"
        "Resonance data summary:\n%s\n\n"
        "Raw CSV header: %s\n"
        "Data sample (first 20 rows):\n%s\n\n"
        "Based on the resonance profile:\n"
        "1. What is the optimal shaper type and frequency?\n"
        "2. What maximum acceleration is safe?\n"
        "3. Are there any concerning secondary peaks?\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|NEEDS_ADJUSTMENT|CONCERNING>\n"
        "FINDINGS: <description of resonance profile>\n"
        "RECOMMENDATION: <recommended settings>\n"
        "CHANGE: [input_shaper] shaper_type_%s = <value>\n"
        "CHANGE: [input_shaper] shaper_freq_%s = <value>"
    ),
    'belt_check': (
        "You are a 3D printer maintenance expert. Compare the X and Y axis "
        "resonance profiles to assess belt tension balance.\n\n"
        "X-axis resonance summary:\n%s\n\n"
        "Y-axis resonance summary:\n%s\n\n"
        "Printer type: Cartesian\n\n"
        "Analyze:\n"
        "1. Are the resonance peaks consistent between axes?\n"
        "2. Does either axis show signs of loose belts?\n"
        "3. Are there signs of binding or over-tension?\n\n"
        "Respond in this exact format:\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "STATUS: <OK|TENSION_IMBALANCE|NEEDS_TIGHTENING|NEEDS_LOOSENING>\n"
        "FINDINGS: <description of belt condition>\n"
        "RECOMMENDATION: <specific adjustment suggestions>"
    ),
}


class RateLimiter:
    def __init__(self, reactor, rpm):
        self.reactor = reactor
        self.rpm = max(1, rpm)
        self.interval = 60.0 / self.rpm
        self.tokens = float(self.rpm)
        self.max_tokens = float(self.rpm)
        self.last_refill = reactor.monotonic()
        self.lock = threading.Lock()
    def acquire(self):
        with self.lock:
            now = self.reactor.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.max_tokens,
                              self.tokens + elapsed * (self.rpm / 60.0))
            self.last_refill = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False
    def wait_time(self):
        with self.lock:
            if self.tokens >= 1.0:
                return 0.0
            return (1.0 - self.tokens) / (self.rpm / 60.0)


class AIProvider:
    def __init__(self, config, api_key, model):
        self.api_key = api_key
        self.model = model
        self.timeout = config.getfloat('timeout', 30.0, above=0.)
    def send_request_sync(self, prompt, images=None):
        raise NotImplementedError("Subclasses must implement send_request_sync")
    def _read_image_base64(self, image_path):
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    def _guess_media_type(self, image_path):
        ext = os.path.splitext(image_path)[1].lower()
        types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.gif': 'image/gif',
            '.webp': 'image/webp', '.bmp': 'image/bmp',
        }
        return types.get(ext, 'image/jpeg')


class ClaudeProvider(AIProvider):
    API_URL = 'https://api.anthropic.com/v1/messages'
    def __init__(self, config, api_key, model):
        AIProvider.__init__(self, config, api_key, model)
        self.max_tokens = config.getint('max_tokens', 1024, minval=1)
        self.temperature = config.getfloat('temperature', 0.3,
                                           minval=0., maxval=2.)
    def send_request_sync(self, prompt, images=None):
        content = []
        if images:
            for img_path in images:
                img_data = self._read_image_base64(img_path)
                media_type = self._guess_media_type(img_path)
                content.append({
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': media_type,
                        'data': img_data,
                    }
                })
        content.append({'type': 'text', 'text': prompt})
        payload = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'messages': [{'role': 'user', 'content': content}],
        }
        data = json.dumps(payload).encode('utf-8')
        req = Request(self.API_URL, data=data)
        req.add_header('Content-Type', 'application/json')
        req.add_header('x-api-key', self.api_key)
        req.add_header('anthropic-version', '2023-06-01')
        try:
            resp = urlopen(req, timeout=self.timeout)
            body = json.loads(resp.read().decode('utf-8'))
            return body['content'][0]['text']
        except HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            raise Exception("Claude API error %d: %s" % (e.code, error_body))
        except URLError as e:
            raise Exception("Claude API connection error: %s" % (str(e),))


class OpenAIProvider(AIProvider):
    API_URL = 'https://api.openai.com/v1/chat/completions'
    def __init__(self, config, api_key, model, api_url=None):
        AIProvider.__init__(self, config, api_key, model)
        self.api_url = api_url or self.API_URL
        self.max_tokens = config.getint('max_tokens', 1024, minval=1)
        self.temperature = config.getfloat('temperature', 0.3,
                                           minval=0., maxval=2.)
    def send_request_sync(self, prompt, images=None):
        content = []
        if images:
            for img_path in images:
                img_data = self._read_image_base64(img_path)
                media_type = self._guess_media_type(img_path)
                data_uri = "data:%s;base64,%s" % (media_type, img_data)
                content.append({
                    'type': 'image_url',
                    'image_url': {'url': data_uri}
                })
        content.append({'type': 'text', 'text': prompt})
        payload = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'messages': [{'role': 'user', 'content': content}],
        }
        data = json.dumps(payload).encode('utf-8')
        req = Request(self.api_url, data=data)
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', 'Bearer %s' % (self.api_key,))
        try:
            resp = urlopen(req, timeout=self.timeout)
            body = json.loads(resp.read().decode('utf-8'))
            return body['choices'][0]['message']['content']
        except HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            raise Exception("OpenAI API error %d: %s" % (e.code, error_body))
        except URLError as e:
            raise Exception("OpenAI API connection error: %s" % (str(e),))


class OpenAICompatibleProvider(OpenAIProvider):
    def __init__(self, config, api_key, model, api_url):
        OpenAIProvider.__init__(self, config, api_key, model, api_url)


class PromptManager:
    def get_prompt(self, template_name, *args):
        template = PROMPT_TEMPLATES.get(template_name)
        if template is None:
            raise ValueError("Unknown prompt template: %s" % (template_name,))
        if args:
            return template % args
        return template


class AIBackend:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.prompt_manager = PromptManager()
        # Read config
        self.provider_name = config.get('provider', 'claude')
        self.api_key = config.get('api_key')
        self.model = config.get('model', 'claude-sonnet-4-20250514')
        self.vision_model = config.get('vision_model', self.model)
        self.timeout = config.getfloat('timeout', 30.0, above=0.)
        rate_limit_rpm = config.getint('rate_limit_rpm', 20, minval=1)
        # Create rate limiter
        self.rate_limiter = RateLimiter(self.reactor, rate_limit_rpm)
        # Create provider
        self.provider = self._create_provider(config)
        self.vision_provider = self.provider
        if self.vision_model != self.model:
            self.vision_provider = self._create_provider(
                config, model_override=self.vision_model)
        # Stats
        self.query_count = 0
        self.error_count = 0
        self.last_query_time = 0.
        self.last_error = ''
        # Register commands
        self.gcode.register_command(
            'AI_STATUS', self.cmd_AI_STATUS,
            desc=self.cmd_AI_STATUS_help)
        self.gcode.register_command(
            'AI_TEST', self.cmd_AI_TEST,
            desc=self.cmd_AI_TEST_help)
        # Register webhooks
        webhooks = self.printer.lookup_object('webhooks')
        webhooks.register_endpoint('ai_backend/status',
                                   self._handle_status_request)
        webhooks.register_endpoint('ai_backend/query',
                                   self._handle_query_request)
    def _create_provider(self, config, model_override=None):
        model = model_override or self.model
        if self.provider_name == 'claude':
            return ClaudeProvider(config, self.api_key, model)
        elif self.provider_name == 'openai':
            return OpenAIProvider(config, self.api_key, model)
        elif self.provider_name == 'openai_compatible':
            api_url = config.get('api_url')
            return OpenAICompatibleProvider(config, self.api_key,
                                            model, api_url)
        else:
            raise config.error(
                "Unknown AI provider '%s'. Must be one of: "
                "claude, openai, openai_compatible" % (self.provider_name,))
    def get_prompt_manager(self):
        return self.prompt_manager
    def query(self, prompt, images=None):
        # Non-blocking AI query using ReactorCompletion
        # Wait for rate limiter
        wait_time = self.rate_limiter.wait_time()
        if wait_time > 0:
            self.reactor.pause(self.reactor.monotonic() + wait_time)
        if not self.rate_limiter.acquire():
            raise self.printer.command_error(
                "AI rate limit exceeded. Try again shortly.")
        provider = self.vision_provider if images else self.provider
        completion = self.reactor.completion()
        def thread_func():
            try:
                response = provider.send_request_sync(prompt, images)
                self.reactor.async_complete(completion,
                                            {'response': response})
            except Exception as e:
                self.reactor.async_complete(completion,
                                            {'error': str(e)})
        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()
        result = completion.wait(
            waketime=self.reactor.monotonic() + self.timeout)
        if result is None:
            self.error_count += 1
            self.last_error = "Request timed out"
            raise self.printer.command_error("AI request timed out")
        if 'error' in result:
            self.error_count += 1
            self.last_error = result['error']
            raise self.printer.command_error(
                "AI request failed: %s" % (result['error'],))
        self.query_count += 1
        self.last_query_time = self.reactor.monotonic()
        return result['response']
    def query_async(self, prompt, callback, images=None):
        # Non-blocking AI query with callback
        wait_time = self.rate_limiter.wait_time()
        def do_query():
            if wait_time > 0:
                time.sleep(wait_time)
            if not self.rate_limiter.acquire():
                self.reactor.register_async_callback(
                    lambda e: callback(None,
                        "AI rate limit exceeded. Try again shortly."))
                return
            provider = self.vision_provider if images else self.provider
            try:
                response = provider.send_request_sync(prompt, images)
                self.query_count += 1
                self.last_query_time = self.reactor.monotonic()
                self.reactor.register_async_callback(
                    lambda e: callback(response, None))
            except Exception as e:
                self.error_count += 1
                self.last_error = str(e)
                self.reactor.register_async_callback(
                    lambda e: callback(None, str(e)))
        thread = threading.Thread(target=do_query)
        thread.daemon = True
        thread.start()
    def get_status(self, eventtime):
        return {
            'provider': self.provider_name,
            'model': self.model,
            'vision_model': self.vision_model,
            'query_count': self.query_count,
            'error_count': self.error_count,
            'last_query_time': self.last_query_time,
            'last_error': self.last_error,
        }
    # G-code commands
    cmd_AI_STATUS_help = "Report AI backend status"
    def cmd_AI_STATUS(self, gcmd):
        status = self.get_status(self.reactor.monotonic())
        self.gcode.respond_info(
            "AI Backend Status:\n"
            "  Provider: %s\n"
            "  Model: %s\n"
            "  Vision Model: %s\n"
            "  Queries: %d\n"
            "  Errors: %d\n"
            "  Last Error: %s"
            % (status['provider'], status['model'], status['vision_model'],
               status['query_count'], status['error_count'],
               status['last_error'] or 'None'))
    cmd_AI_TEST_help = "Test AI backend connectivity"
    def cmd_AI_TEST(self, gcmd):
        self.gcode.respond_info("Testing AI backend connectivity...")
        try:
            response = self.query("Reply with exactly: OK")
            self.gcode.respond_info("AI backend test successful: %s"
                                    % (response,))
        except self.printer.command_error as e:
            raise gcmd.error("AI backend test failed: %s" % (str(e),))
    # Webhooks handlers
    def _handle_status_request(self, web_request):
        eventtime = self.reactor.monotonic()
        web_request.send(self.get_status(eventtime))
    def _handle_query_request(self, web_request):
        prompt = web_request.get_str('prompt')
        try:
            response = self.query(prompt)
            web_request.send({'response': response})
        except self.printer.command_error as e:
            raise web_request.error(str(e))

def load_config(config):
    return AIBackend(config)
