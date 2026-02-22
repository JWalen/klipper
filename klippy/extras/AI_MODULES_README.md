# Klipper AI Modules

AI-powered configuration analysis, print monitoring, calibration guidance, and
automated calibration test prints for Klipper 3D printers.

## Modules Overview

| Module | Purpose |
|--------|---------|
| `ai_backend` | Core AI provider — connects to Claude, OpenAI, Ollama, or any OpenAI-compatible API |
| `ai_config_assistant` | Analyze, suggest improvements, ask questions about, and auto-fix your printer config |
| `ai_camera` | Camera-based print monitoring with AI vision analysis (failure detection, first layer checks) |
| `ai_calibration_wizard` | Step-by-step AI-guided full printer calibration |
| `ai_print_tests` | Generate and run slicer-free calibration test prints with optional AI analysis |

## Quick Start

Add to your `printer.cfg`:

```ini
[ai_backend]
provider: claude
api_key: YOUR_API_KEY_HERE
model: claude-sonnet-4-20250514

[ai_config_assistant]

[ai_camera]
capture_command: wget
snapshot_url: http://localhost:8080/?action=snapshot
capture_dir: /tmp/ai_camera

[ai_calibration_wizard]

[ai_print_tests]
```

Restart Klipper, then test connectivity:

```
AI_TEST
```

---

## AI Backend Configuration

The `[ai_backend]` section is required by all other AI modules. It handles API
communication, rate limiting, and provider selection.

### Provider: Anthropic Claude (Recommended for Vision)

```ini
[ai_backend]
provider: claude
api_key: sk-ant-xxxxx
model: claude-sonnet-4-20250514
vision_model: claude-sonnet-4-20250514
timeout: 30.0
max_tokens: 1024
temperature: 0.3
rate_limit_rpm: 20
```

Get your API key at: https://console.anthropic.com/settings/keys

### Provider: OpenAI

```ini
[ai_backend]
provider: openai
api_key: sk-xxxxx
model: gpt-4o
vision_model: gpt-4o
timeout: 30.0
max_tokens: 1024
temperature: 0.3
rate_limit_rpm: 20
```

Get your API key at: https://platform.openai.com/api-keys

### Provider: Local Ollama Server

Ollama exposes an OpenAI-compatible API, so use the `openai_compatible` provider.

1. Install Ollama on your printer host (or another machine on your network):
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ```

2. Pull a model (see recommended models below):
   ```bash
   ollama pull llama3.1:8b
   ```

3. Configure the backend:
   ```ini
   [ai_backend]
   provider: openai_compatible
   api_key: ollama
   api_url: http://localhost:11434/v1/chat/completions
   model: llama3.1:8b
   timeout: 120.0
   max_tokens: 1024
   temperature: 0.3
   rate_limit_rpm: 60
   ```

   If Ollama runs on a different machine, replace `localhost` with that
   machine's IP address (e.g., `http://192.168.1.100:11434/v1/chat/completions`).

#### Recommended Ollama Models

| Model | VRAM | Vision | Best For |
|-------|------|--------|----------|
| `llama3.1:8b` | ~5 GB | No | Config analysis, text-only tasks on RPi 5 or x86 |
| `llama3.1:70b` | ~40 GB | No | Best text quality if you have a GPU server |
| `llava:7b` | ~5 GB | Yes | Vision tasks (camera analysis, print tests) on modest hardware |
| `llava:13b` | ~9 GB | Yes | Better vision quality with a dedicated GPU |
| `llama3.2-vision:11b` | ~8 GB | Yes | Best balance of vision quality and resource usage |

**Notes:**
- Vision models are required for camera monitoring and `ANALYZE=1` on print
  tests. Without a vision model, those features will work but the AI cannot
  interpret images.
- Running on a Raspberry Pi is possible with 8b models but slow (30-120s per
  query). A separate machine with a GPU is strongly recommended.
- Set `timeout` to `120.0` or higher for local models — they are slower than
  cloud APIs.
- The `api_key` field is required but Ollama ignores it — set it to any
  non-empty string like `ollama`.

### Provider: Any OpenAI-Compatible API

This works with LM Studio, text-generation-webui, vLLM, LocalAI, or any server
that implements the OpenAI chat completions endpoint.

```ini
[ai_backend]
provider: openai_compatible
api_key: your-key-or-dummy
api_url: http://your-server:port/v1/chat/completions
model: your-model-name
timeout: 60.0
max_tokens: 1024
temperature: 0.3
rate_limit_rpm: 60
```

### Backend Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `claude` | `claude`, `openai`, or `openai_compatible` |
| `api_key` | (required) | API key for the provider |
| `api_url` | — | API endpoint URL (required for `openai_compatible`) |
| `model` | `claude-sonnet-4-20250514` | Model name for text queries |
| `vision_model` | same as `model` | Model name for vision/image queries |
| `timeout` | `30.0` | Request timeout in seconds |
| `max_tokens` | `1024` | Max response tokens |
| `temperature` | `0.3` | Response randomness (0.0 = deterministic, 2.0 = creative) |
| `rate_limit_rpm` | `20` | Max requests per minute |

### Backend G-code Commands

| Command | Description |
|---------|-------------|
| `AI_STATUS` | Show backend status (provider, model, query count, errors) |
| `AI_TEST` | Test API connectivity |

---

## AI Config Assistant

Analyzes your printer configuration and proposes fixes.

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_CONFIG_CHECK` | Full config analysis for issues and safety concerns |
| `AI_CONFIG_CHECK SECTION=extruder` | Analyze a specific section only |
| `AI_CONFIG_SUGGEST` | General optimization suggestions |
| `AI_CONFIG_SUGGEST FOCUS=speed` | Suggestions focused on a specific area |
| `AI_ASK QUESTION="Is my acceleration too high?"` | Ask a free-form question about your config |
| `AI_CONFIG_FIX` | AI proposes and stages config fixes (requires `SAVE_CONFIG` to persist) |
| `AI_CONFIG_FIX SECTION=extruder` | Propose fixes for a specific section |

### Safety

`AI_CONFIG_FIX` stages changes only — nothing is written to disk until you run
`SAVE_CONFIG`. All changes are logged.

---

## AI Camera

Camera-based print monitoring with automatic failure detection.

### Camera Setup

The camera module supports multiple capture methods:

#### Crowsnest / ustreamer snapshot (Recommended)

If you already have crowsnest running (default on MainsailOS), use the snapshot
URL — no device conflict:

```ini
[ai_camera]
capture_command: wget
snapshot_url: http://localhost:8080/?action=snapshot
capture_dir: /tmp/ai_camera
check_interval: 60.0
failure_action: pause
confidence_threshold: 0.7
enable_first_layer_check: True
first_layer_check_delay: 120.0
```

#### Direct device capture (fswebcam)

Only use this if nothing else is using the camera device:

```ini
[ai_camera]
camera_device: /dev/video0
capture_command: fswebcam
resolution: 1280x720
capture_dir: /tmp/ai_camera
```

#### Other capture commands

| Command | Use Case |
|---------|----------|
| `fswebcam` | Direct USB webcam capture |
| `ffmpeg` | Direct V4L2 capture with ffmpeg |
| `libcamera-still` | Raspberry Pi camera module |
| `wget` | Snapshot from crowsnest/ustreamer URL |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_CAMERA_CHECK` | One-shot camera check (default: failure detection) |
| `AI_CAMERA_CHECK TYPE=first_layer` | Check first layer quality |
| `AI_CAMERA_CHECK TYPE=completion` | Check completed print quality |
| `AI_CAMERA_CHECK TYPE=general` | General observation |
| `AI_CAMERA_WATCH` | Start continuous monitoring during prints |
| `AI_CAMERA_WATCH INTERVAL=30` | Monitor every 30 seconds |
| `AI_CAMERA_STOP` | Stop continuous monitoring |
| `AI_CAMERA_ANALYZE FILE=/path/to/image.jpg` | Analyze an existing image |

### Camera Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `camera_device` | `/dev/video0` | Camera device path (for fswebcam/ffmpeg) |
| `capture_command` | `fswebcam` | Capture method: `fswebcam`, `ffmpeg`, `libcamera-still`, `wget` |
| `snapshot_url` | — | Snapshot URL (required for `wget`) |
| `resolution` | `1280x720` | Capture resolution (for fswebcam/ffmpeg/libcamera-still) |
| `capture_dir` | `/tmp/ai_camera` | Directory to store captured images |
| `check_interval` | `60.0` | Seconds between automatic checks |
| `failure_action` | `pause` | Action on failure: `pause`, `alert`, `none` |
| `confidence_threshold` | `0.7` | Minimum confidence to trigger failure action (0.0-1.0) |
| `enable_first_layer_check` | `True` | Auto-check first layer during prints |
| `first_layer_check_delay` | `120.0` | Seconds after print start before first layer check |
| `enable_completion_check` | `True` | Auto-check when print completes |

---

## AI Calibration Wizard

Interactive step-by-step printer calibration with AI guidance before and after
each step. Automatically detects which steps apply to your printer based on your
config.

### Calibration Steps (auto-detected)

| Step | Requires Config Section | Command |
|------|------------------------|---------|
| Home All Axes | (always) | `G28` |
| Probe Z-Offset | `[probe]` | `PROBE_CALIBRATE` |
| Bed Screws Tilt | `[screws_tilt_adjust]` | `SCREWS_TILT_CALCULATE` |
| Z Tilt Adjust | `[z_tilt]` | `Z_TILT_ADJUST` |
| Quad Gantry Level | `[quad_gantry_level]` | `QUAD_GANTRY_LEVEL` |
| Delta Calibrate | `[delta_calibrate]` | `DELTA_CALIBRATE` |
| Bed Mesh | `[bed_mesh]` | `BED_MESH_CALIBRATE` |
| PID Bed | `[heater_bed]` | `PID_CALIBRATE HEATER=heater_bed TARGET=60` |
| PID Extruder | `[extruder]` | `PID_CALIBRATE HEATER=extruder TARGET=200` |
| Input Shaper | `[resonance_tester]` | `SHAPER_CALIBRATE` |
| Axis Twist | `[axis_twist_compensation]` | `AXIS_TWIST_COMPENSATION_CALIBRATE` |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_CALIBRATE_START` | Start the full wizard |
| `AI_CALIBRATE_START FROM_STEP=bed_mesh` | Resume from a specific step |
| `AI_CALIBRATE_START SKIP=pid_bed,pid_extruder` | Skip specific steps |
| `AI_CALIBRATE_NEXT` | Execute the current step |
| `AI_CALIBRATE_SKIP` | Skip the current step |
| `AI_CALIBRATE_ABORT` | Abort the wizard |
| `AI_CALIBRATE_STATUS` | Show wizard progress |

---

## AI Print Tests

Generate and run calibration test prints directly from Klipper — no slicer
needed. Optionally capture a photo and ask the AI to analyze results and propose
config fixes.

### G-code Commands

| Command | Purpose | Key Parameters |
|---------|---------|----------------|
| `AI_TEST_FIRST_LAYER` | Zigzag lines across bed — tests Z-offset and adhesion | `BED_TEMP=60 EXTRUDER_TEMP=200 ANALYZE=0` |
| `AI_TEST_FLOW` | Line groups at varying extrusion multipliers | `START=0.9 END=1.1 STEPS=5` |
| `AI_TEST_PA` | Slow-fast-slow lines at varying pressure advance | `START=0.0 END=0.1 STEPS=10` |
| `AI_TEST_SPEED` | Lines at increasing print speeds | `START=50 END=200 STEPS=6` |

All commands accept `BED_TEMP`, `EXTRUDER_TEMP`, and `ANALYZE` parameters.

### Examples

```gcode
; Basic first layer test (no analysis)
AI_TEST_FIRST_LAYER

; First layer test with custom temps
AI_TEST_FIRST_LAYER BED_TEMP=65 EXTRUDER_TEMP=210

; PA test with narrow range and AI analysis
AI_TEST_PA START=0.0 END=0.08 STEPS=8 ANALYZE=1

; Flow test with AI analysis
AI_TEST_FLOW START=0.9 END=1.1 STEPS=5 ANALYZE=1

; Speed test
AI_TEST_SPEED START=50 END=150 STEPS=5
```

### What Each Test Prints

**First Layer Test** — Zigzag lines at 0.28mm height spanning the full bed.
Look for consistent squish, good adhesion, and even line width. AI can propose
`[probe] z_offset` adjustments.

**Flow Test** — Groups of 5 parallel lines, each group at a different extrusion
multiplier (default 90%-110%). Find the group with the smoothest, most consistent
lines. AI can propose `[extruder] rotation_distance` adjustments.

**Pressure Advance Test** — Lines with slow-fast-slow speed transitions at
different PA values. Find the line with the cleanest transitions (no bulging, no
gaps at corners). AI can propose `[extruder] pressure_advance` adjustments.

**Speed Test** — Identical lines printed at increasing speeds. Find where quality
starts to degrade. AI reports the recommended maximum safe print speed.

### ANALYZE=1

When `ANALYZE=1` is set, after printing the test the module will:
1. Capture an image via the `[ai_camera]` module
2. Send the image to the AI with a specialized analysis prompt
3. Report findings (confidence, status, description)
4. Propose config changes if needed (staged for `SAVE_CONFIG`)

Requires `[ai_camera]` to be configured. If the camera is unavailable, the test
still prints — analysis is gracefully skipped.

### Convenience Macros

These macros run each test with `ANALYZE=1` enabled. Add to your `macros.cfg`:

```ini
[gcode_macro AI_FIRST_LAYER_TEST]
description: Print first layer calibration test with AI analysis
gcode:
    AI_TEST_FIRST_LAYER ANALYZE=1

[gcode_macro AI_FLOW_TEST]
description: Print flow/extrusion calibration test with AI analysis
gcode:
    AI_TEST_FLOW ANALYZE=1

[gcode_macro AI_PA_TEST]
description: Print pressure advance calibration test with AI analysis
gcode:
    AI_TEST_PA ANALYZE=1

[gcode_macro AI_SPEED_TEST]
description: Print speed calibration test with AI analysis
gcode:
    AI_TEST_SPEED ANALYZE=1
```

---

## Webhook API

All modules expose JSON-RPC webhook endpoints for integration with Mainsail,
Fluidd, or custom frontends.

### ai_backend
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_backend/status` | GET | — |
| `ai_backend/query` | POST | `prompt` |

### ai_config_assistant
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_config_assistant/check` | POST | `section` (optional) |
| `ai_config_assistant/suggest` | POST | `focus` (optional) |
| `ai_config_assistant/ask` | POST | `question` |
| `ai_config_assistant/fix` | POST | `section` (optional) |

### ai_camera
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_camera/status` | GET | — |
| `ai_camera/check` | POST | `type` (`failure`, `first_layer`, `completion`, `general`) |
| `ai_camera/watch` | POST | `interval` (optional, seconds) |
| `ai_camera/stop` | POST | — |

### ai_calibration_wizard
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_calibration_wizard/start` | POST | `from_step`, `skip` (optional) |
| `ai_calibration_wizard/next` | POST | — |
| `ai_calibration_wizard/skip` | POST | — |
| `ai_calibration_wizard/abort` | POST | — |
| `ai_calibration_wizard/status` | GET | — |

### ai_print_tests
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_print_tests/status` | GET | — |
| `ai_print_tests/run` | POST | `type` (`first_layer`, `flow`, `pa`, `speed`), `bed_temp`, `extruder_temp`, `analyze`, `start`, `end`, `steps` |

---

## Troubleshooting

**"AI backend not available"** — The `[ai_backend]` section is missing or Klipper
hasn't finished starting. Wait for the `Ready` message.

**"AI request timed out"** — Increase `timeout` in `[ai_backend]`. Local models
may need 120s or more.

**"Claude API error 401: invalid x-api-key"** — Your API key is wrong or still
set to the placeholder. Update `api_key` in `[ai_backend]`.

**"Camera capture failed: Capture produced no output file"** — The camera is
unavailable. If using crowsnest, switch to `capture_command: wget` with a
`snapshot_url`. If using fswebcam, make sure nothing else is using `/dev/video0`.

**"A test is already in progress"** — A print test is currently running. Wait for
it to finish or restart Klipper.

**Local model responses are poor quality** — Try a larger model, lower the
temperature to 0.1, or increase `max_tokens`. The 8b models work but larger
models give significantly better analysis.
