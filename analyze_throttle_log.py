#!/usr/bin/env python3
"""
Supra Throttle Log Analyzer
Analyzes debug CSV logs from throttle_simulator.py to detect anomalies and issues.
Updated to work with new comprehensive logging system.
"""

import csv
import sys
import os
from collections import defaultdict, Counter
import statistics
from datetime import datetime
import argparse

class ThrottleLogAnalyzer:
    def __init__(self, csv_file):
        self.csv_file = csv_file
        self.data = []
        self.throttle_ranges = {
            'idle': (0.0, 0.09),
            'light': (0.10, 0.30),
            'aggressive': (0.31, 0.60),
            'violent': (0.61, 0.89),
            'highway': (0.90, 1.00)
        }
        self.anomalies = []
        self.audio_events = []
        self.stability_events = []
        
    def load_data(self):
        """Load CSV data into memory"""
        try:
            with open(self.csv_file, 'r') as file:
                reader = csv.DictReader(file)
                self.data = list(reader)
                
            # Convert numeric fields and handle all possible field names
            for row in self.data:
                # Handle timestamp
                if row.get('timestamp'):
                    row['timestamp'] = float(row['timestamp'])
                # Handle slider position (can be None for some events)
                if row.get('slider_position') and row['slider_position'] != '':
                    try:
                        row['slider_position'] = float(row['slider_position'])
                    except (ValueError, TypeError):
                        row['slider_position'] = None
                # Handle stable flag
                if row.get('stable'):
                    row['stable'] = row['stable'].lower() == 'true'
                    
            print(f"✅ Loaded {len(self.data)} events from {self.csv_file}")
            return True
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            return False
    
    def get_throttle_range_name(self, throttle_value):
        """Get the expected throttle range name for a given value"""
        if throttle_value is None:
            return 'unknown'
            
        for range_name, (min_val, max_val) in self.throttle_ranges.items():
            if min_val <= throttle_value <= max_val:
                return range_name
        return 'out_of_range'
    
    def analyze_basic_stats(self):
        """Generate basic statistics about the log"""
        print("\n" + "="*60)
        print("📊 BASIC STATISTICS")
        print("="*60)
        
        if not self.data:
            print("No data to analyze")
            return
            
        # Event type distribution
        event_types = Counter(row.get('event_type', 'unknown') for row in self.data)
        print(f"\n📈 Event Distribution ({len(self.data)} total events):")
        for event_type, count in event_types.most_common():
            percentage = (count / len(self.data)) * 100
            print(f"  {event_type:20} {count:4d} events ({percentage:5.1f}%)")
            
        # Time span analysis
        timestamps = [row['timestamp'] for row in self.data if row.get('timestamp')]
        if timestamps:
            duration = max(timestamps) - min(timestamps)
            print(f"\n⏱️  Session Duration: {duration:.1f} seconds")
            print(f"   Events per second: {len(self.data) / duration:.1f}")
            
        # Throttle position stats
        throttle_positions = [row['slider_position'] for row in self.data if row.get('slider_position') is not None]
        if throttle_positions:
            print(f"\n🎚️  Throttle Statistics:")
            print(f"   Min position: {min(throttle_positions):.3f} ({min(throttle_positions)*100:.1f}%)")
            print(f"   Max position: {max(throttle_positions):.3f} ({max(throttle_positions)*100:.1f}%)")
            print(f"   Average: {statistics.mean(throttle_positions):.3f} ({statistics.mean(throttle_positions)*100:.1f}%)")
            if len(throttle_positions) > 1:
                print(f"   Std Dev: {statistics.stdev(throttle_positions):.3f}")
    
    def analyze_stability_issues(self):
        """Analyze throttle stability and blocked transitions"""
        print("\n" + "="*60)
        print("⚠️  THROTTLE STABILITY ANALYSIS")
        print("="*60)
        
        stability_checks = [row for row in self.data if row.get('event_type') == 'STABILITY_CHECK']
        blocked_transitions = [row for row in self.data if row.get('event_type') == 'TRANSITION_BLOCKED']
        
        print(f"\n🔍 Stability Checks: {len(stability_checks)}")
        
        if stability_checks:
            stable_count = sum(1 for row in stability_checks if row.get('stable') == 'True')
            unstable_count = len(stability_checks) - stable_count
            print(f"   ✅ Stable: {stable_count}")
            print(f"   ❌ Unstable: {unstable_count}")
            
            if unstable_count > 0:
                print(f"   📊 Stability Rate: {(stable_count / len(stability_checks)) * 100:.1f}%")
        
        print(f"\n🚫 Blocked Transitions: {len(blocked_transitions)}")
        if blocked_transitions:
            reasons = Counter(row.get('reason', 'unknown') for row in blocked_transitions)
            for reason, count in reasons.most_common():
                print(f"   {reason}: {count}")
                
            # Show some examples of blocked transitions
            print(f"\n📋 Example Blocked Transitions:")
            for i, row in enumerate(blocked_transitions[:5]):
                throttle = row.get('slider_position', 'unknown')
                reason = row.get('reason', 'unknown')
                details = row.get('details', '')[:60]
                print(f"   {i+1}. Throttle: {throttle:.3f} - {reason}")
                print(f"      {details}...")
    
    def analyze_audio_discrepancies(self):
        """Find discrepancies between throttle position and audio selection"""
        print("\n" + "="*60)
        print("🎵 AUDIO TRIGGER DISCREPANCIES")
        print("="*60)
        
        audio_events = [row for row in self.data if row.get('event_type') == 'AUDIO_TRIGGERED']
        discrepancies = []
        
        print(f"\n🔊 Audio Events Analyzed: {len(audio_events)}")
        
        for event in audio_events:
            slider_pos = event.get('slider_position')
            selected_range = event.get('throttle_range', '')
            sound_file = event.get('sound_file', '')
            
            if slider_pos is not None:
                expected_range = self.get_throttle_range_name(slider_pos)
                
                if expected_range != selected_range:
                    discrepancies.append({
                        'timestamp': event.get('timestamp'),
                        'slider_position': slider_pos,
                        'expected_range': expected_range,
                        'selected_range': selected_range,
                        'sound_file': sound_file,
                        'difference': abs(slider_pos - self._get_range_center(selected_range))
                    })
        
        print(f"❗ Found {len(discrepancies)} range discrepancies")
        
        if discrepancies:
            # Sort by severity (largest difference)
            discrepancies.sort(key=lambda x: x['difference'], reverse=True)
            
            print(f"\n🚨 Top Range Mismatches:")
            for i, disc in enumerate(discrepancies[:10]):
                slider_pct = disc['slider_position'] * 100
                print(f"   {i+1}. Slider: {slider_pct:5.1f}% → Expected: {disc['expected_range']:10} | "
                      f"Got: {disc['selected_range']:10} | Sound: {disc['sound_file']}")
                      
            # Range distribution analysis
            range_errors = Counter(f"{disc['expected_range']} → {disc['selected_range']}" 
                                 for disc in discrepancies)
            print(f"\n📊 Most Common Range Errors:")
            for error_type, count in range_errors.most_common(5):
                print(f"   {error_type}: {count} times")
    
    def analyze_state_transitions(self):
        """Analyze engine state transitions"""
        print("\n" + "="*60)
        print("🔄 ENGINE STATE TRANSITIONS")
        print("="*60)
        
        state_changes = [row for row in self.data if row.get('event_type') == 'STATE_CHANGE']
        
        if not state_changes:
            print("No state changes found in log")
            return
            
        print(f"\n📈 Total State Changes: {len(state_changes)}")
        
        # Transition types
        transitions = Counter(f"{row.get('from_state', 'unknown')} → {row.get('to_state', 'unknown')}" 
                            for row in state_changes)
        
        print(f"\n🔀 Transition Types:")
        for transition, count in transitions.most_common():
            print(f"   {transition:20} {count:3d} times")
            
        # Analyze problematic transitions
        idle_to_pull = [row for row in state_changes 
                       if row.get('from_state') == 'IDLE' and row.get('to_state') == 'PULL']
        
        if idle_to_pull:
            throttle_values = [row['slider_position'] for row in idle_to_pull 
                             if row.get('slider_position') is not None]
            if throttle_values:
                print(f"\n🎚️  IDLE → PULL Transitions:")
                print(f"   Count: {len(idle_to_pull)}")
                print(f"   Min throttle: {min(throttle_values):.3f} ({min(throttle_values)*100:.1f}%)")
                print(f"   Max throttle: {max(throttle_values):.3f} ({max(throttle_values)*100:.1f}%)")
                print(f"   Avg throttle: {statistics.mean(throttle_values):.3f} ({statistics.mean(throttle_values)*100:.1f}%)")
    
    def analyze_idle_state_issues(self):
        """Analyze issues in IDLE state"""
        print("\n" + "="*60)
        print("🔍 IDLE STATE ANALYSIS")
        print("="*60)
        
        idle_events = [row for row in self.data if row.get('engine_state') == 'IDLE']
        high_throttle_idle = [row for row in idle_events 
                            if row.get('slider_position') is not None and row['slider_position'] > 0.5]
        
        print(f"\n🏃 Total IDLE events: {len(idle_events)}")
        print(f"⚠️  High throttle in IDLE: {len(high_throttle_idle)}")
        
        if high_throttle_idle:
            print(f"\n🚨 Examples of high throttle while in IDLE state:")
            for i, event in enumerate(high_throttle_idle[:5]):
                throttle_pct = event['slider_position'] * 100
                timestamp = event.get('timestamp', 'unknown')
                details = event.get('details', '')[:50]
                print(f"   {i+1}. {throttle_pct:5.1f}% throttle @ {timestamp} - {details}...")
                
        # Check for rapid state changes
        idle_updates = [row for row in self.data if row.get('event_type') == 'IDLE_UPDATE']
        if len(idle_updates) > 1:
            rapid_changes = 0
            for i in range(1, len(idle_updates)):
                prev_throttle = idle_updates[i-1].get('slider_position', 0)
                curr_throttle = idle_updates[i].get('slider_position', 0)
                if abs(curr_throttle - prev_throttle) > 0.1:  # 10% change
                    rapid_changes += 1
                    
            print(f"\n⚡ Rapid throttle changes in IDLE: {rapid_changes}")
    
    def _get_range_center(self, range_name):
        """Get the center value of a throttle range"""
        if range_name in self.throttle_ranges:
            min_val, max_val = self.throttle_ranges[range_name]
            return (min_val + max_val) / 2
        return 0.5
    
    def generate_timeline(self, max_events=50):
        """Generate a timeline of key events"""
        print("\n" + "="*60)
        print("⏰ EVENT TIMELINE (Recent Events)")
        print("="*60)
        
        # Focus on key events
        key_events = [row for row in self.data if row.get('event_type') in [
            'STATE_CHANGE', 'AUDIO_TRIGGERED', 'TRANSITION_BLOCKED', 'AUDIO_FAILED'
        ]]
        
        # Sort by timestamp and take recent events
        key_events.sort(key=lambda x: x.get('timestamp', 0))
        recent_events = key_events[-max_events:] if len(key_events) > max_events else key_events
        
        if not recent_events:
            print("No key events found")
            return
            
        base_time = recent_events[0].get('timestamp', 0)
        
        print(f"\n📋 Showing last {len(recent_events)} key events:")
        print("     Time | Throttle% | Event")
        print("     -----|-----------|" + "-"*50)
        
        for event in recent_events:
            rel_time = event.get('timestamp', 0) - base_time
            throttle = event.get('slider_position')
            throttle_str = f"{throttle*100:5.1f}%" if throttle is not None else " N/A "
            event_type = event.get('event_type', 'unknown')
            
            # Create event description
            if event_type == 'STATE_CHANGE':
                desc = f"{event.get('from_state', '?')} → {event.get('to_state', '?')}"
            elif event_type == 'AUDIO_TRIGGERED':
                desc = f"🔊 {event.get('sound_file', 'unknown')} ({event.get('sound_type', '?')})"
            elif event_type == 'TRANSITION_BLOCKED':
                desc = f"🚫 {event.get('reason', 'unknown')}"
            elif event_type == 'AUDIO_FAILED':
                desc = f"❌ No audio for {event.get('sound_type', '?')}"
            else:
                desc = event_type
                
            print(f"   {rel_time:6.2f}s | {throttle_str} | {desc}")
    
    def _analyze_throttle_change_patterns(self, throttle_changes):
        """Analyze patterns in throttle changes"""
        print(f"\n🌪️  Throttle Change Patterns:")
        
        large_changes = [row for row in throttle_changes 
                        if row.get('change_amount') and abs(float(row['change_amount'])) > 0.2]
        rapid_changes = []
        
        # Find rapid consecutive changes
        for i in range(1, len(throttle_changes)):
            prev_time = throttle_changes[i-1].get('timestamp', 0)
            curr_time = throttle_changes[i].get('timestamp', 0)
            if curr_time - prev_time < 0.5:  # Less than 500ms between changes
                rapid_changes.append(throttle_changes[i])
        
        print(f"   Large changes (>20%): {len(large_changes)}")
        print(f"   Rapid changes (<0.5s apart): {len(rapid_changes)}")
        
        if len(rapid_changes) > 10:
            self.anomalies.append({
                'type': 'EXCESSIVE_RAPID_CHANGES',
                'timestamp': rapid_changes[-1].get('timestamp', 0),
                'severity': 'MEDIUM',
                'description': f"Excessive rapid throttle changes: {len(rapid_changes)} changes in <0.5s intervals"
            })
    
    def generate_anomaly_summary(self):
        """Generate summary of all detected anomalies"""
        if not self.anomalies:
            return
            
        print("\n" + "="*60)
        print(f"🚨 ANOMALY SUMMARY ({len(self.anomalies)} issues found)")
        print("="*60)
        
        # Group by severity
        severity_counts = Counter(anomaly['severity'] for anomaly in self.anomalies)
        print(f"\n📊 By Severity:")
        for severity in ['HIGH', 'MEDIUM', 'LOW']:
            count = severity_counts.get(severity, 0)
            if count > 0:
                print(f"   {severity}: {count}")
        
        # Group by type
        type_counts = Counter(anomaly['type'] for anomaly in self.anomalies)
        print(f"\n📋 By Type:")
        for anomaly_type, count in type_counts.most_common():
            print(f"   {anomaly_type}: {count}")
        
        # Show critical anomalies
        critical = [a for a in self.anomalies if a['severity'] == 'HIGH']
        if critical:
            print(f"\n🚨 Critical Issues (HIGH severity):")
            for i, anomaly in enumerate(critical[:10], 1):
                timestamp = anomaly.get('timestamp', 0)
                desc = anomaly.get('description', 'Unknown issue')
                print(f"   {i:2d}. [{timestamp:7.1f}s] {desc}")
    
    def run_full_analysis(self):
        """Run complete analysis suite"""
        print("🔍 ENHANCED SUPRA THROTTLE LOG ANALYZER")
        print(f"📄 Analyzing: {os.path.basename(self.csv_file)}")
        
        if not self.load_data():
            return
            
        self.analyze_basic_stats()
        self.analyze_stability_issues()
        self.analyze_audio_events()  # Updated method name
        self.analyze_state_transitions()
        self.analyze_idle_state_issues()
        self.generate_comprehensive_timeline()  # Updated method name
        self.generate_anomaly_summary()  # New method
        
        print("\n" + "="*60)
        print("✅ ENHANCED ANALYSIS COMPLETE")
        print("="*60)
        print("\nKey findings to review:")
        print("• Range mismatches between throttle position and selected audio")
        print("• Blocked or failed audio events at critical throttle levels")
        print("• Excessive throttle instability preventing state transitions")
        print("• High throttle values stuck in IDLE state")
        print("• Rapid throttle changes causing system instability")
        
        return len(self.anomalies)

def main():
    parser = argparse.ArgumentParser(description='Enhanced Supra Throttle Log Analyzer')
    parser.add_argument('csv_file', help='Path to the CSV debug log file')
    parser.add_argument('--output', '-o', help='Save detailed report to file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show more detailed output')
    parser.add_argument('--timeline', '-t', type=int, default=50, help='Number of timeline events to show (default: 50)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.csv_file):
        print(f"❌ File not found: {args.csv_file}")
        sys.exit(1)
        
    analyzer = ThrottleLogAnalyzer(args.csv_file)
    anomaly_count = analyzer.run_full_analysis()
    
    # Save report if requested
    if args.output:
        print(f"\n💾 Saving detailed report to {args.output}...")
        with open(args.output, 'w') as f:
            import sys
            old_stdout = sys.stdout
            sys.stdout = f
            analyzer.run_full_analysis()
            sys.stdout = old_stdout
        print(f"Report saved successfully!")
        
    # Summary
    print(f"\n📊 Analysis Summary: {anomaly_count} anomalies detected")
    if anomaly_count > 0:
        print("❗ Review the anomaly summary above for critical issues")
    else:
        print("✅ No significant issues detected")
        
    return 0 if anomaly_count < 5 else 1  # Return error code if many issues

if __name__ == "__main__":
    main()