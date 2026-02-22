# Project Overview

This directory contains the configuration files for a 3D printer running the Klipper firmware. The printer is controlled by a Raspberry Pi and uses an Azteeg X5 Mini v3 controller board. The web interface is provided by Mainsail and Moonraker.

**Key Technologies:**

*   **Firmware:** Klipper
*   **Controller:** Azteeg X5 Mini v3
*   **Host:** Raspberry Pi
*   **Web Interface:** Mainsail, Moonraker
*   **Other:** KlipperScreen, Crowsnest (for webcam), Timelapse

# Building and Running

This is a configuration-only project, so there is no code to build or compile. The Klipper firmware is already compiled and flashed to the controller board.

To run the printer, you need to:

1.  Power on the Raspberry Pi and the printer.
2.  Access the Mainsail web interface by navigating to the Raspberry Pi's IP address in a web browser.
3.  Upload G-code files to the `~/printer_data/gcodes` directory.
4.  Start a print from the Mainsail interface.

# Development Conventions

*   **Configuration Files:** All configuration is done in `.cfg` files. The main configuration file is `printer.cfg`.
*   **Macros:** Custom G-code macros are defined in `macros.cfg`.
*   **Includes:** The `printer.cfg` file includes other configuration files using the `[include]` directive.
*   **Saving Configuration:** Changes to the configuration can be saved using the `SAVE_CONFIG` command in the Klipper console.

