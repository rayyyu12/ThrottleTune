# M4 Supra Electric Scooter Sound System

This system provides realistic engine sounds for electric scooters, supporting both M4 and Supra sound profiles with throttle-based audio playback.

## Recent Updates

### ✅ Fixed Issues
- **M4 Acceleration Timing**: Added 0.5s offset to acceleration sounds to skip initial silence
- **Supra Throttle Stabilization**: Added 0.5s delay before sound selection to prevent incorrect audio when rapidly accelerating
- **Supra Volume Restoration**: Fixed idle volume restoration after rev sounds complete
- **Supra State Machine**: Improved transition logic in ENDING_CLIP state
- **Error Handling**: Enhanced error reporting for missing Supra sound files

### 🔧 Button Controls
- **Short Press**: Switch between M4 and Supra (plays rev sound when switching)
- **Long Press (2+ seconds)**: Shutdown the script

## Installation for Auto-Startup

### Option 1: Automatic Installation (Recommended)
```bash
sudo ./install_service.sh
```

### Option 2: Manual Installation
1. Copy files to `/home/pi/M4HCSUP/`
2. Copy the service file:
   ```bash
   sudo cp m4-supra-sound.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable m4-supra-sound
   ```

## Service Management

```bash
# Start the service
sudo systemctl start m4-supra-sound

# Stop the service  
sudo systemctl stop m4-supra-sound

# Check status
sudo systemctl status m4-supra-sound

# View logs
sudo journalctl -u m4-supra-sound -f

# Disable auto-start
sudo systemctl disable m4-supra-sound
```

## Sound System Overview

### M4 Sound Profile
- **Staged Rev System**: 4-stage rev sounds based on RPM simulation
- **Launch Control**: Hold throttle 55-85% for 0.5s to engage
- **Acceleration**: Sustained 98%+ throttle triggers full acceleration sequence
- **Cruising**: Automatic cruising loops during sustained high throttle
- **Deceleration**: Smooth downshift sounds when letting off throttle

### Supra Sound Profile  
- **Idle**: Continuous idle loop
- **Light Throttle (10-30%)**: Light pulls and cruise sounds
- **Aggressive Throttle (31-60%)**: Aggressive push sounds (6 variations)
- **Violent Throttle (61-100%)**: Violent pull sounds (3 variations)
- **Rev Gestures**: Quick throttle blips trigger rev sounds
- **Throttle Stabilization**: 0.5s delay prevents wrong sound selection during rapid acceleration

## Hardware Requirements

- Raspberry Pi with GPIO access
- MCP3008 ADC chip
- Push button on GPIO 17
- Audio output (speakers/amplifier)
- Throttle input (potentiometer/Hall sensor)

## Configuration

Key parameters can be adjusted in the Python script:
- `M4_ACCELERATION_SOUND_OFFSET`: Delay for M4 acceleration sounds (default: 0.5s)
- `SUPRA_THROTTLE_STABILIZATION_DELAY`: Throttle reading delay for Supra (default: 0.5s)
- `MASTER_ENGINE_VOL`: Overall volume level
- Throttle ranges and other timing parameters

## Troubleshooting

### No Sound
- Check audio output and volume levels
- Verify sound files exist in `m4/` and `supra/` directories
- Check service logs: `sudo journalctl -u m4-supra-sound -f`

### Incorrect Throttle Response
- Adjust `MIN_ADC_VALUE` and `MAX_ADC_VALUE` for your hardware
- Check ADC wiring and power supply
- Verify throttle calibration

### Service Won't Start
- Check Python dependencies: `pygame`, `RPi.GPIO`, `adafruit-circuitpython-mcp3xxx`
- Verify file permissions and paths
- Check systemd logs: `sudo systemctl status m4-supra-sound`

## Dependencies

Install required packages:
```bash
sudo pip3 install pygame RPi.GPIO adafruit-circuitpython-mcp3xxx
```