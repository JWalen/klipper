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
| `ai_mesh_analysis` | AI interprets bed mesh probe data and suggests mechanical fixes |
| `ai_filament_profiles` | Per-filament settings storage with AI-suggested profiles |
| `ai_print_history` | Log prints and calibrations, AI trend analysis for drift detection |
| `ai_resonance` | ADXL resonance analysis and belt tension checking with AI |
| `ai_timelapse` | Post-print timelapse frame analysis to identify when issues started |
| `ai_notifications` | Telegram and Discord notifications with camera snapshots |
| `ai_print_recovery` | Smart AI-guided print failure recovery |

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

[ai_mesh_analysis]

[ai_filament_profiles]

[ai_print_history]

[ai_resonance]

[ai_timelapse]

[ai_notifications]

[ai_print_recovery]
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
| `AI_TEST_FIRST_LAYER` | Zigzag lines across bed — tests Z-offset and adhesion | `BED_TEMP=60 EXTRUDER_TEMP=200` |
| `AI_TEST_FLOW` | Line groups at varying extrusion multipliers | `START=0.9 END=1.1 STEPS=5` |
| `AI_TEST_PA` | Slow-fast-slow lines at varying pressure advance | `START=0.0 END=0.1 STEPS=10` |
| `AI_TEST_SPEED` | Lines at increasing print speeds | `START=50 END=200 STEPS=6` |
| `AI_TEST_TEMP` | Temperature tower — stacked sections at different temps | `START_TEMP=190 END_TEMP=230 STEP=5` |
| `AI_TEST_RETRACTION` | Side-by-side columns testing stringing | `START=0.2 END=2.0 STEPS=5` |
| `AI_TEST_BRIDGING` | Bridge spans between pillar pairs | `SPANS=20,40,60,80` |
| `AI_TEST_OVERHANG` | Wall sections at increasing overhang angles | `ANGLES=15,30,45,60,75` |

All commands accept `BED_TEMP`, `EXTRUDER_TEMP`, and `ANALYZE` parameters.
`AI_TEST_TEMP` uses `START_TEMP` instead of `EXTRUDER_TEMP`.

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

; Temperature tower from 190 to 230 in 5-degree steps
AI_TEST_TEMP START_TEMP=190 END_TEMP=230 STEP=5 ANALYZE=1

; Retraction test with AI analysis
AI_TEST_RETRACTION START=0.2 END=2.0 STEPS=5 ANALYZE=1

; Bridging test with custom spans
AI_TEST_BRIDGING SPANS=20,40,60,80 ANALYZE=1

; Overhang test
AI_TEST_OVERHANG ANGLES=15,30,45,60,75 ANALYZE=1
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

**Temperature Tower** — Hollow 20x20mm square sections stacked vertically, each
printed at a different temperature (default 190-230 in 5-degree steps, 5 layers
per section). Look for the section with best surface quality, bridging, and
overhangs. AI proposes the optimal print temperature.

**Retraction Test** — Side-by-side 10x10mm columns (~10mm tall), with travel
moves between them. Each column uses a different retraction length (default
0.2-2.0mm). Look for the column with the least stringing between towers. AI can
propose `[firmware_retraction] retract_length` changes.

**Bridging Test** — Pairs of 10x10mm support pillars (~5mm tall) spaced at
different distances (default 20, 40, 60, 80mm). Bridge lines are printed across
each gap. Look for the longest span with minimal sag. AI reports the maximum
safe bridge distance.

**Overhang Test** — A vertical wall base (10 layers) followed by sections that
extend outward at increasing angles (default 15, 30, 45, 60, 75 degrees). Look
for where the overhangs start drooping or curling. AI reports the maximum safe
overhang angle.

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

[gcode_macro AI_TEMP_TOWER]
description: Print temperature tower with AI analysis
gcode:
    AI_TEST_TEMP ANALYZE=1

[gcode_macro AI_RETRACTION_TEST]
description: Print retraction test with AI analysis
gcode:
    AI_TEST_RETRACTION ANALYZE=1

[gcode_macro AI_BRIDGING_TEST]
description: Print bridging test with AI analysis
gcode:
    AI_TEST_BRIDGING ANALYZE=1

[gcode_macro AI_OVERHANG_TEST]
description: Print overhang test with AI analysis
gcode:
    AI_TEST_OVERHANG ANALYZE=1
```

---

## AI Mesh Analysis

Analyzes your bed mesh probe data and provides actionable recommendations for
mechanical adjustments (screw turns, shim placement, warping diagnosis).

### Setup

```ini
[ai_mesh_analysis]
```

No configuration options required. The module reads data from your existing
`[bed_mesh]` section.

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_MESH_ANALYZE` | Analyze the current bed mesh probe data |

Run `BED_MESH_CALIBRATE` first to generate probe data, then run `AI_MESH_ANALYZE`
to get AI interpretation.

### What It Reports

- Min/max/mean/std deviation of Z probe values
- Per-corner Z values (front-left, front-right, back-left, back-right, center)
- Total range across the bed
- AI recommendations: which screws to turn and by how much, warping patterns,
  and whether the mesh compensation is sufficient or mechanical fixes are needed

### Example

```gcode
; Probe the bed, then analyze
BED_MESH_CALIBRATE
AI_MESH_ANALYZE
```

---

## AI Filament Profiles

Store per-filament settings (temperatures, pressure advance, retraction, speeds)
and let AI suggest optimal settings for new filaments.

### Setup

```ini
[ai_filament_profiles]
profiles_file: ~/printer_data/config/filament_profiles.json
```

### Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `profiles_file` | `~/printer_data/config/filament_profiles.json` | Path to JSON file storing profiles |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_FILAMENT_SET NAME=PLA_Generic TYPE=PLA EXTRUDER_TEMP=200 BED_TEMP=60 PA=0.02 RETRACT=0.9` | Create or update a profile |
| `AI_FILAMENT_LOAD NAME=PLA_Generic` | Apply a saved profile's settings |
| `AI_FILAMENT_SAVE NAME=MyPLA TYPE=PLA BRAND=Hatchbox` | Save current live settings as a profile |
| `AI_FILAMENT_LIST` | List all saved profiles |
| `AI_FILAMENT_SUGGEST TYPE=PETG` | AI suggests settings for a filament type |
| `AI_FILAMENT_SUGGEST TYPE=PLA BRAND=Hatchbox` | AI suggests with brand-specific tuning |
| `AI_FILAMENT_DELETE NAME=OldProfile` | Delete a saved profile |

### Profile Fields

| Field | Set With | Description |
|-------|----------|-------------|
| `type` | `TYPE=` | Filament type (PLA, PETG, ABS, TPU, etc.) |
| `brand` | `BRAND=` | Brand name |
| `extruder_temp` | `EXTRUDER_TEMP=` | Hotend temperature |
| `bed_temp` | `BED_TEMP=` | Bed temperature |
| `pressure_advance` | `PA=` | Pressure advance value |
| `retract_length` | `RETRACT=` | Retraction length (mm) |
| `retract_speed` | `RETRACT_SPEED=` | Retraction speed (mm/s) |
| `max_speed` | `MAX_SPEED=` | Maximum print speed (mm/s) |
| `fan_speed` | `FAN_SPEED=` | Part cooling fan (0-100%) |
| `notes` | `NOTES=` | Free-form notes |

### What LOAD Does

`AI_FILAMENT_LOAD` applies the profile by running:
- `SET_PRESSURE_ADVANCE ADVANCE={pa}` if pressure_advance is set
- `SET_RETRACTION RETRACT_LENGTH={len} RETRACT_SPEED={spd}` if retraction values are set

Temperature and fan speed are reported but not auto-applied (set them in your
slicer's start G-code or `START_PRINT` macro).

### Example Workflow

```gcode
; AI suggests settings for PETG
AI_FILAMENT_SUGGEST TYPE=PETG BRAND=Overture

; Create a profile with the suggested values
AI_FILAMENT_SET NAME=PETG_Overture TYPE=PETG BRAND=Overture EXTRUDER_TEMP=240 BED_TEMP=80 PA=0.05 RETRACT=0.6

; Before printing with this filament, load it
AI_FILAMENT_LOAD NAME=PETG_Overture

; After tuning with calibration tests, save current live settings
AI_FILAMENT_SAVE NAME=PETG_Overture_Tuned TYPE=PETG BRAND=Overture
```

---

## AI Print History

Logs prints and calibration events with optional auto-logging. AI can analyze
trends to detect calibration drift, recurring failures, and maintenance needs.

### Setup

```ini
[ai_print_history]
history_file: ~/printer_data/config/print_history.json
max_entries: 500
auto_log: True
```

### Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `history_file` | `~/printer_data/config/print_history.json` | Path to JSON history file |
| `max_entries` | `500` | Maximum entries to retain (oldest trimmed first) |
| `auto_log` | `True` | Automatically log print completions/cancellations |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_HISTORY_SHOW` | Show 10 most recent entries |
| `AI_HISTORY_SHOW COUNT=20` | Show more entries |
| `AI_HISTORY_SHOW TYPE=calibration_test` | Filter by entry type |
| `AI_HISTORY_TREND` | AI analyzes recent history for patterns and drift |
| `AI_HISTORY_TREND COUNT=100` | Analyze more history entries |
| `AI_HISTORY_ADD TYPE=note NOTES="Replaced nozzle"` | Add a manual note |
| `AI_HISTORY_CLEAR` | Clear all history |

### Entry Types

| Type | Source |
|------|--------|
| `print_complete` | Auto-logged when a print finishes successfully |
| `print_cancelled` | Auto-logged when a print is cancelled |
| `print_error` | Auto-logged on print errors |
| `calibration_test` | Logged by AI print tests |
| `config_change` | Logged when AI stages config changes |
| `note` | Manual entries via `AI_HISTORY_ADD` |

### What Trend Analysis Reports

`AI_HISTORY_TREND` sends recent history to the AI, which identifies:
- Calibration drift (e.g., Z-offset creeping over time)
- Recurring failure patterns (e.g., same model always fails)
- Maintenance needs (e.g., increasing retraction suggesting nozzle wear)
- Performance changes over time

---

## AI Resonance

Runs resonance tests with your ADXL345 accelerometer and uses AI to interpret
the frequency data, recommend input shaper settings, and check belt tension.

### Setup

```ini
[ai_resonance]
csv_dir: /tmp
```

Requires `[resonance_tester]` and `[adxl345]` to be configured in your
printer.cfg for resonance testing to work.

### Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `csv_dir` | `/tmp` | Directory where resonance CSV files are saved |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_RESONANCE_TEST` | Run X-axis resonance test with AI analysis |
| `AI_RESONANCE_TEST AXIS=y` | Run Y-axis resonance test |
| `AI_BELT_CHECK` | Run both axes and compare belt tension |
| `AI_RESONANCE_ANALYZE FILE=/tmp/resonances_x_*.csv` | Analyze an existing CSV |

### What It Reports

**Resonance Test:**
- Peak resonance frequency and magnitude
- Number of significant frequency peaks
- Current vs recommended input shaper type and frequency
- Can propose `[input_shaper] shaper_type_x` and `shaper_freq_x` changes

**Belt Check:**
- Compares X and Y axis resonance profiles
- Identifies uneven belt tension from asymmetric peaks
- Reports which belt may need tightening

### Example

```gcode
; Full belt tension check
AI_CHECK_BELTS

; Single axis with AI analysis
AI_RESONANCE_CHECK AXIS=x
```

---

## AI Timelapse

Analyzes timelapse frames captured during a print to identify when and where
issues first appeared. Useful for post-mortem analysis of failed prints.

### Setup

```ini
[ai_timelapse]
frames_dir: /tmp/timelapse
max_frames_to_analyze: 20
```

### Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `frames_dir` | `/tmp/timelapse` | Directory containing timelapse frame images |
| `max_frames_to_analyze` | `20` | Maximum frames to send to AI (uniformly sampled) |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_TIMELAPSE_ANALYZE` | Analyze frames in the default directory |
| `AI_TIMELAPSE_ANALYZE PATH=/path/to/frames` | Analyze frames in a specific directory |
| `AI_TIMELAPSE_ANALYZE MAX_FRAMES=10` | Limit frames analyzed |

### How It Works

1. Collects all `.jpg` and `.png` files from the frames directory
2. If more than `max_frames_to_analyze`, uniformly samples down
3. Sends each frame to AI with a per-frame analysis prompt
4. Compiles all per-frame findings into a summary prompt
5. Reports when issues first appeared, what went wrong, and likely root cause

### Integration

Works with any timelapse plugin that saves frames as numbered images (e.g.,
`frame_0001.jpg`, `frame_0002.jpg`). Compatible with the Moonraker timelapse
component.

---

## AI Notifications

Sends notifications to Telegram and/or Discord when the AI camera detects issues
or prints complete. Notifications can include camera snapshots.

### Setup

```ini
[ai_notifications]
telegram_bot_token: YOUR_BOT_TOKEN
telegram_chat_id: YOUR_CHAT_ID
#discord_webhook_url: https://discord.com/api/webhooks/...
notify_on_failure: True
notify_on_completion: True
include_snapshot: True
```

Configure at least one notification target (Telegram or Discord).

### Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `telegram_bot_token` | — | Telegram bot API token (from @BotFather) |
| `telegram_chat_id` | — | Telegram chat/group/channel ID |
| `discord_webhook_url` | — | Discord channel webhook URL |
| `notify_on_failure` | `True` | Send notification on print failure detection |
| `notify_on_completion` | `True` | Send notification on print completion |
| `notify_on_first_layer` | `False` | Send notification after first layer check |
| `include_snapshot` | `True` | Include camera snapshot in notifications |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_NOTIFY_TEST` | Send a test notification to all configured targets |
| `AI_NOTIFY MESSAGE="Filament change needed"` | Send a custom notification |

### Setting Up Telegram

1. Message @BotFather on Telegram to create a bot and get a token
2. Start a chat with your bot
3. Get your chat ID by messaging @userinfobot or visiting
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Add the token and chat ID to your config

### Setting Up Discord

1. In your Discord server, go to channel Settings > Integrations > Webhooks
2. Create a webhook and copy the URL
3. Add the URL to your config

### Automatic Triggers

When `[ai_camera]` is also configured, notifications are sent automatically:
- **On failure detection** (`notify_on_failure`): When AI camera detects a print
  failure and pauses the print
- **On completion** (`notify_on_completion`): When a print finishes successfully
- **On first layer** (`notify_on_first_layer`): After the first layer quality check

---

## AI Print Recovery

Attempts to recover from print failures detected by the AI camera. Assesses the
failure with AI, and if recoverable, performs a purge-and-resume sequence.

### Setup

```ini
[ai_print_recovery]
enabled: True
max_retries: 2
purge_amount: 30.0
z_hop: 5.0
```

Requires `[ai_camera]` and `[pause_resume]` to be configured.

### Config Reference

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `True` | Enable/disable the recovery system |
| `max_retries` | `2` | Maximum recovery attempts per print |
| `purge_amount` | `30.0` | Filament to purge during recovery (mm) |
| `z_hop` | `5.0` | Z lift height during recovery (mm) |

### G-code Commands

| Command | Description |
|---------|-------------|
| `AI_RECOVER` | Attempt recovery (print must be paused) |
| `AI_RECOVERY_ENABLE` | Enable recovery and reset retry counter |
| `AI_RECOVERY_DISABLE` | Disable recovery |

### How Recovery Works

1. Print must be paused (either manually or by AI camera's `failure_action: pause`)
2. `AI_RECOVER` captures an image and sends it to AI for failure assessment
3. AI responds with: recoverable (yes/no), failure type, failed layer, recommendation
4. If recoverable and retries remain:
   - Lifts Z by `z_hop`
   - Moves aside, purges `purge_amount` mm of filament
   - Retracts, moves back, lowers Z
   - Resumes the print
5. After 60 seconds, captures another image to verify recovery worked
6. If verification shows continued failure, reports it to the console

### Safety

- Recovery requires the print to be paused first — it will not interrupt a running print
- `max_retries` prevents infinite recovery loops
- AI must assess the failure as recoverable before attempting recovery
- If AI says the failure is not recoverable, it reports findings and recommends cancelling

### Example

```gcode
; AI camera pauses print due to detected failure...
; Check what happened:
AI_CHECK_PRINT

; Attempt recovery:
AI_RECOVER_PRINT

; Or enable automatic recovery before starting a print:
AI_RECOVERY_ON
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
| `ai_print_tests/run` | POST | `type` (`first_layer`, `flow`, `pa`, `speed`, `temp`, `retraction`, `bridging`, `overhang`), `bed_temp`, `extruder_temp`, `analyze`, `start`, `end`, `steps`, `start_temp`, `end_temp`, `step`, `spans`, `angles` |

### ai_mesh_analysis
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_mesh_analysis/status` | GET | — |
| `ai_mesh_analysis/analyze` | POST | — |

### ai_filament_profiles
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_filament_profiles/status` | GET | — |
| `ai_filament_profiles/list` | GET | — |
| `ai_filament_profiles/get` | GET | `name` |
| `ai_filament_profiles/set` | POST | `name`, `type`, `brand`, `extruder_temp`, `bed_temp`, `pressure_advance`, `retract_length`, `retract_speed`, `max_speed`, `fan_speed`, `notes` |
| `ai_filament_profiles/suggest` | GET | `type`, `brand` (optional) |

### ai_print_history
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_print_history/status` | GET | — |
| `ai_print_history/list` | GET | `count` (optional) |
| `ai_print_history/trend` | GET | `count` (optional) |

### ai_resonance
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_resonance/status` | GET | — |
| `ai_resonance/test` | POST | `axis` (`x` or `y`) |
| `ai_resonance/belt_check` | POST | — |

### ai_timelapse
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_timelapse/status` | GET | — |
| `ai_timelapse/analyze` | POST | `path` (optional), `max_frames` (optional) |

### ai_notifications
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_notifications/status` | GET | — |
| `ai_notifications/send` | POST | `message` |

### ai_print_recovery
| Endpoint | Method | Parameters |
|----------|--------|------------|
| `ai_print_recovery/status` | GET | — |
| `ai_print_recovery/recover` | POST | — |

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

**"No bed mesh data available"** — Run `BED_MESH_CALIBRATE` before
`AI_MESH_ANALYZE`. The mesh module needs probe data to analyze.

**"Profile not found"** — The filament profile name doesn't exist. Run
`AI_FILAMENT_LIST` to see available profiles.

**"resonance_tester not configured"** — Add `[resonance_tester]` and `[adxl345]`
sections to your printer.cfg before using `AI_RESONANCE_TEST` or `AI_BELT_CHECK`.

**"No timelapse frames found"** — No `.jpg` or `.png` files exist in the frames
directory. Check that your timelapse plugin is saving frames to the configured
`frames_dir`.

**"No notification targets configured"** — At least one of `telegram_bot_token`
+ `telegram_chat_id` or `discord_webhook_url` must be set.

**"Print is not paused"** — `AI_RECOVER` requires the print to be paused first.
Either pause manually or let AI camera detect a failure with
`failure_action: pause`.

**"Maximum recovery attempts reached"** — The print has failed too many times.
Cancel and restart the print. Adjust `max_retries` in `[ai_print_recovery]` if
needed.

**Local model responses are poor quality** — Try a larger model, lower the
temperature to 0.1, or increase `max_tokens`. The 8b models work but larger
models give significantly better analysis.
