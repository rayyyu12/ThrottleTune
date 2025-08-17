#!/usr/bin/env python3
"""
M4/Supra Sound System Log Analyzer
Analyzes CSV logs to identify timing issues, anomalies, and sound playback problems.
"""

import csv
import sys
import os
from datetime import datetime
from collections import defaultdict
import argparse

class LogAnalyzer:
    def __init__(self, csv_file):
        self.csv_file = csv_file
        self.data = []
        self.anomalies = []
        self.sound_events = []
        self.car_switches = []
        
    def load_data(self):
        """Load CSV data into memory"""
        try:
            with open(self.csv_file, 'r') as f:
                reader = csv.DictReader(f)
                self.data = list(reader)
            print(f"Loaded {len(self.data)} log entries from {self.csv_file}")
            return True
        except FileNotFoundError:
            print(f"ERROR: File {self.csv_file} not found!")
            return False
        except Exception as e:
            print(f"ERROR loading CSV: {e}")
            return False
    
    def extract_sound_events(self):
        """Extract sound start/stop events from the log data"""
        print("Extracting sound events...")
        
        # Track previous state to detect changes
        prev_m4_sounds = {}
        prev_supra_sounds = {}
        prev_car = None
        
        for i, row in enumerate(self.data):
            timestamp = float(row.get('timestamp_unix', 0))
            car = row.get('active_car', 'Unknown')
            state = row.get('state', 'Unknown')
            throttle = float(row.get('smoothed_throttle_pct', 0))
            
            # Track car switches
            if prev_car and prev_car != car:
                self.car_switches.append({
                    'timestamp': timestamp,
                    'from_car': prev_car,
                    'to_car': car,
                    'row_index': i
                })
                print(f"Car switch detected at {timestamp:.1f}s: {prev_car} -> {car}")
            
            prev_car = car
            
            if car == "M4":
                self._extract_m4_events(row, i, timestamp, state, throttle, prev_m4_sounds)
            elif car == "Supra":
                self._extract_supra_events(row, i, timestamp, state, throttle, prev_supra_sounds)
    
    def _extract_m4_events(self, row, index, timestamp, state, throttle, prev_sounds):
        """Extract M4-specific sound events"""
        current_sounds = {
            'idle_busy': row.get('idle_chan_busy', 'False') == 'True',
            'staged_rev_busy': row.get('m4_staged_rev_chan_busy', 'False') == 'True',
            'staged_rev_sound': row.get('m4_staged_rev_chan_sound', 'None'),
            'sfx_busy': row.get('m4_sfx_chan_busy', 'False') == 'True',
            'sfx_sound': row.get('m4_sfx_chan_sound', 'None'),
            'long_A_busy': row.get('m4_long_A_busy', 'False') == 'True',
            'long_A_sound': row.get('m4_long_A_sound', 'None'),
            'long_B_busy': row.get('m4_long_B_busy', 'False') == 'True',
            'long_B_sound': row.get('m4_long_B_sound', 'None'),
            'lc_active': row.get('m4_is_lc_active_overall', 'False') == 'True',
            'time_at_100': float(row.get('m4_time_@100thr', 0))
        }
        
        # Detect sound starts
        for sound_type in ['staged_rev', 'sfx', 'long_A', 'long_B']:
            busy_key = f'{sound_type}_busy'
            sound_key = f'{sound_type}_sound'
            
            prev_busy = prev_sounds.get(busy_key, False)
            curr_busy = current_sounds[busy_key]
            curr_sound = current_sounds[sound_key]
            
            # Sound started
            if not prev_busy and curr_busy and curr_sound != 'None':
                event = {
                    'timestamp': timestamp,
                    'car': 'M4',
                    'event': 'sound_start',
                    'channel': sound_type,
                    'sound': curr_sound,
                    'state': state,
                    'throttle': throttle,
                    'row_index': index
                }
                self.sound_events.append(event)
                print(f"M4 Sound Start: {curr_sound} on {sound_type} at {timestamp:.1f}s (throttle: {throttle:.2f}, state: {state})")
            
            # Sound stopped
            elif prev_busy and not curr_busy:
                prev_sound = prev_sounds.get(sound_key, 'Unknown')
                event = {
                    'timestamp': timestamp,
                    'car': 'M4',
                    'event': 'sound_stop',
                    'channel': sound_type,
                    'sound': prev_sound,
                    'state': state,
                    'throttle': throttle,
                    'row_index': index
                }
                self.sound_events.append(event)
        
        # Update previous state
        prev_sounds.update(current_sounds)
    
    def _extract_supra_events(self, row, index, timestamp, state, throttle, prev_sounds):
        """Extract Supra-specific sound events"""
        current_sounds = {
            'idle_busy': row.get('idle_chan_busy', 'False') == 'True',
            'driving_A_busy': row.get('supra_driving_A_busy', 'False') == 'True',
            'driving_A_sound': row.get('supra_driving_A_sound', 'None'),
            'driving_B_busy': row.get('supra_driving_B_busy', 'False') == 'True',
            'driving_B_sound': row.get('supra_driving_B_sound', 'None'),
            'rev_sfx_busy': row.get('supra_rev_sfx_busy', 'False') == 'True',
            'rev_sfx_sound': row.get('supra_rev_sfx_sound', 'None')
        }
        
        # Detect sound starts
        for sound_type in ['driving_A', 'driving_B', 'rev_sfx']:
            busy_key = f'{sound_type}_busy'
            sound_key = f'{sound_type}_sound'
            
            prev_busy = prev_sounds.get(busy_key, False)
            curr_busy = current_sounds[busy_key]
            curr_sound = current_sounds[sound_key]
            
            # Sound started
            if not prev_busy and curr_busy and curr_sound != 'None':
                event = {
                    'timestamp': timestamp,
                    'car': 'Supra',
                    'event': 'sound_start',
                    'channel': sound_type,
                    'sound': curr_sound,
                    'state': state,
                    'throttle': throttle,
                    'row_index': index
                }
                self.sound_events.append(event)
                print(f"Supra Sound Start: {curr_sound} on {sound_type} at {timestamp:.1f}s (throttle: {throttle:.2f}, state: {state})")
            
            # Sound stopped
            elif prev_busy and not curr_busy:
                prev_sound = prev_sounds.get(sound_key, 'Unknown')
                event = {
                    'timestamp': timestamp,
                    'car': 'Supra',
                    'event': 'sound_stop',
                    'channel': sound_type,
                    'sound': prev_sound,
                    'state': state,
                    'throttle': throttle,
                    'row_index': index
                }
                self.sound_events.append(event)
        
        # Update previous state
        prev_sounds.update(current_sounds)
    
    def analyze_m4_acceleration_delays(self):
        """Analyze M4 acceleration delays - time from 100% throttle to acceleration sound start"""
        print("\\nAnalyzing M4 acceleration delays...")
        
        # Find periods of sustained 100% throttle
        high_throttle_periods = []
        current_period = None
        
        for i, row in enumerate(self.data):
            if row.get('active_car') != 'M4':
                continue
                
            timestamp = float(row.get('timestamp_unix', 0))
            throttle = float(row.get('smoothed_throttle_pct', 0))
            state = row.get('state', '')
            time_at_100 = float(row.get('m4_time_@100thr', 0))
            
            # Start of high throttle period
            if throttle >= 0.95 and current_period is None:
                current_period = {
                    'start_time': timestamp,
                    'start_index': i,
                    'peak_throttle': throttle,
                    'initial_state': state
                }
            
            # Update current period
            elif throttle >= 0.95 and current_period:
                current_period['peak_throttle'] = max(current_period['peak_throttle'], throttle)
                current_period['end_time'] = timestamp
                current_period['end_index'] = i
                current_period['time_at_100'] = time_at_100
            
            # End of high throttle period
            elif throttle < 0.90 and current_period:
                current_period['duration'] = current_period.get('end_time', timestamp) - current_period['start_time']
                if current_period['duration'] >= 0.5:  # Only consider significant periods
                    high_throttle_periods.append(current_period)
                current_period = None
        
        # Find acceleration sound starts near these periods
        accel_delays = []
        for period in high_throttle_periods:
            # Look for acceleration sounds within 5 seconds after throttle start
            search_start = period['start_time']
            search_end = period['start_time'] + 5.0
            
            accel_sounds = [e for e in self.sound_events 
                          if e['car'] == 'M4' 
                          and e['event'] == 'sound_start'
                          and 'accel' in e['sound'].lower()
                          and search_start <= e['timestamp'] <= search_end]
            
            if accel_sounds:
                # Found acceleration sound
                accel_event = accel_sounds[0]  # Take the first one
                delay = accel_event['timestamp'] - period['start_time']
                
                delay_info = {
                    'throttle_start': period['start_time'],
                    'accel_start': accel_event['timestamp'],
                    'delay': delay,
                    'peak_throttle': period['peak_throttle'],
                    'duration': period['duration'],
                    'sound': accel_event['sound'],
                    'initial_state': period['initial_state']
                }
                accel_delays.append(delay_info)
                
                if delay > 1.0:  # Flag significant delays
                    self.anomalies.append({
                        'type': 'M4_ACCELERATION_DELAY',
                        'timestamp': period['start_time'],
                        'delay': delay,
                        'description': f"M4 acceleration sound '{accel_event['sound']}' started {delay:.1f}s after reaching 100% throttle",
                        'severity': 'HIGH' if delay > 2.0 else 'MEDIUM'
                    })
            else:
                # No acceleration sound found
                self.anomalies.append({
                    'type': 'M4_MISSING_ACCELERATION',
                    'timestamp': period['start_time'],
                    'description': f"M4 reached 100% throttle for {period['duration']:.1f}s but no acceleration sound played",
                    'severity': 'HIGH'
                })
        
        if accel_delays:
            avg_delay = sum(d['delay'] for d in accel_delays) / len(accel_delays)
            max_delay = max(d['delay'] for d in accel_delays)
            print(f"Found {len(accel_delays)} acceleration events")
            print(f"Average delay: {avg_delay:.2f}s")
            print(f"Maximum delay: {max_delay:.2f}s")
            
            for delay in sorted(accel_delays, key=lambda x: x['delay'], reverse=True):
                print(f"  Delay: {delay['delay']:.2f}s - {delay['sound']} (throttle: {delay['peak_throttle']:.2f})")
    
    def analyze_supra_timing_issues(self):
        """Analyze Supra sound timing issues"""
        print("\\nAnalyzing Supra timing issues...")
        
        # Look for sounds playing at inappropriate throttle levels
        for event in self.sound_events:
            if event['car'] != 'Supra' or event['event'] != 'sound_start':
                continue
                
            sound = event['sound']
            throttle = event['throttle']
            
            # Check if sound matches expected throttle range
            expected_range = self._get_supra_expected_throttle_range(sound)
            if expected_range and not (expected_range[0] <= throttle <= expected_range[1]):
                self.anomalies.append({
                    'type': 'SUPRA_WRONG_THROTTLE_RANGE',
                    'timestamp': event['timestamp'],
                    'sound': sound,
                    'throttle': throttle,
                    'expected_range': expected_range,
                    'description': f"Supra '{sound}' played at {throttle:.1f}% throttle (expected {expected_range[0]:.0f}-{expected_range[1]:.0f}%)",
                    'severity': 'MEDIUM'
                })
        
        # Look for rapid sound switching (potential stabilization issues)
        supra_events = [e for e in self.sound_events if e['car'] == 'Supra' and 'driving' in e['channel']]
        
        for i in range(1, len(supra_events)):
            prev_event = supra_events[i-1]
            curr_event = supra_events[i]
            
            time_diff = curr_event['timestamp'] - prev_event['timestamp']
            
            # Flag rapid sound switches
            if time_diff < 1.0 and prev_event['event'] == 'sound_start' and curr_event['event'] == 'sound_start':
                self.anomalies.append({
                    'type': 'SUPRA_RAPID_SOUND_SWITCH',
                    'timestamp': curr_event['timestamp'],
                    'description': f"Supra rapid sound switch: {prev_event['sound']} -> {curr_event['sound']} in {time_diff:.1f}s",
                    'severity': 'LOW'
                })
    
    def _get_supra_expected_throttle_range(self, sound):
        """Get expected throttle range for a Supra sound"""
        sound = sound.lower()
        
        if 'light' in sound:
            return (10, 30)  # 10-30% throttle
        elif 'aggressive' in sound:
            return (31, 60)  # 31-60% throttle  
        elif 'violent' in sound:
            return (61, 100)  # 61-100% throttle
        elif 'rev' in sound:
            return (0, 100)  # Rev sounds can happen at any throttle during gesture
        elif 'startup' in sound:
            return (0, 20)   # Startup should be at low throttle
        
        return None  # Unknown sound
    
    def analyze_general_anomalies(self):
        """Analyze general anomalies across both cars"""
        print("\\nAnalyzing general anomalies...")
        
        # Look for missing idle sounds
        for i, row in enumerate(self.data):
            state = row.get('state', '')
            idle_busy = row.get('idle_chan_busy', 'False') == 'True'
            car = row.get('active_car', '')
            
            # Should have idle in IDLE state
            if state in ['IDLE', 'IDLING'] and not idle_busy:
                timestamp = float(row.get('timestamp_unix', 0))
                self.anomalies.append({
                    'type': 'MISSING_IDLE_SOUND',
                    'timestamp': timestamp,
                    'car': car,
                    'description': f"{car} in {state} state but idle sound not playing",
                    'severity': 'MEDIUM'
                })
        
        # Look for multiple sounds playing simultaneously (potential conflicts)
        for i, row in enumerate(self.data):
            car = row.get('active_car', '')
            timestamp = float(row.get('timestamp_unix', 0))
            
            if car == 'M4':
                active_channels = []
                if row.get('m4_staged_rev_chan_busy') == 'True':
                    active_channels.append('staged_rev')
                if row.get('m4_long_A_busy') == 'True':
                    active_channels.append('long_A')
                if row.get('m4_long_B_busy') == 'True':
                    active_channels.append('long_B')
                
                if len(active_channels) > 1:
                    self.anomalies.append({
                        'type': 'M4_MULTIPLE_CHANNELS',
                        'timestamp': timestamp,
                        'channels': active_channels,
                        'description': f"M4 multiple sound channels active: {', '.join(active_channels)}",
                        'severity': 'LOW'
                    })
            
            elif car == 'Supra':
                active_channels = []
                if row.get('supra_driving_A_busy') == 'True':
                    active_channels.append('driving_A')
                if row.get('supra_driving_B_busy') == 'True':
                    active_channels.append('driving_B')
                
                if len(active_channels) > 1:
                    self.anomalies.append({
                        'type': 'SUPRA_MULTIPLE_CHANNELS',
                        'timestamp': timestamp,
                        'channels': active_channels,
                        'description': f"Supra multiple driving channels active: {', '.join(active_channels)}",
                        'severity': 'LOW'
                    })
    
    def generate_report(self):
        """Generate comprehensive analysis report"""
        print("\\n" + "="*80)
        print("M4/SUPRA SOUND SYSTEM LOG ANALYSIS REPORT")
        print("="*80)
        
        if not self.data:
            print("No data loaded!")
            return
        
        # Basic statistics
        total_time = float(self.data[-1].get('timestamp_unix', 0)) - float(self.data[0].get('timestamp_unix', 0))
        print(f"\\nSESSION INFO:")
        print(f"Duration: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
        print(f"Total log entries: {len(self.data)}")
        print(f"Car switches: {len(self.car_switches)}")
        print(f"Sound events: {len(self.sound_events)}")
        
        # Car usage statistics
        car_time = defaultdict(float)
        prev_timestamp = None
        prev_car = None
        
        for row in self.data:
            timestamp = float(row.get('timestamp_unix', 0))
            car = row.get('active_car', 'Unknown')
            
            if prev_timestamp and prev_car:
                dt = timestamp - prev_timestamp
                car_time[prev_car] += dt
            
            prev_timestamp = timestamp
            prev_car = car
        
        print(f"\\nCAR USAGE:")
        for car, time_used in car_time.items():
            percentage = (time_used / total_time) * 100 if total_time > 0 else 0
            print(f"{car}: {time_used:.1f}s ({percentage:.1f}%)")
        
        # Sound events by car
        m4_events = [e for e in self.sound_events if e['car'] == 'M4']
        supra_events = [e for e in self.sound_events if e['car'] == 'Supra']
        
        print(f"\\nSOUND EVENTS:")
        print(f"M4 events: {len(m4_events)}")
        print(f"Supra events: {len(supra_events)}")
        
        # Anomalies summary
        print(f"\\nANOMALIES DETECTED: {len(self.anomalies)}")
        
        severity_counts = defaultdict(int)
        type_counts = defaultdict(int)
        
        for anomaly in self.anomalies:
            severity_counts[anomaly['severity']] += 1
            type_counts[anomaly['type']] += 1
        
        print(f"By severity:")
        for severity, count in severity_counts.items():
            print(f"  {severity}: {count}")
        
        print(f"\\nBy type:")
        for anom_type, count in type_counts.items():
            print(f"  {anom_type}: {count}")
        
        # Detailed anomaly list
        if self.anomalies:
            print(f"\\nDETAILED ANOMALIES:")
            print("-" * 80)
            
            # Sort by timestamp
            sorted_anomalies = sorted(self.anomalies, key=lambda x: x['timestamp'])
            
            for i, anomaly in enumerate(sorted_anomalies, 1):
                print(f"{i:3d}. [{anomaly['severity']:6s}] {anomaly['type']}")
                print(f"     Time: {anomaly['timestamp']:.1f}s")
                print(f"     Desc: {anomaly['description']}")
                if 'delay' in anomaly:
                    print(f"     Delay: {anomaly['delay']:.2f}s")
                print()
        
        # Sound timeline (recent events)
        print(f"\\nRECENT SOUND EVENTS (last 20):")
        print("-" * 80)
        recent_events = sorted(self.sound_events, key=lambda x: x['timestamp'])[-20:]
        
        for event in recent_events:
            action = "START" if event['event'] == 'sound_start' else "STOP "
            print(f"{event['timestamp']:8.1f}s [{action}] {event['car']:5s} {event['channel']:12s} {event['sound']:25s} (throttle: {event['throttle']:5.1f}%, state: {event['state']})")
    
    def save_detailed_report(self, output_file=None):
        """Save detailed report to file"""
        if not output_file:
            base_name = os.path.splitext(self.csv_file)[0]
            output_file = f"{base_name}_analysis_report.txt"
        
        print(f"\\nSaving detailed report to {output_file}...")
        
        with open(output_file, 'w') as f:
            # Redirect print to file
            import sys
            old_stdout = sys.stdout
            sys.stdout = f
            
            self.generate_report()
            
            # Additional detailed data
            print("\\n\\nFULL SOUND EVENT LOG:")
            print("="*80)
            for event in sorted(self.sound_events, key=lambda x: x['timestamp']):
                action = "START" if event['event'] == 'sound_start' else "STOP "
                print(f"{event['timestamp']:8.1f}s [{action}] {event['car']:5s} {event['channel']:12s} {event['sound']:25s} (throttle: {event['throttle']:5.1f}%, state: {event['state']})")
            
            # Restore stdout
            sys.stdout = old_stdout
        
        print(f"Report saved to {output_file}")

def main():
    parser = argparse.ArgumentParser(description='Analyze M4/Supra sound system logs')
    parser.add_argument('csv_file', help='Path to the CSV log file')
    parser.add_argument('--output', '-o', help='Output file for detailed report')
    parser.add_argument('--quiet', '-q', action='store_true', help='Reduce output verbosity')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.csv_file):
        print(f"ERROR: File {args.csv_file} does not exist!")
        sys.exit(1)
    
    analyzer = LogAnalyzer(args.csv_file)
    
    if not analyzer.load_data():
        sys.exit(1)
    
    # Set verbosity
    if args.quiet:
        import sys
        sys.stdout = open(os.devnull, 'w')
    
    # Run analysis
    analyzer.extract_sound_events()
    analyzer.analyze_m4_acceleration_delays()
    analyzer.analyze_supra_timing_issues() 
    analyzer.analyze_general_anomalies()
    
    # Restore output if was quiet
    if args.quiet:
        sys.stdout = sys.__stdout__
    
    # Generate report
    analyzer.generate_report()
    
    # Save detailed report
    analyzer.save_detailed_report(args.output)

if __name__ == "__main__":
    main()