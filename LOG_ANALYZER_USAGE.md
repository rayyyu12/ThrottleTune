# Log Analyzer Usage Guide

The `analyze_logs.py` script analyzes your CSV log files to identify timing issues and sound anomalies.

## Quick Usage

```bash
# Basic analysis
python3 analyze_logs.py dual_car_sound_log.csv

# Save detailed report to file
python3 analyze_logs.py dual_car_sound_log.csv --output my_analysis.txt

# Quiet mode (less verbose output)
python3 analyze_logs.py dual_car_sound_log.csv --quiet
```

## What It Detects

### 🚗 **M4 Issues**
- **Acceleration Delays**: Measures time from 100% throttle to acceleration sound start
- **Missing Acceleration**: When 100% throttle doesn't trigger acceleration sounds
- **Multiple Channels**: When multiple sound channels play simultaneously

### 🏎️ **Supra Issues**  
- **Wrong Throttle Range**: When sounds play outside their expected throttle ranges
  - Light sounds (10-30% throttle) playing at high throttle
  - Violent sounds (61-100% throttle) playing at low throttle
- **Rapid Sound Switching**: Quick changes between sounds (potential stabilization issues)

### 🔧 **General Issues**
- **Missing Idle**: When car is in IDLE state but idle sound isn't playing
- **Channel Conflicts**: Multiple driving channels active simultaneously
- **Car Switch Events**: Tracks when you switch between M4/Supra

## Sample Output

```
M4/SUPRA SOUND SYSTEM LOG ANALYSIS REPORT
===============================================================================

SESSION INFO:
Duration: 245.3 seconds (4.1 minutes)
Total log entries: 14718
Car switches: 3
Sound events: 47

CAR USAGE:
M4: 156.2s (63.7%)
Supra: 89.1s (36.3%)

ANOMALIES DETECTED: 8

By severity:
  HIGH: 3
  MEDIUM: 4
  LOW: 1

DETAILED ANOMALIES:
--------------------------------------------------------------------------------
  1. [  HIGH ] M4_ACCELERATION_DELAY
     Time: 45.2s
     Desc: M4 acceleration sound 'accel_gears' started 2.3s after reaching 100% throttle
     Delay: 2.30s

  2. [MEDIUM] SUPRA_WRONG_THROTTLE_RANGE
     Time: 78.5s
     Desc: Supra 'violent_pull_2' played at 25% throttle (expected 61-100%)
```

## Analyzing Your Issues

### For the M4 Acceleration Delay Issue:
Look for `M4_ACCELERATION_DELAY` anomalies in the output. The script will show:
- Exact delay time from 100% throttle to sound start
- Which acceleration sound played
- Initial state when throttle was applied

### For Supra "Weird Timing" Issues:
Look for:
- `SUPRA_WRONG_THROTTLE_RANGE`: Wrong sounds for throttle level
- `SUPRA_RAPID_SOUND_SWITCH`: Too-quick sound changes
- Sound event timeline showing what played when

## Files Generated

- **Console Output**: Summary of major issues
- **Detailed Report** (`--output file.txt`): Complete timeline of all sound events and anomalies

This will help you pinpoint exactly when and why sounds are misbehaving!